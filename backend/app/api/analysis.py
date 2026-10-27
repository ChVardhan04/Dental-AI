"""Vision, X-ray and comparison endpoints."""
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ensure_patient_access, get_current_user, require_consent, resolve_patient
from app.models.records import AIAnalysis, AIFinding, ImageAsset, PatientEducationReport
from app.models.user import User, utcnow
from app.services import insight
from app.services.audit import log_event
from app.services.image_quality import PHOTO_VIEWS, XRAY_TYPES, assess_image
from app.services.orchestrator import finding_out, run_photo_analysis, run_xray_analysis, run_xray_comparison
from app.services.storage import get_storage

router = APIRouter(tags=["AI analysis"])


async def _read_upload(file: UploadFile, max_mb: int) -> bytes:
    max_bytes = max_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    if len(content) > max_bytes:
        raise HTTPException(413, f"File exceeds the {max_mb} MB limit")
    return content


def _image_out(a: ImageAsset, duplicate: bool = False) -> dict:
    q = {k: v for k, v in (a.quality_result or {}).items() if k != "sanitized"}
    return {"id": a.id, "patient_id": a.owner_user_id, "image_kind": a.image_kind, "view": a.view, "filename": a.original_filename,
            "width": a.width, "height": a.height, "quality": q, "duplicate": duplicate, "created_at": a.created_at,
            "has_annotation": bool(a.annotated_storage_key), "url": f"/api/v1/images/{a.id}"}


async def _store_image(db: Session, user: User, patient: User, file: UploadFile, kind: str, view: str | None) -> dict:
    content = await _read_upload(file, settings.max_upload_mb)
    sha = hashlib.sha256(content).hexdigest()
    existing = db.query(ImageAsset).filter(ImageAsset.owner_user_id == patient.id, ImageAsset.sha256 == sha, ImageAsset.image_kind == kind,
                                           ImageAsset.deleted_at.is_(None)).first()
    if existing:
        return _image_out(existing, duplicate=True)
    quality = assess_image(content, file.content_type or "", image_kind="xray" if kind == "xray" else "oral_photo", view=view)
    sanitized = quality.pop("sanitized", None)
    key = f"{patient.id}/{kind}/{uuid.uuid4().hex}.png"
    stored = False
    if sanitized is not None:
        get_storage().put(key, sanitized)  # metadata-free, encrypted at rest
        stored = True
    asset = ImageAsset(owner_user_id=patient.id, uploaded_by=user.id, image_kind=kind, view=view, storage_key=key if stored else "",
                       original_filename=(file.filename or "upload")[:255], content_type="image/png" if stored else (file.content_type or "")[:100],
                       sha256=sha, width=quality.get("width"), height=quality.get("height"), quality_result=quality, encrypted=stored)
    db.add(asset)
    db.flush()
    log_event(db, user.id, "image.uploaded", "image_asset", asset.id, {"kind": kind, "view": view, "quality_status": quality.get("status"),
              "checks": quality.get("checks")}, actor_role=user.role, patient_id=patient.id)
    db.commit()
    return _image_out(asset)


