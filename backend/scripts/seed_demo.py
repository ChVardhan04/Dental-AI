"""Create demo accounts for a non-production environment:  python -m scripts.seed_demo
admin@dentedge.example / AdminPass2026 · dentist@dentedge.example / DentistPass2026 · patient@dentedge.example / PatientPass2026"""
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import bootstrap
from app.models.records import DentistAssignment, PatientProfile
from app.models.user import User

if settings.is_production:
    raise SystemExit("Refusing to seed demo accounts in production")
bootstrap()
with SessionLocal() as db:
    ids = {}
    for role, name, email, pw in [("admin", "Demo Admin", "admin@dentedge.example", "AdminPass2026"),
                                  ("dentist", "Dr Asha Menon", "dentist@dentedge.example", "DentistPass2026"),
                                  ("patient", "Riya Sharma", "patient@dentedge.example", "PatientPass2026")]:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(full_name=name, email=email, password_hash=hash_password(pw), role=role)
            db.add(u)
            db.flush()
            if role == "patient":
                db.add(PatientProfile(user_id=u.id))
        ids[role] = u.id
    if not db.query(DentistAssignment).filter(DentistAssignment.dentist_user_id == ids["dentist"], DentistAssignment.patient_user_id == ids["patient"]).first():
        db.add(DentistAssignment(dentist_user_id=ids["dentist"], patient_user_id=ids["patient"], created_by=ids["admin"]))
    db.commit()
print("Demo accounts ready.")
