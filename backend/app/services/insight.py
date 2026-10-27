"""DentEdge Insight, Educate and Report generator."""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.records import (
    AIAnalysis, AIFinding, Appointment, ClinicalFinding, OralHealthProfile, PatientProfile, PerioChart, PerioMeasurement,
    SmileAnalysis, TimelineEvent, VoiceSession,
)
from app.models.user import User, utcnow
from app.services import perio as perio_svc
from app.services.knowledge import retrieve
from app.services.orchestrator import finding_out
from app.services.taxonomy import label_for, patient_phrase

REVIEW_LABELS = {"pending": "Awaiting dentist review", "uncertain": "Uncertain — awaiting dentist review", "confirm": "Confirmed by your dentist",
                 "edit": "Reviewed and updated by your dentist", "reject": "Not confirmed by your dentist", "further_evaluation": "Your dentist requested further examination"}


def _latest(db, model, *filters, order=None):
    q = db.query(model)
    for f in filters:
        q = q.filter(f)
    return q.order_by((order or model.created_at).desc()).first()


def _patient_visible(findings: list[AIFinding]) -> list[AIFinding]:
    return [f for f in findings if f.review_status != "reject"]


def build_profile(db: Session, patient: User) -> dict:
    vision = _latest(db, AIAnalysis, AIAnalysis.user_id == patient.id, AIAnalysis.module == "vision")
    xray = _latest(db, AIAnalysis, AIAnalysis.user_id == patient.id, AIAnalysis.module == "xray")
    comparison = _latest(db, AIAnalysis, AIAnalysis.user_id == patient.id, AIAnalysis.module == "xray_comparison")
    symptoms = _latest(db, VoiceSession, VoiceSession.user_id == patient.id, VoiceSession.session_type == "symptom_intake")
    chart = _latest(db, PerioChart, PerioChart.patient_user_id == patient.id, PerioChart.status == "confirmed")
    smile = _latest(db, SmileAnalysis, SmileAnalysis.user_id == patient.id, SmileAnalysis.status == "scored")
    pending = db.query(AIFinding).filter(AIFinding.patient_user_id == patient.id, AIFinding.review_status.in_(["pending", "uncertain"])).count()
    confirmed = db.query(ClinicalFinding).filter(ClinicalFinding.patient_user_id == patient.id).order_by(ClinicalFinding.created_at.desc()).limit(20).all()

    def findings_line(a: AIAnalysis | None) -> dict | None:
        if not a:
            return None
        fs = _patient_visible(db.query(AIFinding).filter(AIFinding.analysis_id == a.id).all())
        if not a.status.startswith("review") and not fs:
            text = a.summary[:160]
        elif fs:
            text = ", ".join(dict.fromkeys(f.label or label_for(f.finding_type) for f in fs))
        else:
            text = "No observations flagged"
        return {"text": text, "status": a.status, "date": a.created_at, "analysis_id": a.id, "finding_count": len(fs),
                "pending_review": sum(1 for f in fs if f.review_status in ("pending", "uncertain"))}

    perio_line = None
    if chart:
        rows = db.query(PerioMeasurement).filter(PerioMeasurement.chart_id == chart.id).all()
        s = perio_svc.build_chart([{"seq": r.seq, "tooth": r.tooth, "site": r.site, "kind": r.kind, "value": r.value} for r in rows])["summary"]
        bits = []
        if s["bleeding_on_probing_percent"]:
            bits.append(f"Bleeding recorded at {s['bleeding_on_probing_percent']}% of sites")
        bits.append(f"{s['sites_4mm_or_more']} site(s) ≥4 mm")
        perio_line = {"text": "; ".join(bits), "date": chart.confirmed_at or chart.created_at, "chart_id": chart.id, "summary": s}

    if comparison:
        prev_text = comparison.result_json.get("comparison", {}).get("current", "")
    elif confirmed:
        prev_text = f"{len(confirmed)} dentist-confirmed finding(s) on record"
    else:
        prev_text = "No previous examination on record"
    if symptoms and symptoms.emergency:
        next_step = "Urgent professional care was advised for reported symptoms"
    elif pending:
        next_step = f"Dentist review ({pending} AI observation(s) awaiting review)"
    else:
        next_step = "Routine check-up"
    profile = {
        "patient_id": patient.id, "patient_name": patient.full_name, "generated_at": utcnow(),
        "photo": findings_line(vision), "xray": findings_line(xray),
        "symptoms": {"text": symptoms.structured_data.get("summary") or symptoms.transcript[:140], "date": symptoms.created_at, "emergency": symptoms.emergency} if symptoms else None,
        "perio": perio_line,
        "smile": {"score": smile.overall_score, "date": smile.created_at, "metrics": smile.metrics.get("metrics")} if smile else None,
        "previous_examination": prev_text,
        "confirmed_findings": [{"label": c.label or label_for(c.finding_type), "location": c.location, "date": c.created_at, "status": c.status} for c in confirmed],
        "pending_review_count": pending, "next_step": next_step,
        "disclaimer": "This profile combines AI-assisted observations and dentist-confirmed records. AI observations are not diagnoses.",
    }
    row = db.query(OralHealthProfile).filter(OralHealthProfile.patient_user_id == patient.id).first()
    cached = {k: (str(v) if k in ("generated_at",) else v) for k, v in profile.items()}
    if row:
        row.profile, row.updated_at = _jsonable(cached), utcnow()
    else:
        db.add(OralHealthProfile(patient_user_id=patient.id, profile=_jsonable(cached)))
    return profile


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def education_report(db: Session, analysis: AIAnalysis) -> dict:
    """structure, built only from structured findings + approved evidence."""
    findings = _patient_visible(db.query(AIFinding).filter(AIFinding.analysis_id == analysis.id).all())
    exp = analysis.result_json.get("explanation", {})
    evidence = retrieve(db, list({f.finding_type for f in findings}) or ["no_findings"])
    sections = []
    for f in findings:
        doc = next((e for e in evidence if f.finding_type in e["topics"]), None)
        c = doc["content"] if doc else {}
        sections.append({
            "finding_code": f.finding_code, "review_status": REVIEW_LABELS.get(f.review_status, f.review_status),
            "what_we_observed": f"{patient_phrase(f.finding_type).capitalize()} ({(f.location or {}).get('description', 'see image')}).",
            "what_it_may_indicate": c.get("what_it_is", "A dentist should evaluate this observation."),
            "why_it_matters": c.get("why_it_matters", ""), "possible_contributing_factors": c.get("factors", []),
            "what_happens_next": c.get("next_step", "Discuss with your dentist."), "questions_for_your_dentist": c.get("questions", []),
            "urgent_warning_signs": c.get("warning_signs", []),
            "source": {"title": doc["title"], "version": doc["version"], "reviewer": doc["reviewer"]} if doc else None,
        })
    return {"analysis_id": analysis.id, "summary": exp.get("summary", analysis.summary), "sections": sections,
            "recommended_next_step": exp.get("recommended_next_step"), "urgency": analysis.urgency, "limitations": exp.get("limitations", []),
            "appointment_cta": {"label": "Book an appointment", "url": settings.appointment_booking_url},
            "disclaimer": "Educational information based on AI-assisted observations and DentEdge-approved content. Not a diagnosis."}