@router.post("/oral-images", status_code=201)
async def upload_oral_image(file: UploadFile = File(...), view: str = Form(default="front_smile"), image_kind: str = Form(default="oral_photo"),
                            patient_id: str | None = Form(default=None), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if image_kind == "xray":  # backwards compatibility with the earlier single upload endpoint
        return await upload_xray(file=file, xray_type=view if view in XRAY_TYPES else "unknown", patient_id=patient_id, user=user, db=db)
    if image_kind not in {"oral_photo", "smile"}:
        raise HTTPException(400, "Unsupported image workflow")
    if view not in PHOTO_VIEWS:
        raise HTTPException(422, f"view must be one of {sorted(PHOTO_VIEWS)}")
    patient = resolve_patient(db, user, patient_id)
    require_consent(db, patient.id)
    return await _store_image(db, user, patient, file, image_kind, view)


@router.post("/xrays", status_code=201)
async def upload_xray(file: UploadFile = File(...), xray_type: str = Form(default="unknown"), patient_id: str | None = Form(default=None),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if xray_type not in XRAY_TYPES:
        raise HTTPException(422, f"xray_type must be one of {sorted(XRAY_TYPES)}")
    patient = resolve_patient(db, user, patient_id)
    require_consent(db, patient.id)
    return await _store_image(db, user, patient, file, "xray", xray_type)


def _get_image(db: Session, user: User, image_id: str) -> ImageAsset:
    asset = db.query(ImageAsset).filter(ImageAsset.id == image_id, ImageAsset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(404, "Image not found")
    ensure_patient_access(db, user, asset.owner_user_id)
    return asset


@router.get("/images")
def list_images(patient_id: str | None = None, kind: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    q = db.query(ImageAsset).filter(ImageAsset.owner_user_id == pid, ImageAsset.deleted_at.is_(None))
    if kind:
        q = q.filter(ImageAsset.image_kind == kind)
    return [_image_out(a) for a in q.order_by(ImageAsset.created_at.desc()).limit(200).all()]


@router.get("/images/{image_id}")
def get_image(image_id: str, variant: str = Query("original", pattern="^(original|annotated)$"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _get_image(db, user, image_id)
    key = asset.annotated_storage_key if variant == "annotated" else asset.storage_key
    if not key:
        raise HTTPException(404, "Image content not available")
    data = get_storage().get(key)
    log_event(db, user.id, "image.viewed", "image_asset", asset.id, {"variant": variant}, actor_role=user.role, patient_id=asset.owner_user_id)
    db.commit()
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"})


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _get_image(db, user, image_id)
    if user.role == "dentist":
        raise HTTPException(403, "Clinical images can only be deleted by the patient or through the retention workflow")
    storage = get_storage()
    for key in (asset.storage_key, asset.annotated_storage_key):
        if key:
            storage.delete(key)
    asset.deleted_at = utcnow()
    asset.storage_key = ""
    asset.annotated_storage_key = None
    log_event(db, user.id, "image.deleted", "image_asset", asset.id, actor_role=user.role, patient_id=asset.owner_user_id)
    db.commit()


# ------------------------------------------------------------------------------------------- analyses
class OralAnalysisRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=8)
    symptoms: str | None = Field(default=None, max_length=1000)


@router.post("/oral-analysis", status_code=201)
def oral_analysis(payload: OralAnalysisRequest | None = None, image_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = payload.image_ids if payload else ([image_id] if image_id else [])
    if not ids:
        raise HTTPException(422, "Provide image_ids")
    assets = [_get_image(db, user, i) for i in dict.fromkeys(ids)]
    if any(a.image_kind not in ("oral_photo", "smile") for a in assets):
        raise HTTPException(422, "Oral analysis accepts oral photographs only. Use /xray-analysis for radiographs.")
    owners = {a.owner_user_id for a in assets}
    if len(owners) != 1:
        raise HTTPException(422, "All images must belong to the same patient")
    patient = db.get(User, owners.pop())
    require_consent(db, patient.id)
    context = {"symptoms": payload.symptoms} if payload and payload.symptoms else None
    analysis = run_photo_analysis(db, patient, user, assets, context)
    insight.build_profile(db, patient)
    db.commit()
    return analysis_out(db, analysis, user)


class XrayAnalysisRequest(BaseModel):
    image_id: str
    xray_type: str | None = None


@router.post("/xray-analysis", status_code=201)
def xray_analysis(payload: XrayAnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _get_image(db, user, payload.image_id)
    if asset.image_kind != "xray":
        raise HTTPException(422, "This image was not uploaded as an X-ray")
    patient = db.get(User, asset.owner_user_id)
    require_consent(db, patient.id)
    analysis = run_xray_analysis(db, patient, user, asset, payload.xray_type or asset.view)
    insight.build_profile(db, patient)
    db.commit()
    return analysis_out(db, analysis, user)


class ComparisonRequest(BaseModel):
    previous_image_id: str
    current_image_id: str


@router.post("/xray-comparison", status_code=201)
def xray_comparison(payload: ComparisonRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prev = _get_image(db, user, payload.previous_image_id)
    curr = _get_image(db, user, payload.current_image_id)
    if prev.id == curr.id:
        raise HTTPException(422, "Choose two different X-rays")
    if prev.owner_user_id != curr.owner_user_id or prev.image_kind != "xray" or curr.image_kind != "xray":
        raise HTTPException(422, "Both images must be X-rays of the same patient")
    patient = db.get(User, curr.owner_user_id)
    require_consent(db, patient.id)
    analysis = run_xray_comparison(db, patient, user, prev, curr)
    db.commit()
    return analysis_out(db, analysis, user)


def _get_analysis(db: Session, user: User, analysis_id: str) -> AIAnalysis:
    a = db.get(AIAnalysis, analysis_id)
    if not a:
        raise HTTPException(404, "Analysis not found")
    ensure_patient_access(db, user, a.user_id)
    return a


def analysis_out(db: Session, a: AIAnalysis, viewer: User) -> dict:
    findings = db.query(AIFinding).filter(AIFinding.analysis_id == a.id).order_by(AIFinding.confidence.desc()).all()
    if viewer.role == "patient":
        findings = [f for f in findings if f.review_status != "reject"]
    result = dict(a.result_json or {})
    result.pop("annotated", None)
    return {"id": a.id, "patient_id": a.user_id, "image_asset_id": a.image_asset_id, "module": a.module, "status": a.status, "summary": a.summary, "urgency": a.urgency,
            "model_name": a.model_name, "model_version": a.model_version, "rules_version": a.rules_version, "prompt_version": a.prompt_version,
            "created_at": a.created_at, "findings": [finding_out(f) for f in findings], "result": result,
            "annotated_images": [{"image_id": k, "url": f"/api/v1/analyses/{a.id}/annotated/{k}"} for k in (a.result_json or {}).get("annotated", {})],
            "appointment_booking_url": settings.appointment_booking_url}


@router.get("/analyses")
def list_analyses(patient_id: str | None = None, module: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    q = db.query(AIAnalysis).filter(AIAnalysis.user_id == pid)
    if module:
        q = q.filter(AIAnalysis.module == module)
    items = q.order_by(AIAnalysis.created_at.desc()).limit(200).all()
    counts = {}
    for f in db.query(AIFinding).filter(AIFinding.analysis_id.in_([x.id for x in items])).all() if items else []:
        c = counts.setdefault(f.analysis_id, {"findings": 0, "pending": 0})
        c["findings"] += 1
        c["pending"] += f.review_status in ("pending", "uncertain")
    return [{"id": x.id, "module": x.module, "status": x.status, "summary": x.summary, "urgency": x.urgency, "created_at": x.created_at,
             "model_name": x.model_name, "model_version": x.model_version, "finding_count": counts.get(x.id, {}).get("findings", 0),
             "pending_review": counts.get(x.id, {}).get("pending", 0)} for x in items]


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _get_analysis(db, user, analysis_id)
    log_event(db, user.id, "analysis.viewed", "ai_analysis", a.id, actor_role=user.role, patient_id=a.user_id)
    db.commit()
    return analysis_out(db, a, user)


@router.get("/analyses/{analysis_id}/annotated/{image_id}")
def annotated_image(analysis_id: str, image_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _get_analysis(db, user, analysis_id)
    key = (a.result_json or {}).get("annotated", {}).get(image_id)
    if not key:
        raise HTTPException(404, "No annotation for this image")
    return Response(get_storage().get(key), media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/analyses/{analysis_id}/report")
def analysis_report(analysis_id: str, report_type: str = Query("patient", pattern="^(patient|dentist)$"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _get_analysis(db, user, analysis_id)
    patient = db.get(User, a.user_id)
    if report_type == "dentist":
        if user.role != "dentist":
            raise HTTPException(403, "Dentist reports are available to the assigned dentist only")
        content = insight.dentist_report(db, patient, a)
    else:
        content = insight.patient_report(db, patient, a)
    db.add(PatientEducationReport(patient_user_id=patient.id, created_by=user.id, analysis_id=a.id, report_type=report_type,
                                  content=insight._jsonable(content), llm_provider=(a.result_json or {}).get("explanation_provider", ""),
                                  prompt_version=a.prompt_version, safety=(a.result_json or {}).get("safety", {})))
    log_event(db, user.id, f"report.{report_type}.generated", "ai_analysis", a.id, actor_role=user.role, patient_id=patient.id)
    db.commit()
    return content


@router.post("/education/report", status_code=201)
def education_report(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analysis_id = str(payload.get("analysis_id", ""))
    a = _get_analysis(db, user, analysis_id)
    content = insight.education_report(db, a)
    row = PatientEducationReport(patient_user_id=a.user_id, created_by=user.id, analysis_id=a.id, report_type="education",
                                 content=insight._jsonable(content), prompt_version=a.prompt_version, safety=(a.result_json or {}).get("safety", {}))
    db.add(row)
    db.flush()
    log_event(db, user.id, "education.report.generated", "education_report", row.id, actor_role=user.role, patient_id=a.user_id)
    db.commit()
    return {"id": row.id, **content}


@router.get("/education/reports")
def list_education_reports(patient_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    rows = db.query(PatientEducationReport).filter(PatientEducationReport.patient_user_id == pid).order_by(PatientEducationReport.created_at.desc()).limit(100).all()
    if user.role == "patient":
        rows = [r for r in rows if r.report_type != "dentist"]
    return [{"id": r.id, "analysis_id": r.analysis_id, "report_type": r.report_type, "created_at": r.created_at, "content": r.content} for r in rows]

