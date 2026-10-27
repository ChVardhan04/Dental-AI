"""LLM Explanation Layer.

AI Findings + Patient Context + Clinical Rules + Approved Evidence -> LLM -> Structured Explanation -> Safety -> Output.
The LLM never sees raw images here and cannot change findings: it only explains the structured list it is given.
If the provider is unavailable or the output fails the safety gateway, the deterministic template is used.
"""
import json
import logging

from app.services import safety
from app.services.emergency import GUIDANCE as EMERGENCY_GUIDANCE
from app.services.knowledge import citation
from app.services.llm.providers import ProviderUnavailable, get_llm_provider
from app.services.taxonomy import patient_phrase

logger = logging.getLogger("dentedge.explainer")
PROMPT_VERSION = "explain-v1.3"

SYSTEM_PROMPT = """You are the DentEdge patient-explanation component. You explain AI-detected VISUAL observations to patients.
Hard rules:
- Only describe findings listed in FINDINGS. Never add, upgrade or remove findings.
- Never diagnose. Use non-definitive language ("may", "could be consistent with"). Say a dentist must evaluate.
- Never recommend a specific treatment, medicine or dose. Never give home procedures.
- Use only facts contained in EVIDENCE for explanations and contributing factors.
- urgency MUST equal the provided URGENCY value. requires_dentist_review MUST be true.
- Plain language, short sentences, reading age ~12.
Return JSON with keys: summary (string), observations (list of {finding_code, text}), possible_explanations (list of strings),
why_it_matters (string), recommended_next_step (string), urgency (string), limitations (list of strings),
questions_for_dentist (list of strings), warning_signs (list of strings), requires_dentist_review (true)."""

BASE_LIMITATIONS = [
    "This is an AI-assisted screening of the images provided. It is not a diagnosis.",
    "Photos and single images cannot show everything, for example areas between teeth or below the gum line.",
    "AI results can be wrong. A dentist must review these observations.",
]


def _evidence_for(ftype: str, evidence: list[dict]) -> dict | None:
    return next((e for e in evidence if ftype in (e.get("topics") or [])), None)


