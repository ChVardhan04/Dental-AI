"""Dental AI Scribe.

Audio -> STT -> speaker identification -> dental terminology -> clinical information extraction -> SOAP draft ->
dentist review (edit / accept / reject) -> clinical record.

The scribe only records what was said. It never adds diagnoses or treatment the dentist did not state.
"""
import re

from app.services.voice.dental_nlp import extract_symptoms, normalize_terms, summarize_complaint

SCRIBE_VERSION = "1.0.0"

DENTIST_CUES = re.compile(r"\b(let me|i'?ll (check|take|have a look)|open (wide|your mouth)|probing|bleeding on probing|radiograph|x-?ray shows|we (will|'ll|should)|i (recommend|suggest|see|can see|notice)|"
                          r"caries|mesial|distal|buccal|lingual|occlusal|periapical|bitewing|restoration|composite|amalgam|prophylaxis|scaling|diagnos\w*|tooth (number )?\d{2}\b|follow[- ]up|review in)\b")
PATIENT_CUES = re.compile(r"\b(my (tooth|teeth|gum|gums|mouth|jaw)|it hurts|i feel|i'?ve (had|been)|when i (eat|drink|brush|bite)|i can'?t|is it serious|will it hurt|how much)\b")
TOOTH = re.compile(r"\b(?:tooth|#|number)\s*(\d{2})\b|\b([1-4][1-8])\s*(?:mesial|distal|buccal|lingual|occlusal|MO|DO|MOD)\b", re.I)
OBS_PATTERNS = [
    r"(probing depths? (of )?\d+.*?)(?:[.;]|$)", r"(bleeding on probing.*?)(?:[.;]|$)", r"((?:i )?(?:can )?see .*?)(?:[.;]|$)", r"(there is .*?)(?:[.;]|$)",
    r"(x-?ray shows .*?)(?:[.;]|$)", r"(radiograph shows .*?)(?:[.;]|$)", r"(mobility .*?)(?:[.;]|$)", r"(recession .*?)(?:[.;]|$)", r"(plaque .*?)(?:[.;]|$)",
    r"(swelling .*?)(?:[.;]|$)", r"(tender to .*?)(?:[.;]|$)", r"(percussion .*?)(?:[.;]|$)",
]
ASSESS_PATTERNS = [r"((?:looks like|consistent with|likely|suspect|diagnos\w*|impression is|assessment is) .*?)(?:[.;]|$)"]
PLAN_PATTERNS = [r"((?:we(?:'ll| will| should)|i(?:'ll| will)? (?:recommend|suggest)|plan is|next step|schedule|book|refer\w*|follow[- ]up|review in|come back) .*?)(?:[.;]|$)"]
MEDS = re.compile(r"\b(amoxicillin|ibuprofen|paracetamol|chlorhexidine|fluoride varnish|metronidazole|clindamycin|antibiotics?)\b", re.I)


def diarize(transcript: str, segments: list[dict] | None = None) -> list[dict]:
    """Speaker identification. Uses explicit labels when present, otherwise a cue-based classifier."""
    lines = []
    if segments:
        lines = [s.get("text", "") for s in segments if s.get("text")]
    else:
        lines = [l.strip() for l in re.split(r"\n+|(?<=[.?!])\s+(?=(?:Dentist|Doctor|Dr\.?|Patient|Pt)\s*:)", transcript) if l.strip()]
    out, prev = [], "patient"
    for line in lines:
        m = re.match(r"^\s*(dentist|doctor|dr\.?|clinician|patient|pt|parent)\s*:\s*(.*)$", line, re.I)
        if m:
            role = "dentist" if m.group(1).lower().startswith(("dent", "doc", "dr", "clin")) else "patient"
            text = m.group(2)
            method = "label"
        else:
            text = line
            d, p = len(DENTIST_CUES.findall(line.lower())), len(PATIENT_CUES.findall(line.lower()))
            role = "dentist" if d > p else "patient" if p > d else ("dentist" if prev == "patient" else "patient")
            method = "heuristic"
        if text.strip():
            out.append({"speaker": role, "text": text.strip(), "attribution": method})
            prev = role
    return out


def _collect(patterns, text):
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            s = m.group(1).strip().rstrip(",")
            if 6 < len(s) < 300 and s not in found:
                found.append(s[0].upper() + s[1:])
    return found


def build_soap(transcript: str, segments: list[dict] | None = None) -> dict:
    turns = diarize(transcript, segments)
    patient_text = " ".join(t["text"] for t in turns if t["speaker"] == "patient")
    dentist_text = " ".join(t["text"] for t in turns if t["speaker"] == "dentist")
    symptoms = extract_symptoms(patient_text or transcript)
    teeth = sorted({(m.group(1) or m.group(2)) for m in TOOTH.finditer(transcript) if (m.group(1) or m.group(2))})
    observations = _collect(OBS_PATTERNS, dentist_text)
    assessments = _collect(ASSESS_PATTERNS, dentist_text)
    plan = _collect(PLAN_PATTERNS, dentist_text)
    meds = sorted({m.group(1).lower() for m in MEDS.finditer(dentist_text)})
    referral = bool(re.search(r"\brefer\w*\b", dentist_text, re.I))
    note = {
        "subjective": {"chief_complaint": summarize_complaint(symptoms), "patient_statements": [t["text"] for t in turns if t["speaker"] == "patient"][:12],
                       "structured_symptoms": {k: symptoms.get(k) for k in ("complaints", "trigger", "duration", "location", "severity", "character", "fever")}},
        "objective": {"clinician_observations": observations, "teeth_referenced": teeth},
        "assessment": {"clinician_stated": assessments, "note": "Recorded only as stated by the clinician. The scribe does not generate diagnoses."},
        "plan": {"clinician_stated": plan, "medications_mentioned": meds, "referral_mentioned": referral},
    }
    text = render_soap(note)
    return {"turns": turns, "note": note, "note_text": text, "terminology": normalize_terms(transcript), "scribe_version": SCRIBE_VERSION,
            "status": "draft", "requires_dentist_approval": True}


def render_soap(note: dict) -> str:
    s, o, a, p = note["subjective"], note["objective"], note["assessment"], note["plan"]
    lines = ["S — Subjective", f"Chief complaint: {s['chief_complaint']}"]
    lines += [f"• {x}" for x in s["patient_statements"][:6]]
    lines += ["", "O — Objective"] + ([f"• {x}" for x in o["clinician_observations"]] or ["• No clinician observations dictated."])
    if o["teeth_referenced"]:
        lines.append(f"Teeth referenced: {', '.join(o['teeth_referenced'])}")
    lines += ["", "A — Assessment"] + ([f"• {x}" for x in a["clinician_stated"]] or ["• Not dictated — to be completed by the dentist."])
    lines += ["", "P — Plan"] + ([f"• {x}" for x in p["clinician_stated"]] or ["• Not dictated — to be completed by the dentist."])
    if p["medications_mentioned"]:
        lines.append(f"Medications mentioned by clinician: {', '.join(p['medications_mentioned'])} (verify before saving)")
    if p["referral_mentioned"]:
        lines.append("Referral mentioned — confirm referral details.")
    lines += ["", "DRAFT generated by DentEdge AI Scribe — requires dentist review and approval."]
    return "\n".join(lines)
