"""Unit, model-behaviour and safety tests for individual services."""
import imagegen as g

from app.services import confidence, perio, safety
from app.services.clinical_rules import apply_rules, validate_findings
from app.services.emergency import detect_emergency
from app.services.explainer import template_explanation
from app.services.image_quality import assess_image
from app.services.smile import analyze_smile
from app.services.vision.models import HeuristicOralVisionModel
from app.services.voice.dental_nlp import extract_symptoms
from app.services.voice.scribe import build_soap, diarize
from app.services.xray import pipeline as xp


# --------------------------------------------------------------------------- image quality gate
def q(data, ct="image/png", kind="oral_photo", view="front_smile"):
    r = assess_image(data, ct, image_kind=kind, view=view)
    r.pop("sanitized", None)
    return r


def test_valid_oral_photo_passes():
    r = q(g.oral_photo())
    assert r["accepted"] and r["dental_image_verified"]


def test_rejects_unsupported_mime_type():
    r = q(b"not an image", "application/pdf")
    assert r["accepted"] is False and r["status"] == "rejected"


def test_rejects_corrupted_file():
    assert q(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)["accepted"] is False


def test_rejects_content_type_spoofing():
    assert q(g.oral_photo(), "image/jpeg")["checks"].get("type_mismatch")


def test_rejects_non_dental_image():
    r = q(g.landscape())
    assert not r["accepted"] and r["status"] == "not_dental"


def test_rejects_blurry_dark_and_low_resolution():
    assert q(g.blurry_oral())["checks"]["sharpness"] is False
    assert q(g.dark_oral())["accepted"] is False
    r = q(g.tiny_oral())
    assert r["checks"]["minimum_resolution"] is False and "Resolution" in r["reason"]


def test_wrong_modality_routing():
    assert q(g.xray())["status"] == "not_dental"  # X-ray uploaded as a photo
    assert q(g.oral_photo(), kind="xray")["status"] == "not_dental"  # photo uploaded as an X-ray
    assert q(g.xray(), kind="xray", view="bitewing")["accepted"]


def test_metadata_is_stripped():
    r = assess_image(g.jpeg_with_metadata(), "image/jpeg", image_kind="oral_photo", view="front_smile")
    assert r["metrics"]["metadata_removed"] is True
    assert b"IGNORE PREVIOUS" not in r["sanitized"]


# --------------------------------------------------------------------------- rules engine
def test_quality_gate_blocks_findings():
    r = validate_findings([{"finding_type": "visible_staining", "confidence": .99}], {"accepted": False})
    assert r["allowed"] is False and r["findings"] == [] and "R001" in r["rules_fired"]


def test_findings_always_require_review_and_low_confidence_is_uncertain():
    r = apply_rules([{"finding_type": "visible_staining", "confidence": .95}, {"finding_type": "visible_plaque", "confidence": .3}],
                    module="vision", quality={"accepted": True})
    assert all(f["requires_review"] for f in r["findings"])
    assert {f["finding_type"]: f["review_status"] for f in r["findings"]}["visible_plaque"] == "uncertain"


def test_unsupported_finding_types_are_rejected():
    r = apply_rules([{"finding_type": "severe_periodontitis", "confidence": .99}], module="vision", quality={"accepted": True})
    assert r["findings"] == [] and "R003" in r["rules_fired"]


def test_emergency_stops_normal_flow():
    r = apply_rules([{"finding_type": "visible_staining", "confidence": .9}], module="vision", quality={"accepted": True},
                    emergency={"emergency": True, "guidance": "go"})
    assert r["status"] == "emergency_escalation" and r["urgency"] == "urgent" and r["findings"] == []


def test_unpermitted_model_and_unsupported_xray_type():
    assert apply_rules([], module="vision", quality={"accepted": True}, model_permitted=False)["status"] == "model_not_permitted"
    r = apply_rules([], module="xray", quality={"accepted": True}, xray_type="panoramic", supported_xray_types=["bitewing"])
    assert r["status"] == "unsupported_xray_type"


