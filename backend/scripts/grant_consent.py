"""DEV/DEMO ONLY - records the required AI consents for patient accounts so uploads are not blocked.

Put this file in backend/scripts/ and run from the backend folder:
    python -m scripts.grant_consent                 # all patients
    python -m scripts.grant_consent you@email.com   # one patient
"""
import sys

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import CONSENT_VERSION, REQUIRED_PATIENT_CONSENTS, missing_consents
from app.main import bootstrap
from app.models.records import Consent
from app.models.user import User

if settings.is_production:
    raise SystemExit("Refusing to run in production")

bootstrap()
with SessionLocal() as db:
    q = db.query(User).filter(User.role == "patient", User.deleted_at.is_(None))
    if len(sys.argv) > 1:
        q = q.filter(User.email == sys.argv[1].strip().lower())
    users = q.all()
    if not users:
        raise SystemExit("No matching patient accounts found")
    for u in users:
        for t in missing_consents(db, u.id):
            db.add(Consent(user_id=u.id, consent_type=t, version=CONSENT_VERSION, accepted=True))
        db.commit()
        print(f"Consent recorded for {u.email} -> still missing: {missing_consents(db, u.id) or 'nothing'}")
