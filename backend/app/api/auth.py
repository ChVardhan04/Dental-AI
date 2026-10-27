from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, hash_password, validate_password_strength, verify_password
from app.models.records import PatientProfile
from app.models.user import User, utcnow
from app.schemas.auth import ChangePasswordRequest, ProfileOut, ProfileUpdate, RegisterRequest, TokenOut, UserOut
from app.services.audit import log_event

router = APIRouter(prefix="/auth", tags=["Authentication"])
MAX_FAILED = 5
LOCK_MINUTES = 15
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password-1")


def _token(user: User) -> dict:
    return {"access_token": create_access_token(user), "expires_in": settings.jwt_access_token_minutes * 60, "user": user}


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    validate_password_strength(payload.password)
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists")
    user = User(full_name=payload.full_name.strip(), email=email, password_hash=hash_password(payload.password), role="patient")
    db.add(user)
    db.flush()
    db.add(PatientProfile(user_id=user.id, date_of_birth=payload.date_of_birth, phone=payload.phone))
    log_event(db, user.id, "account.registered", "user", user.id, {"role": user.role}, actor_role=user.role, patient_id=user.id)
    db.commit()
    return _token(user)


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower().strip()).first()
    now = utcnow()
    if user and user.locked_until:
        locked = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=now.tzinfo)
        if locked > now:
            raise HTTPException(429, "Account temporarily locked after repeated failed sign-ins. Try again later.")
    ok = verify_password(form.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active or user.deleted_at:
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
            log_event(db, user.id, "auth.login_failed", "user", user.id, actor_role=user.role)
            db.commit()
        raise HTTPException(401, "Incorrect email or password")
    user.failed_logins = 0
    user.locked_until = None
    log_event(db, user.id, "auth.login", "user", user.id, actor_role=user.role)
    db.commit()
    return _token(user)


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version = (user.token_version or 0) + 1  # revokes every outstanding token
    log_event(db, user.id, "auth.logout", "user", user.id, actor_role=user.role)
    db.commit()


@router.post("/change-password", status_code=204)
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    validate_password_strength(payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    log_event(db, user.id, "auth.password_changed", "user", user.id, actor_role=user.role)
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


def _profile_out(db: Session, user: User) -> dict:
    prof = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role,
            "phone": prof.phone if prof else None, "date_of_birth": prof.date_of_birth if prof else None}


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _profile_out(db, user)


@router.patch("/profile", response_model=ProfileOut)
def update_profile(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    changed = []
    if payload.full_name is not None and payload.full_name.strip() != user.full_name:
        user.full_name = payload.full_name.strip()
        changed.append("full_name")
    if user.role == "patient" and (payload.phone is not None or payload.date_of_birth is not None):
        prof = db.query(PatientProfile).filter(PatientProfile.user_id == user.id).first()
        if not prof:
            prof = PatientProfile(user_id=user.id)
            db.add(prof)
        if payload.phone is not None:
            prof.phone = payload.phone.strip() or None
            changed.append("phone")
        if payload.date_of_birth is not None:
            prof.date_of_birth = payload.date_of_birth or None
            changed.append("date_of_birth")
    if changed:
        log_event(db, user.id, "auth.profile_updated", "user", user.id, {"fields": changed}, actor_role=user.role)
    db.commit()
    return _profile_out(db, user)
