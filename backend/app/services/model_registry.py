"""AI Model Registry. Every AI result identifies exactly which model generated it,
and the orchestrator only runs model versions whose deployment status is permitted."""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.records import AIModel, AIModelVersion

DEPLOYMENT_STATUSES = ["research", "staging", "production", "retired", "disabled"]
APPROVAL_STATUSES = ["pending", "approved", "rejected"]

# Baseline input statistics for drift detection. Replace with statistics computed from the
# real training dataset when a trained model is registered.
_PHOTO_REF = {"brightness_mean": {"mean": 132.0, "std": 28.0}, "blur_score": {"mean": 420.0, "std": 260.0}, "contrast_std": {"mean": 52.0, "std": 14.0}}
_XRAY_REF = {"brightness_mean": {"mean": 118.0, "std": 30.0}, "blur_score": {"mean": 160.0, "std": 120.0}, "contrast_std": {"mean": 58.0, "std": 15.0}}

SEED_MODELS = [
    # name, task, modality, description, version, status, approval, training, validation, metrics, reference
    ("dental-image-quality-gate", "quality_gate", "photo+xray", "Deterministic technical and dental-suitability gate (format, decoding, dental content, resolution, lighting, blur, coverage).",
     "1.2.0", "production", "approved", "n/a (deterministic rules)", "Internal red-team set v1", {"type": "deterministic"}, {}),
    ("oral-vision-heuristic", "oral_photo_findings", "photo", "Colour-space measurement model: visible staining, possible plaque, visible gum changes, visible spacing. Research use only.",
     "0.3.0", "research", "pending", "n/a (unsupervised colour analysis)", "Not clinically validated", {"note": "No clinical performance claims"}, _PHOTO_REF),
    ("oral-vision-llm", "oral_photo_findings", "photo", "Vision-language model constrained to the controlled finding vocabulary. Enabled when VISION_PROVIDER=llm.",
     "1.0.0", "research", "pending", "Provider foundation model", "Not clinically validated", {}, _PHOTO_REF),
    ("xray-type-classifier", "xray_type", "xray", "Classifies periapical / bitewing / panoramic from geometry and intensity profile.",
     "0.2.0", "research", "pending", "n/a (geometric rules)", "Internal sample set", {}, _XRAY_REF),
    ("xray-anatomy-detector", "xray_anatomy", "xray", "Detects radiopaque dental structures and maps them to approximate tooth regions.",
     "0.2.0", "research", "pending", "n/a (classical CV)", "Not clinically validated", {}, _XRAY_REF),
    ("xray-radiolucency-candidate", "xray_findings", "xray", "Flags areas of reduced radiodensity inside dental structures for dentist review. Does not diagnose caries.",
     "0.1.0", "research", "pending", "n/a (classical CV)", "Not clinically validated", {"supported_types": ["periapical", "bitewing", "panoramic"]}, _XRAY_REF),
    ("xray-comparison", "xray_comparison", "xray", "Registers previous and current radiographs (ORB + RANSAC homography) and highlights changed regions.",
     "0.2.0", "research", "pending", "n/a (classical CV)", "Not clinically validated", {}, {}),
    ("smile-cosmetic-analyzer", "smile_score", "photo", "Cosmetic visual metrics (symmetry, alignment, staining, visibility, gum display, balance). Not a medical score.",
     "0.3.0", "research", "pending", "n/a (geometric/colour analysis)", "Not clinically validated", {}, _PHOTO_REF),
    ("dental-symptom-nlp", "symptom_extraction", "text", "Deterministic dental terminology normaliser, symptom extractor and missing-information detector.",
     "1.1.0", "production", "approved", "Rule lexicon v1.1", "Internal phrase test set", {"type": "deterministic"}, {}),
    ("dental-scribe", "clinical_note", "text", "Speaker attribution, clinical information extraction and SOAP draft generation. Dentist approval required.",
     "1.0.0", "staging", "pending", "Rule lexicon v1.1 + optional LLM", "Internal transcripts", {}, {}),
    ("perio-voice-parser", "perio_commands", "text", "Periodontal voice command parser and tooth/site state machine.",
     "1.0.0", "production", "approved", "Rule grammar v1", "Internal command set", {"type": "deterministic"}, {}),
    ("patient-explainer", "explanation", "text", "Evidence-grounded explanation generator (template or configured LLM provider) behind the safety gateway.",
     "1.0.0", "production", "approved", "n/a", "Safety test suite", {}, {}),
]


@dataclass
class ActiveModel:
    name: str
    version: str
    deployment_status: str
    approval_status: str
    metrics: dict
    reference_stats: dict

    @property
    def is_research(self) -> bool:
        return self.deployment_status != "production"


def seed_models(db: Session) -> None:
    for name, task, modality, desc, version, status, approval, train, val, metrics, ref in SEED_MODELS:
        model = db.query(AIModel).filter(AIModel.name == name).first()
        if not model:
            model = AIModel(name=name, task=task, modality=modality, description=desc)
            db.add(model)
            db.flush()
        if not db.query(AIModelVersion).filter(AIModelVersion.model_id == model.id, AIModelVersion.version == version).first():
            db.add(AIModelVersion(model_id=model.id, version=version, deployment_status=status, approval_status=approval,
                                  training_dataset=train, validation_dataset=val, metrics=metrics, reference_stats=ref))
    db.commit()


_RANK = {"production": 3, "staging": 2, "research": 1}


def get_active(db: Session, name: str) -> ActiveModel | None:
    """Return the best permitted version of a model, or None if no version may run."""
    model = db.query(AIModel).filter(AIModel.name == name).first()
    if not model:
        return None
    versions = db.query(AIModelVersion).filter(AIModelVersion.model_id == model.id).all()
    candidates = [v for v in versions if v.deployment_status in settings.model_statuses and v.deployment_status in _RANK and v.approval_status != "rejected"]
    if not candidates:
        return None
    best = sorted(candidates, key=lambda v: (_RANK[v.deployment_status], _vkey(v.version)), reverse=True)[0]
    return ActiveModel(model.name, best.version, best.deployment_status, best.approval_status, best.metrics or {}, best.reference_stats or {})


def _vkey(v: str):
    out = []
    for part in v.split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out)
