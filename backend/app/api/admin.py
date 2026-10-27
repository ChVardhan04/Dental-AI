"""Administration: users, dentist assignments, model registry, knowledge base, audit, monitoring.
Administrators manage the system without access to clinical content."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.middleware import metrics
from app.core.security import hash_password, require_roles, validate_password_strength
from app.models.records import AIModel, AIModelVersion, AuditLog, DentistAssignment, ImageAsset, KnowledgeDocument, KnowledgeVersion, PatientProfile
from app.models.user import User, utcnow
from app.services import monitoring
from app.services.audit import log_event
from app.services.model_registry import APPROVAL_STATUSES, DEPLOYMENT_STATUSES
from app.services.storage import get_storage

router = APIRouter(prefix="/admin", tags=["Administration"])
admin_only = require_roles("admin")


def _user_out(u: User) -> dict:
    return {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "is_active": u.is_active, "created_at": u.created_at, "deleted": bool(u.deleted_at)}


@router.get("/users")
def users(role: str | None = None, q: str | None = None, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    query = db.query(User).filter(User.deleted_at.is_(None))
    if role:
        query = query.filter(User.role == role)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter((User.email.ilike(like)) | (User.full_name.ilike(like)))
    return [_user_out(u) for u in query.order_by(User.created_at.desc()).limit(500).all()]


class StaffPayload(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(pattern="^(dentist|admin|patient)$")


@router.post("/users", status_code=201)
def create_user(payload: StaffPayload, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    validate_password_strength(payload.password)
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(409, "Email already registered")
    u = User(full_name=payload.full_name, email=payload.email.lower(), password_hash=hash_password(payload.password), role=payload.role)
    db.add(u)
    db.flush()
    if u.role == "patient":
        db.add(PatientProfile(user_id=u.id))
    log_event(db, admin.id, "admin.user_created", "user", u.id, {"role": u.role}, actor_role="admin")
    db.commit()
    return _user_out(u)


class UserUpdate(BaseModel):
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UserUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and payload.is_active is False:
        raise HTTPException(400, "You cannot deactivate your own account")
    if payload.is_active is not None:
        u.is_active = payload.is_active
        u.token_version = (u.token_version or 0) + 1
    log_event(db, admin.id, "admin.user_updated", "user", u.id, payload.model_dump(exclude_none=True), actor_role="admin")
    db.commit()
    return _user_out(u)


class AssignmentPayload(BaseModel):
    dentist_id: str
    patient_id: str


@router.get("/assignments")
def assignments(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.query(DentistAssignment).filter(DentistAssignment.active.is_(True)).all()
    names = {u.id: u.full_name for u in db.query(User).filter(User.id.in_({r.dentist_user_id for r in rows} | {r.patient_user_id for r in rows})).all()} if rows else {}
    return [{"id": r.id, "dentist_id": r.dentist_user_id, "dentist_name": names.get(r.dentist_user_id), "patient_id": r.patient_user_id,
             "patient_name": names.get(r.patient_user_id), "created_at": r.created_at} for r in rows]


@router.post("/assignments", status_code=201)
def assign(payload: AssignmentPayload, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    d = db.query(User).filter(User.id == payload.dentist_id, User.role == "dentist", User.deleted_at.is_(None)).first()
    p = db.query(User).filter(User.id == payload.patient_id, User.role == "patient", User.deleted_at.is_(None)).first()
    if not d or not p:
        raise HTTPException(404, "Dentist or patient not found")
    row = db.query(DentistAssignment).filter(DentistAssignment.dentist_user_id == d.id, DentistAssignment.patient_user_id == p.id).first()
    if row:
        row.active = True
    else:
        row = DentistAssignment(dentist_user_id=d.id, patient_user_id=p.id, created_by=admin.id)
        db.add(row)
    db.flush()
    log_event(db, admin.id, "admin.assignment_created", "dentist_assignment", row.id, {"dentist": d.id}, actor_role="admin", patient_id=p.id)
    db.commit()
    return {"id": row.id, "dentist_id": d.id, "patient_id": p.id}


@router.delete("/assignments/{assignment_id}", status_code=204)
def unassign(assignment_id: str, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    row = db.get(DentistAssignment, assignment_id)
    if not row:
        raise HTTPException(404, "Assignment not found")
    row.active = False
    log_event(db, admin.id, "admin.assignment_removed", "dentist_assignment", row.id, actor_role="admin", patient_id=row.patient_user_id)
    db.commit()


# ------------------------------------------------------------------------------------------- model registry
@router.get("/models")
def models(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    out = []
    for m in db.query(AIModel).order_by(AIModel.name).all():
        versions = db.query(AIModelVersion).filter(AIModelVersion.model_id == m.id).order_by(AIModelVersion.created_at.desc()).all()
        out.append({"id": m.id, "name": m.name, "task": m.task, "modality": m.modality, "description": m.description,
                    "versions": [{"id": v.id, "version": v.version, "training_dataset": v.training_dataset, "validation_dataset": v.validation_dataset,
                                  "metrics": v.metrics, "deployment_status": v.deployment_status, "approval_status": v.approval_status,
                                  "approved_by": v.approved_by, "notes": v.notes, "created_at": v.created_at} for v in versions]})
    return {"models": out, "allowed_statuses": sorted(settings.model_statuses), "deployment_statuses": DEPLOYMENT_STATUSES, "approval_statuses": APPROVAL_STATUSES}


class VersionUpdate(BaseModel):
    deployment_status: str | None = None
    approval_status: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/models/versions/{version_id}")
def update_version(version_id: str, payload: VersionUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    v = db.get(AIModelVersion, version_id)
    if not v:
        raise HTTPException(404, "Model version not found")
    if payload.deployment_status and payload.deployment_status not in DEPLOYMENT_STATUSES:
        raise HTTPException(422, "Invalid deployment status")
    if payload.approval_status and payload.approval_status not in APPROVAL_STATUSES:
        raise HTTPException(422, "Invalid approval status")
    # Model change control: production requires prior approval with validation evidence.
    target_status = payload.deployment_status or v.deployment_status
    target_approval = payload.approval_status or v.approval_status
    if target_status == "production" and target_approval != "approved":
        raise HTTPException(409, "A model version must be approved before it can be deployed to production")
    if target_status == "production" and not v.validation_dataset or (target_status == "production" and "not clinically validated" in v.validation_dataset.lower()):
        raise HTTPException(409, "Production deployment requires a documented clinical validation dataset")
    before = {"deployment_status": v.deployment_status, "approval_status": v.approval_status}
    if payload.deployment_status:
        v.deployment_status = payload.deployment_status
    if payload.approval_status:
        v.approval_status = payload.approval_status
        v.approved_by = admin.id if payload.approval_status == "approved" else v.approved_by
    if payload.notes is not None:
        v.notes = payload.notes
    model = db.get(AIModel, v.model_id)
    log_event(db, admin.id, "model.version_updated", "ai_model_version", v.id, {"before": before, "after": payload.model_dump(exclude_none=True)},
              actor_role="admin", model_name=model.name if model else None, model_version=v.version)
    db.commit()
    return {"id": v.id, "deployment_status": v.deployment_status, "approval_status": v.approval_status}


class VersionCreate(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    training_dataset: str = Field(min_length=1, max_length=200)
    validation_dataset: str = Field(min_length=1, max_length=200)
    metrics: dict = Field(default_factory=dict)
    notes: str = ""


@router.post("/models/{model_id}/versions", status_code=201)
def register_version(model_id: str, payload: VersionCreate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    m = db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    if db.query(AIModelVersion).filter(AIModelVersion.model_id == m.id, AIModelVersion.version == payload.version).first():
        raise HTTPException(409, "Version already registered")
    v = AIModelVersion(model_id=m.id, version=payload.version, training_dataset=payload.training_dataset, validation_dataset=payload.validation_dataset,
                       metrics=payload.metrics, notes=payload.notes, deployment_status="disabled", approval_status="pending")
    db.add(v)
    db.flush()
    log_event(db, admin.id, "model.version_registered", "ai_model_version", v.id, actor_role="admin", model_name=m.name, model_version=v.version)
    db.commit()
    return {"id": v.id, "version": v.version, "deployment_status": v.deployment_status}


# ------------------------------------------------------------------------------------------- knowledge base
@router.get("/knowledge")
def knowledge(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    out = []
    for d in db.query(KnowledgeDocument).order_by(KnowledgeDocument.title).all():
        vs = db.query(KnowledgeVersion).filter(KnowledgeVersion.document_id == d.id).order_by(KnowledgeVersion.created_at.desc()).all()
        out.append({"id": d.id, "slug": d.slug, "title": d.title, "topics": d.topics,
                    "versions": [{"id": v.id, "version": v.version, "status": v.status, "source": v.source, "publication_date": v.publication_date,
                                  "review_date": v.review_date, "reviewer": v.reviewer, "content": v.content, "created_at": v.created_at} for v in vs]})
    return out


class KnowledgeVersionPayload(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{3,120}$")
    title: str = Field(min_length=3, max_length=200)
    topics: list[str] = Field(min_length=1)
    version: str = Field(min_length=1, max_length=20)
    content: dict
    source: str = Field(min_length=3, max_length=300)
    publication_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    review_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reviewer: str = Field(min_length=3, max_length=160)


@router.post("/knowledge", status_code=201)
def add_knowledge(payload: KnowledgeVersionPayload, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    from app.services.safety import check_text
    text_blob = " ".join(str(v) if not isinstance(v, list) else " ".join(map(str, v)) for v in payload.content.values())
    issues = [v for v in check_text(text_blob, text_blob) if v["type"] in ("unsupported_medication_advice", "dangerous_instruction", "excessive_certainty")]
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.slug == payload.slug).first()
    if not doc:
        doc = KnowledgeDocument(slug=payload.slug, title=payload.title, topics=payload.topics)
        db.add(doc)
        db.flush()
    else:
        doc.title, doc.topics = payload.title, payload.topics
    if db.query(KnowledgeVersion).filter(KnowledgeVersion.document_id == doc.id, KnowledgeVersion.version == payload.version).first():
        raise HTTPException(409, "This version already exists")
    v = KnowledgeVersion(document_id=doc.id, version=payload.version, content=payload.content, source=payload.source, publication_date=payload.publication_date,
                         review_date=payload.review_date, reviewer=payload.reviewer, status="draft")
    db.add(v)
    db.flush()
    log_event(db, admin.id, "knowledge.version_created", "knowledge_version", v.id, {"slug": doc.slug, "safety_flags": issues}, actor_role="admin")
    db.commit()
    return {"id": v.id, "document_id": doc.id, "status": v.status, "safety_flags": issues}


@router.patch("/knowledge/versions/{version_id}")
def set_knowledge_status(version_id: str, status: str = Query(pattern="^(draft|approved|retired)$"), admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    v = db.get(KnowledgeVersion, version_id)
    if not v:
        raise HTTPException(404, "Knowledge version not found")
    if status == "approved":  # only one approved version per document
        for other in db.query(KnowledgeVersion).filter(KnowledgeVersion.document_id == v.document_id, KnowledgeVersion.status == "approved").all():
            other.status = "retired"
    v.status = status
    log_event(db, admin.id, "knowledge.status_changed", "knowledge_version", v.id, {"status": status}, actor_role="admin")
    db.commit()
    return {"id": v.id, "status": v.status}


# ------------------------------------------------------------------------------------------- audit & monitoring
@router.get("/audit-logs")
def audit_logs(action: str | None = None, actor_id: str | None = None, patient_id: str | None = None, limit: int = Query(200, le=1000),
               admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if actor_id:
        q = q.filter(AuditLog.actor_user_id == actor_id)
    if patient_id:
        q = q.filter(AuditLog.patient_user_id == patient_id)
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"id": r.id, "created_at": r.created_at, "actor_user_id": r.actor_user_id, "actor_role": r.actor_role, "action": r.action,
             "resource_type": r.resource_type, "resource_id": r.resource_id, "patient_user_id": r.patient_user_id, "model": r.model_name,
             "model_version": r.model_version, "confidence": r.confidence, "decision": r.decision, "details": r.details, "request_id": r.request_id,
             "ip_address": r.ip_address} for r in rows]


@router.get("/monitoring")
def monitoring_view(days: int = Query(30, ge=1, le=365), admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    tech = metrics.snapshot()
    tech.update(database="ok" if db_ok else "error", storage="ok" if get_storage().healthy() else "error",
                images_stored=db.query(ImageAsset).filter(ImageAsset.deleted_at.is_(None)).count())
    try:
        import resource
        tech["process_max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        pass
    return {"technical": tech, "ai": monitoring.ai_metrics(db, days), "drift": monitoring.drift_report(db, days),
            "configuration": {"environment": settings.app_env, "llm_provider": settings.llm_provider, "vision_provider": settings.vision_provider,
                              "speech_provider": settings.speech_provider, "storage_backend": settings.storage_backend,
                              "allowed_model_statuses": sorted(settings.model_statuses), "confidence_threshold": settings.confidence_threshold}}


@router.post("/retention/purge")
def retention_purge(dry_run: bool = True, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Data retention policy: remove stored binaries older than DATA_RETENTION_DAYS (records are kept de-identified)."""
    cutoff = (utcnow() - timedelta(days=settings.data_retention_days)).replace(tzinfo=None)
    old = db.query(ImageAsset).filter(ImageAsset.created_at < cutoff, ImageAsset.deleted_at.is_(None)).all()
    if not dry_run:
        storage = get_storage()
        for a in old:
            for k in (a.storage_key, a.annotated_storage_key):
                if k:
                    storage.delete(k)
            a.storage_key, a.annotated_storage_key, a.deleted_at = "", None, utcnow()
    log_event(db, admin.id, "retention.purge", "image_asset", None, {"dry_run": dry_run, "count": len(old), "retention_days": settings.data_retention_days}, actor_role="admin")
    db.commit()
    return {"dry_run": dry_run, "eligible": len(old), "retention_days": settings.data_retention_days}
