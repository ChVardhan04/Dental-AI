"""Smile, consent, patient intelligence, appointments and privacy workflows."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    CONSENT_VERSION, REQUIRED_PATIENT_CONSENTS, ensure_patient_access, get_current_user, missing_consents, require_consent,
)
from app.core.database import get_db
from app.models.records import (
    AIAnalysis, AIFinding, Appointment, ClinicalFinding, Consent, DeletionRequest, DentistAssignment, ImageAsset, PatientEducationReport,
    PatientProfile, PerioChart, SmileAnalysis, TimelineEvent, VoiceSession,
)
from app.models.user import User, utcnow
from app.services import insight
from app.services.audit import log_event
from app.services.image_utils import load_rgb
from app.services.model_registry import get_active
from app.services.smile import DISCLAIMER, analyze_smile, compare_scores
from app.services.storage import get_storage
from app.services.timeline import add_event

router = APIRouter(tags=["Patient workflows"])

CONSENT_TEXT = {
    "ai_analysis": "I agree that DentEdge AI may analyse my images, X-rays, voice and text with AI models to produce observations for me and my dentist. AI results are not a diagnosis.",
    "data_processing": "I agree that my images and audio may be processed and stored securely (encrypted) for this purpose, and reviewed by my assigned dentist.",
    "privacy_notice": "I have read the privacy notice, including how long data is kept and how I can export or delete it.",
}


# ------------------------------------------------------------------------------------------- consent
@router.get("/consents/status")
def consent_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "patient":
        return {"required": [], "missing": [], "version": CONSENT_VERSION, "texts": CONSENT_TEXT}
    return {"required": sorted(REQUIRED_PATIENT_CONSENTS), "missing": missing_consents(db, user.id), "version": CONSENT_VERSION, "texts": CONSENT_TEXT}


class ConsentPayload(BaseModel):
    consent_type: str = Field(min_length=3, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    accepted: bool


class ConsentBatch(BaseModel):
    consents: list[ConsentPayload] = Field(min_length=1, max_length=10)


@router.post("/consents", status_code=201)
def save_consents(payload: ConsentBatch | ConsentPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = payload.consents if isinstance(payload, ConsentBatch) else [payload]
    out = []
    for c in items:
        if c.consent_type not in CONSENT_TEXT:
            raise HTTPException(422, f"Unknown consent type '{c.consent_type}'")
        row = Consent(user_id=user.id, consent_type=c.consent_type, version=c.version, accepted=c.accepted)
        db.add(row)
        db.flush()
        log_event(db, user.id, "consent.recorded", "consent", row.id, {"type": c.consent_type, "version": c.version, "accepted": c.accepted},
                  actor_role=user.role, patient_id=user.id)
        out.append({"id": row.id, "consent_type": row.consent_type, "version": row.version, "accepted": row.accepted})
    db.commit()
    return {"consents": out, "missing": missing_consents(db, user.id)} if isinstance(payload, ConsentBatch) else out[0]


@router.get("/consents")
def consent_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Consent).filter(Consent.user_id == user.id).order_by(Consent.created_at.desc()).all()
    return [{"id": r.id, "consent_type": r.consent_type, "version": r.version, "accepted": r.accepted, "created_at": r.created_at} for r in rows]


# ------------------------------------------------------------------------------------------- smile
class SmilePayload(BaseModel):
    image_id: str | None = None
    metrics: dict | None = None  # legacy field, ignored


@router.post("/smile-analysis", status_code=201)
def smile_analysis(payload: SmilePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.image_id:
        raise HTTPException(422, "Upload a smile photo first and provide image_id")
    asset = db.get(ImageAsset, payload.image_id)
    if not asset or asset.deleted_at:
        raise HTTPException(404, "Image not found")
    ensure_patient_access(db, user, asset.owner_user_id)
    require_consent(db, asset.owner_user_id)
    model = get_active(db, "smile-cosmetic-analyzer")
    if not (asset.quality_result or {}).get("accepted"):
        result = {"status": "not_scored", "reason": (asset.quality_result or {}).get("reason", "Image quality check failed"), "metrics": {}, "overall": None}
    elif not model:
        result = {"status": "not_scored", "reason": "The cosmetic analysis model is not enabled.", "metrics": {}, "overall": None}
    else:
        result = analyze_smile(load_rgb(get_storage().get(asset.storage_key)))
    previous = db.query(SmileAnalysis).filter(SmileAnalysis.user_id == asset.owner_user_id, SmileAnalysis.status == "scored").order_by(SmileAnalysis.created_at.desc()).first()
    progress = compare_scores(previous.metrics if previous else None, result) if result["status"] == "scored" else None
    result["progress"] = progress
    result.setdefault("disclaimer", DISCLAIMER)
    row = SmileAnalysis(user_id=asset.owner_user_id, image_asset_id=asset.id, metrics=result, overall_score=result.get("overall"),
                        model_version=model.version if model else "", status=result["status"])
    db.add(row)
    db.flush()
    if result["status"] == "scored":
        add_event(db, asset.owner_user_id, "smile_analysis", f"Smile Score {result['overall']}/100", "Cosmetic visual assessment",
                  ref_type="smile_analysis", ref_id=row.id, created_by=user.id)
    log_event(db, user.id, "smile.analysis.created", "smile_analysis", row.id, {"status": result["status"], "overall": result.get("overall")},
              actor_role=user.role, patient_id=asset.owner_user_id, model_name="smile-cosmetic-analyzer", model_version=row.model_version)
    insight.build_profile(db, db.get(User, asset.owner_user_id))
    db.commit()
    return {"id": row.id, "image_id": asset.id, "created_at": row.created_at, **result}


@router.get("/smile-analysis")
def smile_history(patient_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    rows = db.query(SmileAnalysis).filter(SmileAnalysis.user_id == pid).order_by(SmileAnalysis.created_at.desc()).limit(50).all()
    return [{"id": r.id, "image_id": r.image_asset_id, "created_at": r.created_at, "overall": r.overall_score, "status": r.status, **(r.metrics or {})} for r in rows]


# ------------------------------------------------------------------------------------------- patients, timeline, profile
@router.get("/patients")
def my_patients(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "dentist":
        raise HTTPException(403, "Only dentists have patient lists")
    links = db.query(DentistAssignment).filter(DentistAssignment.dentist_user_id == user.id, DentistAssignment.active.is_(True)).all()
    out = []
    for link in links:
        p = db.get(User, link.patient_user_id)
        if not p or p.deleted_at:
            continue
        pending = db.query(AIFinding).filter(AIFinding.patient_user_id == p.id, AIFinding.review_status.in_(["pending", "uncertain"])).count()
        last = db.query(AIAnalysis).filter(AIAnalysis.user_id == p.id).order_by(AIAnalysis.created_at.desc()).first()
        urgent = db.query(VoiceSession).filter(VoiceSession.user_id == p.id, VoiceSession.emergency.is_(True)).count()
        out.append({"id": p.id, "full_name": p.full_name, "email": p.email, "pending_review": pending, "last_activity": last.created_at if last else None,
                    "emergency_flags": urgent, "consent_complete": not missing_consents(db, p.id)})
    return sorted(out, key=lambda x: (-x["emergency_flags"], -x["pending_review"], x["full_name"]))


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_patient_access(db, user, patient_id)
    events = insight.timeline(db, patient_id)
    years: dict[int, list] = {}
    for e in events:
        years.setdefault(e["year"], []).append(e)
    return {"patient_id": patient_id, "events": events, "by_year": [{"year": y, "events": v} for y, v in sorted(years.items(), reverse=True)]}


@router.get("/patients/{patient_id}/oral-profile")
def oral_profile(patient_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = ensure_patient_access(db, user, patient_id)
    profile = insight.build_profile(db, patient)
    log_event(db, user.id, "profile.viewed", "oral_health_profile", patient_id, actor_role=user.role, patient_id=patient_id)
    db.commit()
    return profile


# ------------------------------------------------------------------------------------------- appointments
class AppointmentPayload(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)
    preferred_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_type: str | None = Field(default=None, max_length=40)
    source_id: str | None = Field(default=None, max_length=36)
    urgency: str = Field(default="routine", pattern="^(routine|soon|urgent)$")


@router.post("/appointments", status_code=201)
def request_appointment(payload: AppointmentPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "patient":
        raise HTTPException(403, "Appointments are requested by patients")
    link = db.query(DentistAssignment).filter(DentistAssignment.patient_user_id == user.id, DentistAssignment.active.is_(True)).first()
    appt = Appointment(patient_user_id=user.id, dentist_user_id=link.dentist_user_id if link else None, preferred_date=payload.preferred_date,
                       reason=payload.reason, urgency=payload.urgency, source_type=payload.source_type, source_id=payload.source_id)
    db.add(appt)
    db.flush()
    log_event(db, user.id, "appointment.requested", "appointment", appt.id, {"urgency": payload.urgency}, actor_role=user.role, patient_id=user.id)
    db.commit()
    return {"id": appt.id, "status": appt.status, "booking_url": settings.appointment_booking_url,
            "message": "Your request has been recorded. Complete the booking on DentEdge to choose a time."}


@router.get("/appointments")
def list_appointments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Appointment)
    if user.role == "patient":
        q = q.filter(Appointment.patient_user_id == user.id)
    elif user.role == "dentist":
        ids = [a.patient_user_id for a in db.query(DentistAssignment).filter(DentistAssignment.dentist_user_id == user.id, DentistAssignment.active.is_(True)).all()]
        q = q.filter(Appointment.patient_user_id.in_(ids or [""]))
    else:
        raise HTTPException(403, "Not permitted")
    return [{"id": a.id, "patient_id": a.patient_user_id, "reason": a.reason, "preferred_date": a.preferred_date, "urgency": a.urgency,
             "status": a.status, "created_at": a.created_at} for a in q.order_by(Appointment.created_at.desc()).limit(100).all()]


# ------------------------------------------------------------------------------------------- privacy
@router.get("/me/export")
def export_my_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "patient":
        raise HTTPException(403, "Data export is available for patient accounts")

    def rows(model, col):
        return [{c.name: getattr(r, c.name) for c in model.__table__.columns if c.name not in ("password_hash", "storage_key", "annotated_storage_key", "audio_storage_key")}
                for r in db.query(model).filter(col == user.id).all()]
    data = {
        "account": {"id": user.id, "full_name": user.full_name, "email": user.email, "created_at": user.created_at},
        "profile": rows(PatientProfile, PatientProfile.user_id), "consents": rows(Consent, Consent.user_id),
        "images": rows(ImageAsset, ImageAsset.owner_user_id), "analyses": rows(AIAnalysis, AIAnalysis.user_id),
        "findings": rows(AIFinding, AIFinding.patient_user_id), "clinical_findings": rows(ClinicalFinding, ClinicalFinding.patient_user_id),
        "voice_sessions": rows(VoiceSession, VoiceSession.user_id), "perio_charts": rows(PerioChart, PerioChart.patient_user_id),
        "smile_analyses": rows(SmileAnalysis, SmileAnalysis.user_id), "reports": rows(PatientEducationReport, PatientEducationReport.patient_user_id),
        "timeline": rows(TimelineEvent, TimelineEvent.patient_user_id), "appointments": rows(Appointment, Appointment.patient_user_id),
    }
    log_event(db, user.id, "privacy.data_exported", "user", user.id, actor_role=user.role, patient_id=user.id)
    db.commit()
    return insight._jsonable(data)


class DeletePayload(BaseModel):
    confirm: str = Field(pattern="^DELETE$")
    password: str


@router.post("/me/delete")
def delete_my_account(payload: DeletePayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.core.security import verify_password
    if user.role != "patient":
        raise HTTPException(403, "Staff accounts are deactivated by an administrator")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(400, "Password is incorrect")
    summary = purge_patient(db, user)
    db.commit()
    return {"status": "deleted", **summary}


def purge_patient(db: Session, user: User) -> dict:
    """Deletion workflow: removes stored binaries, de-identifies records, revokes sessions. Audit log is retained."""
    storage = get_storage()
    files = 0
    for a in db.query(ImageAsset).filter(ImageAsset.owner_user_id == user.id).all():
        for k in (a.storage_key, a.annotated_storage_key):
            if k:
                storage.delete(k)
                files += 1
        a.storage_key, a.annotated_storage_key, a.original_filename, a.deleted_at = "", None, "deleted", utcnow()
    for v in db.query(VoiceSession).filter(VoiceSession.user_id == user.id).all():
        if v.audio_storage_key:
            storage.delete(v.audio_storage_key)
            files += 1
        v.transcript, v.structured_data, v.audio_storage_key = "", {"deleted": True}, None
    for model, col in ((AIAnalysis, AIAnalysis.user_id),):
        for r in db.query(model).filter(col == user.id).all():
            r.summary, r.result_json = "", {"deleted": True}
    db.query(TimelineEvent).filter(TimelineEvent.patient_user_id == user.id).delete()
    db.query(PatientEducationReport).filter(PatientEducationReport.patient_user_id == user.id).delete()
    db.query(PatientProfile).filter(PatientProfile.user_id == user.id).delete()
    db.query(DentistAssignment).filter(DentistAssignment.patient_user_id == user.id).update({"active": False})
    user.full_name, user.email = "Deleted user", f"deleted-{user.id}@invalid.local"
    user.is_active, user.deleted_at = False, utcnow()
    user.token_version = (user.token_version or 0) + 1
    db.add(DeletionRequest(user_id=user.id, status="completed", details={"files_removed": files}))
    log_event(db, user.id, "privacy.account_deleted", "user", user.id, {"files_removed": files}, actor_role="patient", patient_id=user.id)
    return {"files_removed": files}