def test_rules_are_deterministic():
    f = [{"finding_type": "visible_staining", "confidence": .7, "bbox": [0, 0, 10, 10]}]
    assert apply_rules(f, module="vision", quality={"accepted": True}) == apply_rules(f, module="vision", quality={"accepted": True})


def test_confidence_is_quality_weighted_and_capped():
    assert confidence.calibrate(0.99, quality_score=1.0, research=True) <= confidence.RESEARCH_CONFIDENCE_CAP
    assert confidence.calibrate(0.8, quality_score=0.2) < confidence.calibrate(0.8, quality_score=1.0)


# --------------------------------------------------------------------------- safety gateway
EVIDENCE = [{"topics": ["visible_staining"], "content": {"factors": ["Coffee"], "why_it_matters": "Most staining is cosmetic."}}]


def _out(**kw):
    base = {"summary": "The image shows areas of visible staining. A dentist should evaluate this.", "observations": [], "urgency": "routine",
            "requires_dentist_review": True, "limitations": []}
    base.update(kw)
    return base


def test_safety_rejects_hallucinated_finding():
    out = _out(summary="Patient has severe periodontal disease.")
    r = safety.validate_explanation(out, finding_types=["visible_staining"], expected_urgency="routine", evidence=EVIDENCE)
    types = {v["type"] for v in r["violations"]}
    assert not r["passed"] and ("unsupported_diagnosis" in types or "hallucinated_finding" in types)


def test_safety_rejects_certainty_treatment_medication_and_danger():
    for text, kind in [("This is definitely nothing to worry about.", "excessive_certainty"),
                       ("You need a root canal on this tooth.", "unsupported_treatment_recommendation"),
                       ("Take 400 mg ibuprofen.", "unsupported_medication_advice"),
                       ("You can pull the tooth out yourself.", "dangerous_instruction")]:
        r = safety.validate_explanation(_out(summary=text), finding_types=["visible_staining"], expected_urgency="routine", evidence=EVIDENCE)
        assert kind in {v["type"] for v in r["violations"]}, text


def test_safety_detects_missing_escalation_and_contradiction():
    r = safety.validate_explanation(_out(urgency="routine"), finding_types=[], expected_urgency="urgent", evidence=[])
    types = {v["type"] for v in r["violations"]}
    assert "missing_escalation" in types and "contradictory_information" in types
    r = safety.validate_explanation(_out(requires_dentist_review=False), finding_types=["visible_staining"], expected_urgency="routine", evidence=EVIDENCE)
    assert "contradictory_information" in {v["type"] for v in r["violations"]}


def test_template_explanations_always_pass_safety():
    from app.seed.knowledge_seed import DOCS
    evidence = [{"topics": t, "title": title, "content": c} for _, title, t, c in DOCS]
    for types in (["visible_staining", "visible_plaque"], ["visible_gingival_changes"], ["radiolucent_area_for_review", "restoration_present"], []):
        findings = [{"finding_type": t, "finding_code": f"F-{i}", "confidence": .7, "location": {"description": "upper front area"}} for i, t in enumerate(types)]
        for urgency in ("routine", "soon"):
            out = template_explanation(findings, evidence, urgency)
            r = safety.validate_explanation(out, finding_types=types, expected_urgency=urgency, evidence=evidence)
            assert r["passed"], (types, r["violations"])
    out = template_explanation([], [], "urgent")
    assert safety.validate_explanation(out, finding_types=[], expected_urgency="urgent", evidence=[])["passed"]


# --------------------------------------------------------------------------- emergency
def test_emergency_detection_and_negation():
    for text in ["My face is really swollen and I have a fever", "I'm having difficulty breathing", "it hurts to swallow and I can't swallow",
                 "the bleeding won't stop after extraction", "my tooth got knocked out playing cricket"]:
        assert detect_emergency(text)["emergency"], text
    for text in ["I have no swelling and no fever", "My tooth is sensitive to cold", "It hurts when I fall asleep on that side"]:
        assert not detect_emergency(text)["emergency"], text