def template_explanation(findings: list[dict], evidence: list[dict], urgency: str, *, context: dict | None = None,
                         modality: str = "photo", blocked_messages: list[str] | None = None) -> dict:
    context = context or {}
    if urgency == "urgent":
        return {
            "summary": EMERGENCY_GUIDANCE, "observations": [], "possible_explanations": [],
            "why_it_matters": "Some symptoms need urgent professional assessment rather than an online AI review.",
            "recommended_next_step": "Contact your dentist immediately or seek emergency medical care now.",
            "urgency": "urgent", "limitations": ["The AI assessment was stopped so that you can get help first."],
            "questions_for_dentist": [], "warning_signs": ["Difficulty breathing or swallowing", "Severe facial swelling", "Bleeding that will not stop", "Significant injury to the face or teeth"],
            "requires_dentist_review": True,
        }
    if blocked_messages:
        return {
            "summary": "We could not analyse this safely. " + " ".join(blocked_messages),
            "observations": [], "possible_explanations": [], "why_it_matters": "Reliable results need clear, suitable images.",
            "recommended_next_step": "Please provide a better image, or ask your dentist to review your concern.",
            "urgency": urgency, "limitations": BASE_LIMITATIONS[:1], "questions_for_dentist": [], "warning_signs": [],
            "requires_dentist_review": True,
        }

    observations, explanations, questions, warnings, why = [], [], [], [], []
    seen_types = []
    for f in findings:
        phrase = patient_phrase(f["finding_type"])
        where = f.get("location", {}).get("description")
        conf = f.get("confidence", 0)
        certainty = "uncertain — held for dentist review" if f.get("review_status") == "uncertain" else f"AI confidence {round(conf * 100)}%"
        text = f"The image shows {phrase}" + (f" ({where})" if where else "") + f". This may need a dentist's evaluation to determine the cause ({certainty})."
        observations.append({"finding_code": f.get("finding_code"), "text": text})
        if f["finding_type"] not in seen_types:
            seen_types.append(f["finding_type"])
    for ftype in seen_types:
        doc = _evidence_for(ftype, evidence)
        if not doc:
            continue
        c = doc["content"]
        explanations.extend(f"{x} may contribute." for x in c.get("factors", [])[:3])
        why.append(c.get("why_it_matters", ""))
        questions.extend(c.get("questions", []))
        warnings.extend(c.get("warning_signs", []))

    if not findings:
        doc = _evidence_for("no_findings", evidence)
        summary = ("No visual observations were generated from the images provided. This does not mean that everything is healthy; "
                   "regular check-ups are still important.")
        if doc:
            questions.extend(doc["content"].get("questions", []))
        next_step = "Keep your regular dental check-ups and contact your dentist if you notice any symptoms."
    else:
        names = ", ".join(dict.fromkeys(patient_phrase(f["finding_type"]) for f in findings))
        summary = (f"The AI noticed {len(findings)} visual observation{'s' if len(findings) != 1 else ''} that a dentist should review: {names}. "
                   "These are observations, not a diagnosis.")
        next_step = ("Please arrange a dental appointment soon so a dentist can examine the area." if urgency == "soon"
                     else "Share these observations with your dentist at your next visit or book a check-up.")
    symptoms = context.get("symptoms")
    if symptoms:
        summary += f" You also reported: {symptoms}."

    return {
        "summary": summary, "observations": observations, "possible_explanations": list(dict.fromkeys(explanations))[:6],
        "why_it_matters": " ".join(dict.fromkeys(w for w in why if w)) or "Regular professional check-ups help catch changes early.",
        "recommended_next_step": next_step, "urgency": urgency,
        "limitations": BASE_LIMITATIONS + (["Research-stage models were used; results have not been clinically validated."] if any(f.get("research_only") for f in findings) else []),
        "questions_for_dentist": list(dict.fromkeys(questions))[:6], "warning_signs": list(dict.fromkeys(warnings))[:5],
        "requires_dentist_review": True,
    }


def explain(findings: list[dict], evidence: list[dict], urgency: str, *, context: dict | None = None, modality: str = "photo",
            blocked_messages: list[str] | None = None) -> dict:
    """Returns {explanation, provider, prompt_version, safety, citations}."""
    template = template_explanation(findings, evidence, urgency, context=context, modality=modality, blocked_messages=blocked_messages)
    types = [f["finding_type"] for f in findings]
    citations = [citation(e) for e in evidence]
    provider = get_llm_provider()
    used = "template"
    output = template
    attempted_violations: list[dict] = []

    if provider.supports_generation and not blocked_messages and urgency != "urgent":
        payload = {
            "FINDINGS": [{k: f.get(k) for k in ("finding_code", "finding_type", "label", "location", "confidence", "review_status")} for f in findings],
            "URGENCY": urgency, "PATIENT_CONTEXT": context or {},
            "EVIDENCE": [{"title": e["title"], "content": e["content"]} for e in evidence],
        }
        try:
            candidate = provider.complete_json(SYSTEM_PROMPT, json.dumps(payload, default=str))
            candidate.setdefault("requires_dentist_review", True)
            check = safety.validate_explanation(candidate, finding_types=types, expected_urgency=urgency, evidence=evidence)
            if check["passed"]:
                output, used = candidate, provider.name
            else:
                attempted_violations = check["violations"]
                logger.warning("LLM output rejected by safety gateway: %s", attempted_violations)
        except ProviderUnavailable as exc:
            logger.warning("LLM provider unavailable, using template: %s", exc)

    final_check = safety.validate_explanation(output, finding_types=types, expected_urgency=urgency, evidence=evidence)
    if not final_check["passed"] and output is not template:
        output, used = template, "template"
        final_check = safety.validate_explanation(output, finding_types=types, expected_urgency=urgency, evidence=evidence)
    return {
        "explanation": output, "provider": used, "prompt_version": PROMPT_VERSION, "citations": citations,
        "safety": {**final_check, "rejected_generation_violations": attempted_violations, "fallback_used": used == "template" and provider.supports_generation},
    }
