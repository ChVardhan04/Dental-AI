"""Deterministic Clinical Rules Engine.

The rules are versioned and pure: same input -> same output. They run *after* the AI model and *before*
any language generation, and they override everything downstream.

NOTE: thresholds are engineering defaults and must be approved by DentEdge clinical governance.
"""
from app.core.config import settings
from app.services.taxonomy import PROMPT_REVIEW_TYPES, allowed_for

RULES_VERSION = "2026.09.2"

RULE_TEXT = {
    "R001": "IF image_quality fails THEN do_not_generate_finding AND request_new_image",
    "R002": "IF model version not permitted by registry THEN do_not_generate_finding",
    "R003": "IF finding_type not in approved vocabulary THEN reject finding (unsupported conclusion)",
    "R004": "IF AI_confidence < threshold THEN mark_uncertain AND require_dentist_review",
    "R005": "ALL AI findings require dentist review before entering the clinical record",
    "R006": "IF model is not production-approved THEN label research_only",
    "R007": "IF potential_emergency_signal THEN show_urgent_guidance AND do_not_continue_normal_flow",
    "R008": "IF finding type warrants prompt assessment THEN urgency = soon",
    "R009": "IF findings of same type overlap THEN merge (keep highest confidence)",
    "R010": "IF X-ray type unsupported by finding model THEN do_not_generate_finding",
}


def _iou(a, b) -> float:
    if not a or not b:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(ax, bx), max(ay, by)
    iw, ih = min(ax + aw, bx + bw) - ix, min(ay + ah, by + bh) - iy
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / float(aw * ah + bw * bh - inter)


def apply_rules(findings: list[dict], *, module: str, quality: dict | None, model_permitted: bool = True,
                research: bool = True, emergency: dict | None = None, xray_type: str | None = None,
                supported_xray_types: list[str] | None = None, threshold: float | None = None) -> dict:
    threshold = settings.confidence_threshold if threshold is None else threshold
    fired: list[str] = []
    messages: list[str] = []

    if emergency and emergency.get("emergency"):
        fired.append("R007")
        return {"allowed": False, "status": "emergency_escalation", "findings": [], "messages": [emergency.get("guidance")],
                "urgency": "urgent", "rules_fired": fired, "rules_version": RULES_VERSION, "clinical_diagnosis": False}

    if quality is not None and not quality.get("accepted"):
        fired.append("R001")
        return {"allowed": False, "status": "blocked_quality_gate", "findings": [],
                "messages": quality.get("messages") or ["No analysis was generated because the image-quality gate did not pass."],
                "urgency": "routine", "rules_fired": fired, "rules_version": RULES_VERSION, "clinical_diagnosis": False}

    if not model_permitted:
        fired.append("R002")
        return {"allowed": False, "status": "model_not_permitted", "findings": [],
                "messages": ["No findings were generated because no approved model version is enabled for this workflow."],
                "urgency": "routine", "rules_fired": fired, "rules_version": RULES_VERSION, "clinical_diagnosis": False}

    if module == "xray" and supported_xray_types is not None and xray_type not in supported_xray_types:
        fired.append("R010")
        return {"allowed": False, "status": "unsupported_xray_type", "findings": [],
                "messages": [f"Automated findings are not enabled for '{xray_type}' radiographs. A dentist can still review the image."],
                "urgency": "routine", "rules_fired": fired, "rules_version": RULES_VERSION, "clinical_diagnosis": False}

    vocab = allowed_for(module)
    kept: list[dict] = []
    for f in findings:
        if f.get("finding_type") not in vocab:
            fired.append("R003")
            messages.append("An unsupported AI output was discarded.")
            continue
        f = dict(f)
        conf = float(f.get("confidence", 0))
        if conf < threshold:
            fired.append("R004")
            f["review_status"] = "uncertain"
            f["certainty"] = "uncertain"
        else:
            f["review_status"] = "pending"
            f["certainty"] = "review_required"
        f["requires_review"] = True
        fired.append("R005")
        if research:
            f["research_only"] = True
            fired.append("R006")
        kept.append(f)

    # R009 merge overlapping duplicates
    merged: list[dict] = []
    for f in sorted(kept, key=lambda x: -float(x.get("confidence", 0))):
        dup = next((m for m in merged if m["finding_type"] == f["finding_type"] and m.get("image_asset_id") == f.get("image_asset_id")
                    and _iou(m.get("bbox"), f.get("bbox")) > 0.4), None)
        if dup:
            fired.append("R009")
            continue
        merged.append(f)

    urgency = "routine"
    if any(f["finding_type"] in PROMPT_REVIEW_TYPES for f in merged):
        urgency = "soon"
        fired.append("R008")
    if any(f.get("review_status") == "uncertain" for f in merged):
        messages.append("Some results are uncertain and have been held for professional review.")

    return {"allowed": True, "status": "review_required", "findings": merged, "messages": list(dict.fromkeys(messages)),
            "urgency": urgency, "rules_fired": sorted(set(fired)), "rules_version": RULES_VERSION, "clinical_diagnosis": False}


# Backwards compatible helper used by earlier code/tests
def validate_findings(findings: list[dict], quality: dict, module: str = "vision") -> dict:
    return apply_rules(findings, module=module, quality=quality)