# --------------------------------------------------------------------------- dental NLP
def test_symptom_extraction_and_missing_information():
    s = extract_symptoms("My tooth is sensitive when I drink something cold")
    assert s["complaint"] == "tooth sensitivity" and s["trigger"] == "cold"
    assert {"duration", "location", "severity"} <= set(s["missing_information"])
    assert len(s["follow_up_questions"]) >= 1
    s = extract_symptoms("Sharp sensitivity to cold in my upper left back tooth for 2 weeks, about 6 out of 10")
    assert s["complete"] and s["duration"] == "2 weeks" and s["severity"]["score"] == 6 and s["location"]["side"] == "left"


def test_terminology_normalisation():
    s = extract_symptoms("my wisdom tooth hurts and my gums bleed when I brush")
    terms = {t["term"] for t in s["terminology"]}
    assert "third molar" in terms and "bleeding gums" in s["complaints"]


# --------------------------------------------------------------------------- scribe
def test_scribe_diarization_and_soap():
    t = ("Patient: My lower right molar hurts when I chew, for about a week.\nDentist: I can see a deep cavity on tooth 46 distal. "
         "Probing depth of 5 mm on 46. We will schedule a filling and review in two weeks.")
    turns = diarize(t)
    assert [x["speaker"] for x in turns] == ["patient", "dentist"]
    soap = build_soap(t)
    assert "46" in soap["note"]["objective"]["teeth_referenced"]
    assert soap["note"]["plan"]["clinician_stated"] and soap["requires_dentist_approval"]
    assert "DRAFT" in soap["note_text"]


# --------------------------------------------------------------------------- perio state machine
def test_perio_state_machine_commands():
    e = perio.PerioEngine(None)
    e.process("start")
    e.process("3 2 3")
    assert e.public_state()["position"]["tooth"] == "17"
    e.process("bleeding")
    e.process("4 5 4")
    e.process("undo")
    assert e.public_state()["position"]["tooth"] == "17"
    e.process("mobility 2")
    e.process("jump to tooth 26")
    assert e.public_state()["position"]["tooth"] == "26"
    e.process("pause")
    try:
        e.process("3 3 3")
        raise AssertionError("paused engine accepted measurements")
    except perio.PerioError:
        pass
    e.process("resume")
    e.process("three two four")
    e.process("tooth 27 missing")
    msgs = e.process("repeat")["messages"]
    assert "Current position" in msgs[0]


def test_perio_validation_and_chart():
    e = perio.PerioEngine(None)
    e.process("start")
    for bad in ("20", "mobility 7", "jump to tooth 99"):
        try:
            e.process(bad)
            raise AssertionError(bad)
        except perio.PerioError:
            pass
    rows = []
    for cmd in ("3 2 3", "bleeding", "5 6 4"):
        res = e.process(cmd)
        rows += res["new"]
    chart = perio.build_chart(rows)
    assert chart["summary"]["sites_recorded"] == 6
    assert chart["summary"]["sites_6mm_or_more"] == 1
    assert chart["summary"]["bleeding_on_probing_percent"] > 0
    assert "measured the gum pockets" in perio.patient_report(chart)["summary"]


# --------------------------------------------------------------------------- vision, smile, x-ray model behaviour
def test_vision_model_finds_staining_spacing_and_gum_changes():
    r = HeuristicOralVisionModel().analyze(g.oral_photo(as_array=True, stain=True, red_gums=True, gap=True), "front_smile")
    types = {f["finding_type"] for f in r["findings"]}
    assert {"visible_staining", "visible_spacing", "visible_gingival_changes"} <= types
    assert all(f["bbox"] and f["location"]["region"] for f in r["findings"])


def test_vision_model_does_not_fabricate_on_clean_image():
    assert HeuristicOralVisionModel().analyze(g.oral_photo(as_array=True), "front_smile")["findings"] == []


def test_smile_score_is_bounded_and_cosmetic():
    r = analyze_smile(g.oral_photo(as_array=True))
    assert r["status"] == "scored" and 0 <= r["overall"] <= 100
    assert "not a medical score" in r["disclaimer"]
    assert analyze_smile(g.oral_photo(as_array=True)[:50, :50])["status"] == "not_scored"


