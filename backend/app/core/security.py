"""Authentication, authorization and patient-isolation helpers."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.records import Consent, DentistAssignment
from app.models.user import User

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

CLINICAL_ROLES = {"dentist"}
REQUIRED_PATIENT_CONSENTS = {"ai_analysis", "data_processing", "privacy_notice"}
CONSENT_VERSION = "2026-09"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> None:
    checks = [len(password) >= 10, any(c.isalpha() for c in password), any(c.isdigit() for c in password)]
    if not all(checks):
        raise HTTPException(422, "Password must be at least 10 characters and include letters and numbers")


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id, "role": user.role, "tv": user.token_version or 0, "jti": uuid.uuid4().hex,
        "iat": now, "exp": now + timedelta(minutes=settings.jwt_access_token_minutes), "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    error = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise error
    if payload.get("typ") != "access" or not payload.get("sub"):
        raise error
    user = db.query(User).filter(User.id == payload["sub"], User.is_active.is_(True), User.deleted_at.is_(None)).first()
    if not user or int(payload.get("tv", -1)) != (user.token_version or 0):
        raise error
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to access this resource")
        return user
    return dependency


def is_assigned(db: Session, dentist_id: str, patient_id: str) -> bool:
    return db.query(DentistAssignment).filter(
        DentistAssignment.dentist_user_id == dentist_id,
        DentistAssignment.patient_user_id == patient_id,
        DentistAssignment.active.is_(True),
    ).first() is not None


def ensure_patient_access(db: Session, user: User, patient_id: str, *, clinical: bool = True) -> User:
    """Patients: own data only. Dentists: assigned patients only. Admins: no clinical content."""
    patient = db.query(User).filter(User.id == patient_id, User.role == "patient", User.deleted_at.is_(None)).first()
    if user.role == "patient":
        if patient_id != user.id:
            raise HTTPException(403, "Patients can only access their own records")
    elif user.role == "dentist":
        if not patient or not is_assigned(db, user.id, patient_id):
            raise HTTPException(403, "This patient is not assigned to you")
    elif user.role == "admin":
        if clinical:
            raise HTTPException(403, "Administrators do not have access to clinical content")
    else:
        raise HTTPException(403, "Not permitted")
    if not patient:
        raise HTTPException(404, "Patient not found")
    return patient


def resolve_patient(db: Session, user: User, patient_id: str | None) -> User:
    """Patients act on themselves; dentists must name an assigned patient."""
    if user.role == "patient":
        if patient_id and patient_id != user.id:
            raise HTTPException(403, "Patients can only act on their own records")
        return user
    if user.role == "dentist":
        if not patient_id:
            raise HTTPException(422, "patient_id is required for dentist actions")
        return ensure_patient_access(db, user, patient_id)
    raise HTTPException(403, "Administrators cannot submit clinical data")


def missing_consents(db: Session, patient_id: str) -> list[str]:
    rows = db.query(Consent).filter(Consent.user_id == patient_id).order_by(Consent.created_at.asc()).all()
    latest: dict[str, Consent] = {}
    for row in rows:
        latest[row.consent_type] = row
    return sorted(t for t in REQUIRED_PATIENT_CONSENTS if not (t in latest and latest[t].accepted and latest[t].version == CONSENT_VERSION))


def require_consent(db: Session, patient_id: str) -> None:
    """AI processing is blocked until the patient has accepted the current consent version."""
    missing = missing_consents(db, patient_id)
    if missing:
        raise HTTPException(403, {"code": "consent_required", "message": "Patient consent is required before AI processing", "missing": missing, "version": CONSENT_VERSION})
