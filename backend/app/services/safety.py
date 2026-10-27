"""Safety Gateway. Every patient-facing explanation passes through here.

Detects: unsupported diagnosis, unsupported treatment recommendation, excessive certainty, hallucinated findings,
dangerous instructions, unsupported medication advice, missing escalation and contradictory information.
"""
import re

SAFETY_VERSION = "2026.09.2"

HEDGES = re.compile(r"\b(may|might|could|can|possibl\w*|potential\w*|appear\w*|seem\w*|consistent with|suggest\w*|not (a|an)? ?diagnos\w*|does not mean|doesn't mean|cannot|can't|only a dentist|your dentist will|ask your dentist|whether|if)\b")
DISEASE_TERMS = ["gingivitis", "periodontitis", "periodontal disease", "gum disease", "caries", "cavity", "cavities", "tooth decay", "decay",
                 "abscess", "infection", "infected", "cancer", "tumou?r", "cyst", "pulpitis", "oral lesion", "necrosis", "bone loss"]
DISEASE_RE = re.compile(r"\b(" + "|".join(DISEASE_TERMS) + r")\b")
ASSERTIVE = re.compile(r"\b(you (definitely |clearly |probably )?(have|have got|'ve got|are suffering from|suffer from|are diagnosed)|patient has|this is (a|an)?|there is (a|an)|it is (a|an)|shows (a|an)?|diagnosed (with|as))\b")
TREATMENT = re.compile(r"\b(you (will )?(need|require|must (have|get)|should (get|have|undergo))|requires?|recommend\w*( that you)?( get| have)?|must be)\b.{0,40}\b(root canal|extraction|extracted|filling|crown|implant|braces|aligners?|surgery|scaling|deep clean\w*|veneers?|whitening|antibiotics?)\b")
MEDICATION = re.compile(r"\b(antibiotics?|amoxicillin|penicillin|ibuprofen|paracetamol|acetaminophen|aspirin|painkillers?|analgesics?|clindamycin|metronidazole|\d+\s?mg|dosage|take (a|two|one) (pill|tablet)s?)\b")
CERTAINTY = re.compile(r"\b(definitely|certainly|undoubtedly|without (a )?doubt|100 ?%|guarantee\w*|clearly (shows|indicates|is)|it is (certain|confirmed)|is confirmed|confirms|no need to (see|visit) (a|your) dentist|nothing to worry about|completely healthy|perfectly healthy|you are healthy)\b")
DANGEROUS = re.compile(r"\b(pull (it|the tooth|your tooth)( out)? yourself|remove (it|the tooth) yourself|drain (it|the swelling)|pop (it|the)|lance|super ?glue|bleach your|hydrogen peroxide|ignore (the|this|it)|apply aspirin|put aspirin|wait and see|no need to (seek|get) (help|care))\b")
ESCALATION = re.compile(r"\b(urgent\w*|emergency|immediately|right away|straight away|as soon as possible|now)\b")

FINDING_PHRASES = {
    "visible_plaque": ["plaque"], "visible_staining": ["stain"], "apparent_discoloration": ["discolo"],
    "visible_gingival_changes": ["gum inflammation", "gingival", "gum changes", "red gums", "swollen gums"],
    "apparent_recession": ["recession", "receding"], "visible_chip": ["chip"], "visible_fracture": ["fracture", "crack", "broken tooth"],
    "visible_crowding": ["crowd"], "visible_spacing": ["spacing", "gap between", "gaps between"],
    "possible_caries": ["caries", "cavity", "cavities", "decay"], "radiolucent_area_for_review": ["radiolucen", "reduced radiodensity", "darker area"],
    "possible_periapical_radiolucency": ["periapical", "root tip"], "possible_bone_level_change": ["bone level", "bone loss"],
    "restoration_present": ["restoration", "filling", "crown"], "potential_change_for_review": ["change since", "looks different from your previous"],
}
OBSERVATION_FIELDS = ("summary", "observations")
TEXT_FIELDS = ("summary", "observations", "possible_explanations", "recommended_next_step", "limitations", "questions_for_dentist", "warning_signs", "why_it_matters")


def _texts(output: dict, fields) -> list[str]:
    out = []
    for f in fields:
        v = output.get(f)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    out.extend(str(x) for x in item.values() if isinstance(x, str))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def check_text(text: str, evidence_text: str = "") -> list[dict]:
    """Sentence-level checks usable for any generated text (explanations, SOAP notes, chat replies)."""
    violations = []
    ev = evidence_text.lower()
    for s in _sentences(text):
        low = s.lower()
        hedged = bool(HEDGES.search(low))
        m = DISEASE_RE.search(low)
        if m and ASSERTIVE.search(low) and not hedged:
            violations.append({"type": "unsupported_diagnosis", "text": s})
        elif m and m.group(1) not in ev and not re.search(r"\b(not|no|does not mean|doesn't mean)\b", low):
            violations.append({"type": "ungrounded_clinical_claim", "text": s})
        if TREATMENT.search(low) and not re.search(r"\b(discuss|ask|options?|whether|your dentist (may|can|will))\b", low):
            violations.append({"type": "unsupported_treatment_recommendation", "text": s})
        if MEDICATION.search(low):
            violations.append({"type": "unsupported_medication_advice", "text": s})
        if CERTAINTY.search(low):
            violations.append({"type": "excessive_certainty", "text": s})
        if DANGEROUS.search(low):
            violations.append({"type": "dangerous_instruction", "text": s})
    return violations


def validate_explanation(output: dict, *, finding_types: list[str], expected_urgency: str, evidence: list[dict]) -> dict:
    violations: list[dict] = []
    if not isinstance(output, dict):
        return {"passed": False, "violations": [{"type": "malformed_output", "text": "Explanation is not structured JSON"}], "version": SAFETY_VERSION}

    evidence_text = " ".join(str(e.get("content", "")) for e in evidence).lower()
    all_text = " ".join(_texts(output, TEXT_FIELDS))
    violations += check_text(all_text, evidence_text)

    # Hallucinated findings: observations must only describe findings present in structured evidence.
    obs_text = " ".join(_texts(output, OBSERVATION_FIELDS)).lower()
    present = set(finding_types)
    for ftype, phrases in FINDING_PHRASES.items():
        if ftype in present:
            continue
        # allow phrases that belong to another present finding (e.g. "stain" shared by staining/discoloration)
        if any(p in obs_text for p in phrases) and not any(p in " ".join(FINDING_PHRASES.get(x, [])) for x in present for p in phrases):
            violations.append({"type": "hallucinated_finding", "text": f"Explanation mentions '{ftype}' which is not in the structured findings"})

    if expected_urgency == "urgent" and not ESCALATION.search(all_text.lower()):
        violations.append({"type": "missing_escalation", "text": "Urgent situation without urgent-care guidance"})
    if output.get("urgency") and output.get("urgency") != expected_urgency:
        violations.append({"type": "contradictory_information", "text": f"Urgency '{output.get('urgency')}' contradicts clinical rules ('{expected_urgency}')"})
    if output.get("requires_dentist_review") is False:
        violations.append({"type": "contradictory_information", "text": "Output claims dentist review is not required"})

    # de-duplicate
    seen, unique = set(), []
    for v in violations:
        key = (v["type"], v["text"])
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return {"passed": not unique, "violations": unique, "version": SAFETY_VERSION}