def test_xray_type_detection_anatomy_findings_and_comparison():
    gray = xp.to_gray(g.xray(as_array=True))
    t = xp.classify_type(gray, "panoramic")
    assert t["detected_type"] == "bitewing" and t["type_mismatch"]
    pre = xp.preprocess(gray)
    an = xp.detect_anatomy(pre, "bitewing")
    assert an["structure_count"] >= 6
    cands = xp.radiolucency_candidates(pre, an["mask"], "bitewing")
    assert cands and abs(cands[0]["bbox"][0] + cands[0]["bbox"][2] / 2 - 260) < 40
    cmp = xp.compare(xp.to_gray(g.xray(as_array=True, lesion=False)), gray, "bitewing")
    assert cmp["alignment"]["success"] and cmp["changes"]
    same = xp.compare(gray, gray, "bitewing")
    assert same["changes"] == []


# --------------------------------------------------------------------------- LLM provider abstraction + hallucination protection
class _FakeLLM:
    name = "fake"
    supports_generation = True

    def __init__(self, output):
        self.output = output

    def complete_json(self, system, user):
        assert "FINDINGS" in user and "Never diagnose" in system
        return self.output


def test_llm_hallucination_is_rejected_and_template_used(monkeypatch):
    from app.services import explainer
    bad = {"summary": "Patient has severe periodontal disease and needs antibiotics.", "observations": [], "urgency": "routine", "requires_dentist_review": True}
    monkeypatch.setattr(explainer, "get_llm_provider", lambda: _FakeLLM(bad))
    findings = [{"finding_type": "visible_staining", "finding_code": "F-1", "confidence": .7, "location": {}}]
    r = explainer.explain(findings, [], "routine")
    assert r["provider"] == "template" and r["safety"]["passed"] and r["safety"]["rejected_generation_violations"]


def test_llm_safe_output_is_used(monkeypatch):
    from app.services import explainer
    good = {"summary": "The photo shows some visible staining. A dentist should look at it.", "observations": [{"finding_code": "F-1", "text": "Visible staining on a front tooth."}],
            "possible_explanations": [], "recommended_next_step": "Mention it at your next check-up.", "urgency": "routine", "limitations": ["Not a diagnosis."],
            "questions_for_dentist": [], "warning_signs": [], "requires_dentist_review": True}
    monkeypatch.setattr(explainer, "get_llm_provider", lambda: _FakeLLM(good))
    r = explainer.explain([{"finding_type": "visible_staining", "finding_code": "F-1", "confidence": .7, "location": {}}], [], "routine")
    assert r["provider"] == "fake" and r["explanation"]["summary"].startswith("The photo")


def test_provider_selection_falls_back_safely(monkeypatch):
    from app.core.config import settings
    from app.services.llm import providers
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert providers.get_llm_provider().name == "template"
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    assert providers.get_llm_provider().name == "openai"
    monkeypatch.setattr(settings, "llm_provider", "local")
    assert providers.get_llm_provider().name == "local"


def test_production_configuration_guards():
    import pytest
    from app.core.config import Settings
    with pytest.raises(ValueError):
        Settings(app_env="production", jwt_secret_key="short", storage_encryption_key="", database_url="sqlite:///x.db")
    ok = Settings(app_env="production", jwt_secret_key="k" * 40, storage_encryption_key="x" * 44, database_url="postgresql+psycopg://u@h/db")
    assert ok.is_production


def test_storage_is_encrypted_at_rest(tmp_path):
    from cryptography.fernet import Fernet
    from app.services.storage import EncryptedStorage, LocalStorage
    s = EncryptedStorage(LocalStorage(str(tmp_path)), Fernet.generate_key())
    s.put("p/a.png", b"secret-image-bytes")
    raw = next(tmp_path.rglob("a.png")).read_bytes()
    assert b"secret-image-bytes" not in raw and s.get("p/a.png") == b"secret-image-bytes"
    # path traversal in storage keys is neutralised: the object always lands inside the storage root
    assert tmp_path.resolve() in LocalStorage(str(tmp_path))._path("../../../etc/passwd").parents
