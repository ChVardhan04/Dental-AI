"""DentEdge Voice: transcription, patient symptom intake and dentist AI scribe."""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import ensure_patient_access, get_current_user, require_consent, require_roles, resolve_patient
from app.models.records import Transcript, VoiceSession
from app.models.user import User, utcnow
from app.services import insight
from app.services.audit import log_event
from app.services.emergency import detect_emergency
from app.services.knowledge import citation, retrieve
from app.services.llm.providers import ProviderUnavailable, get_speech_provider
from app.services.safety import check_text
from app.services.storage import get_storage
from app.services.timeline import add_event
from app.services.voice.dental_nlp import NLP_VERSION, continue_conversation
from app.services.voice.scribe import build_soap

router = APIRouter(prefix="/voice", tags=["Voice AI"])
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/m4a", "audio/x-m4a", "video/webm"}
SYMPTOM_TOPICS = {"sensitivity": "sensitivity", "pain": "pain", "bleeding_gums": "bleeding_gums", "bad_breath": "bad_breath", "swelling": "pain",
                  "broken_tooth": "visible_chip", "discoloration": "visible_staining"}


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user)):
    return {"server_transcription": get_speech_provider() is not None, "provider": settings.speech_provider,
            "browser_transcription_supported": True, "nlp_version": NLP_VERSION}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), patient_id: str | None = Form(default=None), purpose: str = Form(default="symptom_intake"),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = resolve_patient(db, user, patient_id)
    require_consent(db, patient.id)
    ctype = (file.content_type or "").split(";")[0]
    if ctype not in AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format")
    data = await file.read(settings.max_audio_mb * 1024 * 1024 + 1)
    if not data or len(data) > settings.max_audio_mb * 1024 * 1024:
        raise HTTPException(413, f"Audio must be between 1 byte and {settings.max_audio_mb} MB")
    provider = get_speech_provider()
    if provider is None:
        raise HTTPException(503, {"code": "speech_provider_not_configured",
                                  "message": "Server speech-to-text is not configured. Use in-browser dictation or type your message."})
    try:
        result = provider.transcribe(data, file.filename or "audio.webm", ctype)
    except ProviderUnavailable:
        raise HTTPException(502, "Speech service is temporarily unavailable. Please type your message instead.")
    key = f"{patient.id}/audio/{uuid.uuid4().hex}.enc"
    get_storage().put(key, data)
    log_event(db, user.id, "voice.transcribed", "audio", key, {"purpose": purpose, "provider": provider.name, "bytes": len(data)}, actor_role=user.role, patient_id=patient.id)
    db.commit()
    return {"text": result["text"], "segments": result.get("segments", []), "provider": provider.name, "audio_key": key}


class SymptomPayload(BaseModel):
    transcript: str = Field(min_length=1, max_length=20000)
    session_id: str | None = None
    patient_id: str | None = None
    source: str = Field(default="text", pattern="^(text|browser_speech|server_speech)$")
    session_type: str | None = None  # backwards compatibility


def _session_out(s: VoiceSession) -> dict:
    return {"id": s.id, "patient_id": s.user_id, "session_type": s.session_type, "status": s.status, "transcript": s.transcript,
            "structured": s.structured_data, "emergency": s.emergency, "created_at": s.created_at, "approved_at": s.approved_at}