def patient_report(db: Session, patient: User, analysis: AIAnalysis) -> dict:
    """patient report."""
    findings = _patient_visible(db.query(AIFinding).filter(AIFinding.analysis_id == analysis.id).all())
    r = analysis.result_json
    exp = r.get("explanation", {})
    symptoms = _latest(db, VoiceSession, VoiceSession.user_id == patient.id, VoiceSession.session_type == "symptom_intake")
    xt = r.get("xray_type")
    xray_view = xt.get("detected_type") if isinstance(xt, dict) else xt
    images = r.get("images") or ([{"image_id": analysis.image_asset_id, "view": xray_view, "quality": r.get("quality") or {"accepted": True, "reason": "Accepted"}}]
                                 if analysis.image_asset_id else [])
    obs = [{"finding_code": f.finding_code, "observation": patient_phrase(f.finding_type), "location": (f.location or {}).get("description"),
            "ai_confidence": f"{round(f.confidence * 100)}%", "review_status": REVIEW_LABELS.get(f.review_status, f.review_status)} for f in findings]
    return {
        "title": "DentEdge AI Assessment", "patient": patient.full_name, "date": analysis.created_at, "analysis_id": analysis.id, "module": analysis.module,
        "images_analyzed": [{"image_id": i.get("image_id"), "view": i.get("view")} for i in images],
        "image_quality": [{"image_id": i.get("image_id"), "accepted": (i.get("quality") or {}).get("accepted"), "note": (i.get("quality") or {}).get("reason")} for i in images],
        "visual_observations": obs if analysis.module == "vision" else [],
        "xray_observations": obs if analysis.module.startswith("xray") else [],
        "patient_symptoms": (symptoms.structured_data.get("summary") if symptoms else None),
        "ai_confidence_note": "Confidence describes how strongly the AI model detected a visual pattern. It is not the probability of a disease.",
        "important_limitations": exp.get("limitations", []),
        "patient_friendly_explanation": exp.get("summary"), "possible_explanations": exp.get("possible_explanations", []),
        "recommended_follow_up": exp.get("recommended_next_step"), "urgency": analysis.urgency,
        "questions_for_dentist": exp.get("questions_for_dentist", []), "warning_signs": exp.get("warning_signs", []),
        "appointment_cta": {"label": "Book an appointment", "url": settings.appointment_booking_url},
        "sources": r.get("citations", []),
        "model": {"name": analysis.model_name, "version": analysis.model_version, "rules_version": analysis.rules_version},
    }


