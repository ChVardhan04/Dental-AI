"""Emergency escalation rule set.

Clinically-approvable, deterministic patterns. When any rule fires the normal AI flow stops and urgent
professional-care guidance is shown instead.
"""
import re

EMERGENCY_RULES_VERSION = "2026.09.1"

RULES = [
    ("difficulty_breathing", r"(difficult(y|ies)?|trouble|hard|struggl\w*|can'?t|cannot|unable to)\s+(\w+\s+){0,2}breath\w*|short(ness)? of breath|breathless", "Difficulty breathing"),
    ("difficulty_swallowing", r"(difficult(y|ies)?|trouble|hard|can'?t|cannot|unable to|pain(ful)?)\s+(\w+\s+){0,2}swallow\w*", "Difficulty swallowing"),
    ("severe_facial_swelling", r"((severe|big|large|huge|massive|bad|spreading|increasing|growing)\s+(\w+\s+){0,2}swell\w*)|(face|facial|cheek|jaw|eye|neck)\s+(\w+\s+){0,3}(swell\w*|swollen|puff\w*)|swell\w*\s+(\w+\s+){0,3}(face|facial|cheek|jaw|eye|neck)|swollen\s+(face|cheek|jaw|eye|neck)", "Facial swelling"),
    ("uncontrolled_bleeding", r"(won'?t|will not|doesn'?t|does not|can'?t|cannot|not)\s+(\w+\s+){0,2}stop\w*\s+bleed\w*|bleed\w*\s+(\w+\s+){0,3}(won'?t|will not|doesn'?t|does not|not)\s+stop|uncontroll?ed\s+bleed\w*|heavy\s+bleed\w*|bleeding\s+(a lot|heavily|profusely)", "Uncontrolled bleeding"),
    ("dental_trauma", r"knocked\s+out|tooth\s+(fell|came)\s+out\s+(after|from|in)|avuls\w*|\b(hit|struck|accident|fell (on|onto|off|down)|injur\w*|trauma|punched|crash\w*)\b.{0,40}\b(tooth|teeth|jaw|mouth|face)\b|\b(tooth|teeth|jaw|mouth|face)\b.{0,40}\b(got hit|was hit|struck|accident|injur\w*|trauma|punched)\b|broken\s+jaw", "Significant facial or dental trauma"),
    ("fever_with_swelling", r"(fever|temperature|chills).*(swell\w*|swollen)|(swell\w*|swollen).*(fever|temperature|chills)", "Fever with swelling"),
]

NEGATION = re.compile(r"\b(no|not|without|never|denies|deny|don'?t have|do not have|isn'?t|aren'?t)\b[\w\s,]{0,25}$")

GUIDANCE = ("Some of the symptoms you described may need urgent professional care. Please contact your dentist "
            "immediately or seek emergency medical care now. If you have difficulty breathing or swallowing, call your "
            "local emergency number. This assessment has been paused so you can get help first.")


def detect_emergency(text: str) -> dict:
    t = (text or "").lower()
    signals = []
    for code, pattern, label in RULES:
        for m in re.finditer(pattern, t):
            prefix = t[max(0, m.start() - 40):m.start()]
            if NEGATION.search(prefix):
                continue
            signals.append({"code": code, "label": label, "matched": m.group(0)[:80]})
            break
    return {"emergency": bool(signals), "signals": signals, "guidance": GUIDANCE if signals else None,
            "rules_version": EMERGENCY_RULES_VERSION}