@router.post("/symptoms", status_code=201)
def symptoms(payload: SymptomPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.session_type == "scribe":
        if user.role != "dentist":
            raise HTTPException(403, "The AI scribe is available to dentists only")
        return scribe(ScribePayload(transcript=payload.transcript, patient_id=payload.patient_id), user, db)
    patient = resolve_patient(db, user, payload.patient_id)
    require_consent(db, patient.id)
    session = None
    if payload.session_id:
        session = db.get(VoiceSession, payload.session_id)
        if not session or session.user_id != patient.id or session.session_type != "symptom_intake":
            raise HTTPException(404, "Session not found")
    full = ((session.transcript + "\n") if session else "") + payload.transcript.strip()
    emergency = detect_emergency(full)
    structured = continue_conversation(full, payload.transcript, session.structured_data if session else None)
    structured["emergency"] = emergency
    if emergency["emergency"]:
        structured["follow_up_questions"] = []
        structured["next_step"] = "urgent_care"
        status = "emergency_escalation"
    else:
        topics = [SYMPTOM_TOPICS[k] for k in structured["complaint_keys"] if k in SYMPTOM_TOPICS]
        evidence = retrieve(db, topics)
        structured["education"] = [{"title": e["title"], "what_it_is": e["content"]["what_it_is"], "next_step": e["content"]["next_step"],
                                    "warning_signs": e["content"]["warning_signs"], "source": citation(e)} for e in evidence]
        structured["next_step"] = "complete" if structured["complete"] else "follow_up"
        status = "complete" if structured["complete"] else "needs_more_information"
    if session:
        session.transcript, session.structured_data, session.status = full, structured, status
        session.emergency = session.emergency or emergency["emergency"]
    else:
        session = VoiceSession(user_id=patient.id, created_by=user.id, session_type="symptom_intake", transcript=full, structured_data=structured,
                               status=status, emergency=emergency["emergency"])
        db.add(session)
        db.flush()
    db.add(Transcript(session_id=session.id, text=payload.transcript, provider=payload.source))
    if status in ("complete", "emergency_escalation"):
        add_event(db, patient.id, "voice_complaint", "Symptom report" + (" — urgent care advised" if emergency["emergency"] else ""),
                  structured["summary"], ref_type="voice_session", ref_id=session.id, created_by=user.id)
    log_event(db, user.id, "voice.symptoms.structured", "voice_session", session.id, {"status": status, "emergency": emergency["emergency"],
              "signals": [s["code"] for s in emergency["signals"]], "missing": structured.get("missing_information")}, actor_role=user.role, patient_id=patient.id,
              model_name="dental-symptom-nlp", model_version=NLP_VERSION)
    insight.build_profile(db, patient)
    db.commit()
    return {**_session_out(session), "message": emergency["guidance"] if emergency["emergency"] else
            structured.get("reply") or ("Thank you. Your symptoms have been structured for your dentist." if structured["complete"] else "A few more details will help your dentist.")}


class ScribePayload(BaseModel):
    transcript: str = Field(min_length=1, max_length=60000)
    patient_id: str | None = None
    segments: list[dict] | None = None


@router.post("/scribe", status_code=201)
def scribe(payload: ScribePayload, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    if not payload.patient_id:
        raise HTTPException(422, "patient_id is required")
    patient = ensure_patient_access(db, user, payload.patient_id)
    require_consent(db, patient.id)
    draft = build_soap(payload.transcript, payload.segments)
    draft["safety_warnings"] = [v for v in check_text(draft["note_text"], payload.transcript.lower()) if v["type"] in ("unsupported_medication_advice", "dangerous_instruction")]
    session = VoiceSession(user_id=patient.id, created_by=user.id, session_type="scribe", transcript=payload.transcript, structured_data=draft, status="draft")
    db.add(session)
    db.flush()
    db.add(Transcript(session_id=session.id, text=payload.transcript, segments=draft["turns"], provider="client"))
    log_event(db, user.id, "scribe.draft.created", "voice_session", session.id, {"turns": len(draft["turns"])}, actor_role=user.role, patient_id=patient.id,
              model_name="dental-scribe", model_version=draft["scribe_version"])
    db.commit()
    return _session_out(session)


class ScribeReview(BaseModel):
    action: str = Field(pattern="^(save_edit|approve|reject)$")
    note_text: str | None = Field(default=None, max_length=30000)
    reason: str | None = Field(default=None, max_length=2000)


@router.patch("/scribe/{session_id}")
def review_scribe(session_id: str, payload: ScribeReview, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    s = db.get(VoiceSession, session_id)
    if not s or s.session_type != "scribe":
        raise HTTPException(404, "Scribe session not found")
    ensure_patient_access(db, user, s.user_id)
    if s.status in ("approved", "rejected"):
        raise HTTPException(409, "This note has already been finalised; create a new note to amend it")
    data = dict(s.structured_data)
    if payload.note_text is not None:
        data.setdefault("revisions", []).append({"at": utcnow().isoformat(), "by": user.id, "previous": data.get("note_text")})
        data["note_text"] = payload.note_text
        data["edited_by_dentist"] = True
    if payload.action == "approve":
        s.status, s.approved_by, s.approved_at = "approved", user.id, utcnow()
        add_event(db, s.user_id, "clinical_note", "Clinical note approved", (data.get("note_text") or "")[:300], ref_type="voice_session", ref_id=s.id, created_by=user.id)
    elif payload.action == "reject":
        s.status = "rejected"
        data["rejection_reason"] = payload.reason
    else:
        s.status = "draft"
    s.structured_data = data
    log_event(db, user.id, f"scribe.{payload.action}", "voice_session", s.id, {"edited": payload.note_text is not None}, actor_role=user.role,
              patient_id=s.user_id, decision=payload.action)
    db.commit()
    return _session_out(s)


@router.get("/sessions")
def list_sessions(patient_id: str | None = None, session_type: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    q = db.query(VoiceSession).filter(VoiceSession.user_id == pid)
    if session_type:
        q = q.filter(VoiceSession.session_type == session_type)
    rows = q.order_by(VoiceSession.created_at.desc()).limit(100).all()
    if user.role == "patient":
        rows = [r for r in rows if r.session_type != "scribe" or r.status == "approved"]
    return [_session_out(r) for r in rows]