def dentist_report(db: Session, patient: User, analysis: AIAnalysis) -> dict:
    """dentist report (more detailed)."""
    findings = db.query(AIFinding).filter(AIFinding.analysis_id == analysis.id).all()
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == patient.id).first()
    symptoms = _latest(db, VoiceSession, VoiceSession.user_id == patient.id, VoiceSession.session_type == "symptom_intake")
    scribe = _latest(db, VoiceSession, VoiceSession.user_id == patient.id, VoiceSession.session_type == "scribe")
    chart = _latest(db, PerioChart, PerioChart.patient_user_id == patient.id)
    comparison = _latest(db, AIAnalysis, AIAnalysis.user_id == patient.id, AIAnalysis.module == "xray_comparison")
    confirmed = db.query(ClinicalFinding).filter(ClinicalFinding.patient_user_id == patient.id).order_by(ClinicalFinding.created_at.desc()).limit(50).all()
    perio_summary = None
    if chart:
        rows = db.query(PerioMeasurement).filter(PerioMeasurement.chart_id == chart.id).all()
        perio_summary = {"chart_id": chart.id, "status": chart.status,
                         **perio_svc.build_chart([{"seq": x.seq, "tooth": x.tooth, "site": x.site, "kind": x.kind, "value": x.value} for x in rows])["summary"]}
    r = analysis.result_json
    return {
        "title": "DentEdge AI — Dentist Report", "generated_at": utcnow(),
        "patient_information": {"id": patient.id, "name": patient.full_name, "email": patient.email, "date_of_birth": profile.date_of_birth if profile else None},
        "ai_analysis_summary": {"analysis_id": analysis.id, "module": analysis.module, "status": analysis.status, "summary": analysis.summary,
                                "urgency": analysis.urgency, "model": analysis.model_name, "model_version": analysis.model_version,
                                "rules_version": analysis.rules_version, "prompt_version": analysis.prompt_version, "created_at": analysis.created_at},
        "image_quality": r.get("images") or r.get("quality"), "xray_type": r.get("xray_type"),
        "findings": [finding_out(f) for f in findings], "evidence": r.get("citations", []),
        "annotations": [{"image_id": k, "url": f"/api/v1/analyses/{analysis.id}/annotated/{k}"} for k in (r.get("annotated") or {})],
        "historical_comparison": comparison.result_json.get("comparison") if comparison else None,
        "patient_symptoms": symptoms.structured_data if symptoms else None, "perio_data": perio_summary,
        "ai_generated_draft_notes": {"session_id": scribe.id, "status": scribe.status, "note_text": scribe.structured_data.get("note_text")} if scribe else None,
        "dentist_review": [{"finding_code": f.finding_code, "decision": f.review_status, "note": f.review_note, "reviewed_at": f.reviewed_at} for f in findings if f.reviewer_id],
        "final_clinical_findings": [{"label": c.label, "finding_type": c.finding_type, "location": c.location, "notes": c.notes, "status": c.status, "date": c.created_at} for c in confirmed],
        "pipeline_trace": r.get("pipeline_trace"), "safety": r.get("safety"), "rules": r.get("clinical_gate"),
    }


def timeline(db: Session, patient_id: str) -> list[dict]:
    events = db.query(TimelineEvent).filter(TimelineEvent.patient_user_id == patient_id).order_by(TimelineEvent.occurred_at.desc()).limit(300).all()
    appts = db.query(Appointment).filter(Appointment.patient_user_id == patient_id).all()
    out = [{"id": e.id, "type": e.event_type, "title": e.title, "summary": e.summary, "ref_type": e.ref_type, "ref_id": e.ref_id,
            "date": e.occurred_at, "year": e.occurred_at.year} for e in events]
    out += [{"id": a.id, "type": "appointment", "title": f"Appointment request ({a.status})", "summary": a.reason, "ref_type": "appointment",
             "ref_id": a.id, "date": a.created_at, "year": a.created_at.year} for a in appts]
    return sorted(out, key=lambda e: e["date"], reverse=True)
