"""Clinical and AI data model (Production )."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import new_id, utcnow


def _id():
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created():
    return mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- people & access
class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    medical_history: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class DentistAssignment(Base):
    """Dentists may only access patients explicitly assigned to them."""
    __tablename__ = "dentist_assignments"
    __table_args__ = (UniqueConstraint("dentist_user_id", "patient_user_id", name="uq_dentist_patient"),)
    id: Mapped[str] = _id()
    dentist_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created()


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    dentist_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    preferred_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    urgency: Mapped[str] = mapped_column(String(20), default="routine")
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    created_at: Mapped[datetime] = _created()


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(40))
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- images
class ImageAsset(Base):
    __tablename__ = "image_assets"
    id: Mapped[str] = _id()
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # the patient
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_kind: Mapped[str] = mapped_column(String(30), default="oral_photo")  # oral_photo | xray | smile
    view: Mapped[str | None] = mapped_column(String(40), nullable=True)  # front_smile, upper_teeth, periapical ...
    storage_key: Mapped[str] = mapped_column(String(500))
    annotated_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    quality_result: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class XRayStudy(Base):
    __tablename__ = "xray_studies"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    image_asset_id: Mapped[str] = mapped_column(ForeignKey("image_assets.id"), index=True)
    declared_type: Mapped[str] = mapped_column(String(30), default="unknown")
    detected_type: Mapped[str] = mapped_column(String(30), default="unknown")
    type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    study_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- model registry
class AIModel(Base):
    __tablename__ = "ai_models"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    task: Mapped[str] = mapped_column(String(80))
    modality: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class AIModelVersion(Base):
    __tablename__ = "ai_model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)
    id: Mapped[str] = _id()
    model_id: Mapped[str] = mapped_column(ForeignKey("ai_models.id"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    training_dataset: Mapped[str] = mapped_column(String(200), default="")
    validation_dataset: Mapped[str] = mapped_column(String(200), default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    deployment_status: Mapped[str] = mapped_column(String(20), default="research")  # research|staging|production|retired|disabled
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reference_stats: Mapped[dict] = mapped_column(JSON, default=dict)  # input distribution baseline for drift
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- analysis & findings
class AIAnalysis(Base):
    __tablename__ = "ai_analyses"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # patient
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_asset_id: Mapped[str | None] = mapped_column(ForeignKey("image_assets.id"), nullable=True)
    module: Mapped[str] = mapped_column(String(40), index=True)  # vision | xray | xray_comparison | smile
    status: Mapped[str] = mapped_column(String(30), default="queued")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    model_version: Mapped[str] = mapped_column(String(40), default="")
    rules_version: Mapped[str] = mapped_column(String(20), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    urgency: Mapped[str] = mapped_column(String(20), default="routine")
    summary: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class AIFinding(Base):
    __tablename__ = "ai_findings"
    id: Mapped[str] = _id()
    finding_code: Mapped[str] = mapped_column(String(20), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("ai_analyses.id"), index=True)
    patient_user_id: Mapped[str] = mapped_column(String(36), index=True)
    image_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[dict] = mapped_column(JSON, default=dict)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [x, y, w, h] in source pixels
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(30), default="uncertain")
    evidence: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    model_version: Mapped[str] = mapped_column(String(40), default="")
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class ClinicalReview(Base):
    """Immutable history of every dentist decision on an AI finding."""
    __tablename__ = "clinical_reviews"
    id: Mapped[str] = _id()
    finding_id: Mapped[str] = mapped_column(ForeignKey("ai_findings.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class ClinicalFinding(Base):
    """Dentist-confirmed finding: the only kind that enters the clinical record."""
    __tablename__ = "clinical_findings"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_finding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40), default="ai_review")
    finding_type: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(30), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="confirmed")
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- voice
class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # patient
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_type: Mapped[str] = mapped_column(String(30), default="symptom_intake")  # symptom_intake | scribe
    transcript: Mapped[str] = mapped_column(Text, default="")
    audio_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    structured_data: Mapped[dict] = mapped_column(JSON, default=dict)
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[str] = _id()
    session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    segments: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(40), default="client")
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- perio
class PerioChart(Base):
    __tablename__ = "perio_charts"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    dentist_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="in_progress")  # in_progress|paused|completed|confirmed
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    measurements: Mapped[list] = mapped_column(JSON, default=list)  # legacy/summary snapshot
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class PerioMeasurement(Base):
    __tablename__ = "perio_measurements"
    id: Mapped[str] = _id()
    chart_id: Mapped[str] = mapped_column(ForeignKey("perio_charts.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    tooth: Mapped[str] = mapped_column(String(4))
    site: Mapped[str | None] = mapped_column(String(4), nullable=True)  # DB B MB DL L ML; None = tooth-level
    kind: Mapped[str] = mapped_column(String(20))  # probing_depth|bleeding|plaque|mobility|furcation|recession|missing
    value: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- smile, education, insight
class SmileAnalysis(Base):
    __tablename__ = "smile_analyses"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    image_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = _created()


class PatientEducationReport(Base):
    __tablename__ = "education_reports"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    report_type: Mapped[str] = mapped_column(String(20), default="patient")  # patient | dentist
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_provider: Mapped[str] = mapped_column(String(40), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    safety: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class OralHealthProfile(Base):
    __tablename__ = "oral_health_profiles"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimelineEvent(Base):
    """OralHealthTimeline entries."""
    __tablename__ = "timeline_events"
    id: Mapped[str] = _id()
    patient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurred_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- knowledge
class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = _id()
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    topics: Mapped[list] = mapped_column(JSON, default=list)  # finding types / symptom keys it supports
    created_at: Mapped[datetime] = _created()


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_knowledge_version"),)
    id: Mapped[str] = _id()
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    version: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict] = mapped_column(JSON, default=dict)  # what_it_is, why_it_matters, factors, next_step, questions, warning_signs
    source: Mapped[str] = mapped_column(String(300))
    publication_date: Mapped[str] = mapped_column(String(10))
    review_date: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | retired
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- audit
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = _id()
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    patient_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created()
