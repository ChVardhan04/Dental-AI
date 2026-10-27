"""Dentist review — human-in-the-loop. AI findings never become clinical findings automatically."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ensure_patient_access, require_roles
from app.models.records import AIAnalysis, AIFinding, ClinicalFinding, ClinicalReview, DentistAssignment
from app.models.user import User, utcnow
from app.services import insight
from app.services.audit import log_event
from app.services.orchestrator import finding_out
from app.services.taxonomy import ALL_FINDINGS, label_for
from app.services.timeline import add_event

router = APIRouter(tags=["Clinical review"])
DECISIONS = "confirm|edit|reject|uncertain|further_evaluation"


class ReviewPayload(BaseModel):
    finding_id: str | None = None
    decision: str = Field(pattern=f"^({DECISIONS})$")
    note: str | None = Field(default=None, max_length=3000)
    edited_finding: dict | None = None  # {finding_type?, location?{tooth, region}, severity?, label?}


@router.get("/clinical-review/queue")
def review_queue(status: str = "open", patient_id: str | None = None, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    patient_ids = [a.patient_user_id for a in db.query(DentistAssignment).filter(DentistAssignment.dentist_user_id == user.id, DentistAssignment.active.is_(True)).all()]
    if patient_id:
        ensure_patient_access(db, user, patient_id)
        patient_ids = [patient_id]
    if not patient_ids:
        return {"items": [], "counts": {"open": 0}}
    q = db.query(AIFinding).filter(AIFinding.patient_user_id.in_(patient_ids))
    if status == "open":
        q = q.filter(AIFinding.review_status.in_(["pending", "uncertain"]))
    elif status != "all":
        q = q.filter(AIFinding.review_status == status)
    findings = q.order_by(AIFinding.created_at.desc()).limit(300).all()
    names = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(patient_ids)).all()}
    analyses = {a.id: a for a in db.query(AIAnalysis).filter(AIAnalysis.id.in_({f.analysis_id for f in findings})).all()} if findings else {}
    items = []
    for f in findings:
        a = analyses.get(f.analysis_id)
        items.append({**finding_out(f), "patient_id": f.patient_user_id, "patient_name": names.get(f.patient_user_id), "module": a.module if a else None,
                      "urgency": a.urgency if a else None,
                      "annotated_url": f"/api/v1/analyses/{f.analysis_id}/annotated/{f.image_asset_id}" if a and f.image_asset_id in (a.result_json or {}).get("annotated", {}) else None,
                      "image_url": f"/api/v1/images/{f.image_asset_id}" if f.image_asset_id else None})
    open_count = db.query(AIFinding).filter(AIFinding.patient_user_id.in_(patient_ids), AIFinding.review_status.in_(["pending", "uncertain"])).count()
    return {"items": items, "counts": {"open": open_count}}


@router.post("/clinical-review")
def review(payload: ReviewPayload, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    if not payload.finding_id:
        raise HTTPException(422, "finding_id is required")
    return _review(payload.finding_id, payload, user, db)


@router.post("/clinical-review/{finding_id}")
def review_by_path(finding_id: str, payload: ReviewPayload, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    return _review(finding_id, payload, user, db)


def _review(finding_id: str, payload: ReviewPayload, user: User, db: Session) -> dict:
    finding = db.query(AIFinding).filter((AIFinding.id == finding_id) | (AIFinding.finding_code == finding_id)).first()
    if not finding:
        raise HTTPException(404, "Finding not found")
    ensure_patient_access(db, user, finding.patient_user_id)
    if payload.decision in ("reject", "edit", "further_evaluation") and not (payload.note or payload.edited_finding):
        raise HTTPException(422, "Please document the reason for this decision")
    before = {"finding_type": finding.finding_type, "label": finding.label, "location": finding.location, "severity": finding.severity, "review_status": finding.review_status}
    if payload.decision == "edit":
        edit = payload.edited_finding or {}
        if edit.get("finding_type"):
            if edit["finding_type"] not in ALL_FINDINGS:
                raise HTTPException(422, "Edited finding type is not in the approved vocabulary")
            finding.finding_type = edit["finding_type"]
            finding.label = label_for(edit["finding_type"])
        if edit.get("label"):
            finding.label = str(edit["label"])[:200]
        if isinstance(edit.get("location"), dict):
            finding.location = {**(finding.location or {}), **{k: v for k, v in edit["location"].items() if k in ("tooth", "region", "surface", "description")}}
        if edit.get("severity"):
            finding.severity = str(edit["severity"])[:30]
    finding.review_status = payload.decision
    finding.reviewer_id = user.id
    finding.review_note = payload.note
    finding.reviewed_at = utcnow()
    after = {"finding_type": finding.finding_type, "label": finding.label, "location": finding.location, "severity": finding.severity, "review_status": finding.review_status}
    db.add(ClinicalReview(finding_id=finding.id, reviewer_id=user.id, decision=payload.decision, note=payload.note, before=before, after=after))

    # Only dentist-confirmed (or confirmed-with-edits) findings enter the clinical record. Never silently modified.
    existing = db.query(ClinicalFinding).filter(ClinicalFinding.source_finding_id == finding.id).first()
    if payload.decision in ("confirm", "edit"):
        if existing:
            existing.finding_type, existing.label, existing.location, existing.severity = finding.finding_type, finding.label, finding.location, finding.severity
            existing.notes, existing.status, existing.confirmed_by = payload.note or "", "confirmed", user.id
        else:
            db.add(ClinicalFinding(patient_user_id=finding.patient_user_id, source_finding_id=finding.id, finding_type=finding.finding_type,
                                   label=finding.label or label_for(finding.finding_type), location=finding.location, severity=finding.severity,
                                   notes=payload.note or "", confirmed_by=user.id))
        add_event(db, finding.patient_user_id, "dentist_review", f"Dentist confirmed: {finding.label or label_for(finding.finding_type)}",
                  payload.note or "", ref_type="ai_finding", ref_id=finding.id, created_by=user.id)
    elif existing:
        existing.status = "retracted"
        existing.notes = f"Retracted after re-review ({payload.decision}). {payload.note or ''}".strip()
    if payload.decision == "further_evaluation":
        add_event(db, finding.patient_user_id, "dentist_review", "Dentist requested further examination", payload.note or "",
                  ref_type="ai_finding", ref_id=finding.id, created_by=user.id)

    log_event(db, user.id, "clinical_finding.reviewed", "ai_finding", finding.id,
              {"finding_code": finding.finding_code, "ai_finding": before["finding_type"], "edited_to": after if payload.decision == "edit" else None},
              actor_role=user.role, patient_id=finding.patient_user_id, model_name=finding.model_name, model_version=finding.model_version,
              confidence=finding.confidence, decision=payload.decision)
    insight.build_profile(db, db.get(User, finding.patient_user_id))
    db.commit()
    return {**finding_out(finding), "reviewer_id": user.id, "note": finding.review_note}


@router.get("/findings/{finding_id}/history")
def finding_history(finding_id: str, user: User = Depends(require_roles("dentist", "patient")), db: Session = Depends(get_db)):
    finding = db.get(AIFinding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    ensure_patient_access(db, user, finding.patient_user_id)
    rows = db.query(ClinicalReview).filter(ClinicalReview.finding_id == finding.id).order_by(ClinicalReview.created_at.asc()).all()
    return {"finding": finding_out(finding), "history": [{"decision": r.decision, "note": r.note, "before": r.before, "after": r.after,
                                                          "reviewer_id": r.reviewer_id, "created_at": r.created_at} for r in rows]}
