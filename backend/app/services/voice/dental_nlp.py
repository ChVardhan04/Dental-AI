"""Dental terminology processing, symptom extraction and missing-information detection.

Deterministic and fully testable. The output is a structured complaint, e.g.
{"complaint": "tooth sensitivity", "trigger": "cold", "duration": null, "location": null, "severity": null}
"""
import re

NLP_VERSION = "1.1.0"

WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "few": 3, "couple of": 2, "a couple of": 2, "several": 4, "a few": 3}

TERMINOLOGY = [  # lay phrase -> normalised dental term
    (r"wisdom tooth|wisdom teeth", "third molar"), (r"back tooth|back teeth|molars?", "molar"), (r"front tooth|front teeth|incisors?", "incisor"),
    (r"eye tooth|canines?|fang", "canine"), (r"premolars?|bicuspids?", "premolar"), (r"gums?", "gingiva"), (r"cavity|cavities|hole in (my|the) tooth", "suspected caries (patient-reported)"),
    (r"filling", "restoration"), (r"cap\b|crown", "crown"), (r"root canal", "endodontic treatment"), (r"jaw joint|tmj|jaw clicking", "temporomandibular joint"),
    (r"canker sore|mouth ulcer|ulcer", "oral ulcer"), (r"bad breath|halitosis", "halitosis"),
]

COMPLAINTS = [
    ("tooth sensitivity", "sensitivity", r"sensitiv\w*|zing\w*|twinge\w*|sharp (pain|feeling) when"),
    ("toothache", "pain", r"tooth\s?ache|tooth (pain|hurts?)|pain\w*|hurts?|hurting|aches?|aching|sore\b|throbb\w*"),
    ("bleeding gums", "bleeding_gums", r"(gums?|gingiva)\s+(\w+\s+){0,2}bleed\w*|bleed\w*\s+(\w+\s+){0,3}(gums?|when (i )?(brush|floss))"),
    ("swelling", "swelling", r"swell\w*|swollen|puff\w*|lump"),
    ("bad breath", "bad_breath", r"bad breath|halitosis|breath smells"),
    ("loose tooth", "loose_tooth", r"loose|wobbl\w*|moving tooth"),
    ("broken or chipped tooth", "broken_tooth", r"chip\w*|crack\w*|broke\w*|fractur\w*"),
    ("jaw pain or clicking", "jaw", r"jaw\s+(\w+\s+)?(pain|hurts|click\w*|pop\w*|lock\w*)|tmj|clicking"),
    ("mouth ulcer", "ulcer", r"ulcer|canker|sore spot|blister"),
    ("tooth discoloration", "discoloration", r"stain\w*|yellow\w*|discolou?r\w*|dark spot|brown spot|black spot"),
    ("dry mouth", "dry_mouth", r"dry mouth|mouth (is|feels) dry"),
    ("food trapping", "food_trap", r"food (gets )?(stuck|trapped)"),
]

TRIGGERS = [("cold", r"\bcold\b|ice|chilled"), ("hot", r"\bhot\b|warm drink|heat"), ("sweet", r"sweet|sugar\w*|chocolate|candy"),
            ("biting/chewing", r"bit(e|ing)|chew\w*|eating"), ("pressure", r"pressure|pressing|touch\w*"), ("brushing", r"brush\w*"),
            ("flossing", r"floss\w*"), ("at night", r"at night|night\w*|sleep\w*|lying down"), ("cold air", r"cold air|breath(e|ing) in air"),
            ("acidic food", r"acid\w*|citrus|lemon|orange juice")]

CHARACTER = [("sharp", r"\bsharp\b|stabbing|shooting"), ("dull", r"\bdull\b"), ("throbbing", r"throbb\w*|pulsing|pounding"),
             ("constant", r"constant\w*|all the time|continuous\w*|non-?stop"), ("intermittent", r"comes and goes|on and off|sometimes|occasional\w*|intermittent\w*"),
             ("lingering", r"linger\w*|stays for|lasts (a )?(long|while)")]

SEVERITY_WORDS = [("severe", r"severe|unbearable|excruciating|terrible|worst|really bad|very bad|agoni\w*"),
                  ("moderate", r"moderate|quite bad|pretty bad|significant"), ("mild", r"mild|slight\w*|a little|a bit|minor")]

REQUIRED = {
    "sensitivity": ["location", "trigger", "duration", "severity"],
    "pain": ["location", "duration", "severity", "character"],
    "bleeding_gums": ["duration", "trigger"],
    "swelling": ["location", "duration", "fever"],
    "loose_tooth": ["location", "duration"],
    "broken_tooth": ["location", "pain_present"],
    "jaw": ["duration", "severity"],
    "ulcer": ["location", "duration"],
    "discoloration": ["location", "duration"],
}

QUESTIONS = {
    "location": "Which tooth or area is affected — upper or lower, left or right, front or back?",
    "trigger": "What sets it off? For example cold drinks, hot drinks, sweet food, biting or brushing?",
    "duration": "How long have you noticed this — days, weeks or months?",
    "severity": "On a scale of 0 to 10, how strong is the discomfort?",
    "character": "How would you describe it — sharp, dull, throbbing, constant or does it come and go?",
    "fever": "Do you have a fever or feel generally unwell?",
    "pain_present": "Is the tooth painful or sensitive?",
}


def normalize_terms(text: str) -> list[dict]:
    t = text.lower()
    out = []
    for pattern, term in TERMINOLOGY:
        m = re.search(r"\b(" + pattern + r")", t)
        if m:
            out.append({"phrase": m.group(1), "term": term})
    return out


def _duration(t: str) -> str | None:
    m = re.search(r"\b(\d+|a couple of|couple of|a few|few|several|an?|one|two|three|four|five|six|seven|eight|nine|ten)\s+(day|week|month|year|hour)s?\b", t)
    if m:
        n = m.group(1)
        num = int(n) if n.isdigit() else WORD_NUM.get(n, 1)
        return f"{num} {m.group(2)}{'s' if num != 1 else ''}"
    for pat, label in [(r"since yesterday|yesterday", "1 day"), (r"since last week|last week", "about 1 week"), (r"since last month|last month", "about 1 month"),
                       (r"today|this morning|tonight", "today"), (r"for (a )?(long time|while|ages)", "a long time (unspecified)"), (r"since (\w+day)", "since {0}"),
                       (r"\b(hours|days|weeks|months|years)\b", "several {0}")]:
        m = re.search(pat, t)
        if m:
            return label.format(*(g for g in m.groups() if g)) if "{0}" in label else label
    return None


def _severity(t: str) -> dict | None:
    m = re.search(r"\b(\d{1,2})\s*(out of|/|of)\s*10\b", t)
    if m and 0 <= int(m.group(1)) <= 10:
        v = int(m.group(1))
        return {"score": v, "label": "severe" if v >= 7 else "moderate" if v >= 4 else "mild"}
    for label, pat in SEVERITY_WORDS:
        if re.search(r"\b(" + pat + r")\b", t):
            return {"score": None, "label": label}
    return None


def _bare_score(t: str) -> dict | None:
    """A lone number 0-10 in a reply to the severity question, e.g. "months, 8, sharp"."""
    m = re.search(r"(?<![\d/.])\b(10|[0-9])\b(?!\s*(?:day|week|month|year|hour|min|tooth|teeth|am\b|pm\b|[:/.]\d|out of|of 10))", t)
    if not m:
        return None
    v = int(m.group(1))
    return {"score": v, "label": "severe" if v >= 7 else "moderate" if v >= 4 else "mild"}


AREAS = [("cheek", r"cheek\w*"), ("ear", r"\bears?\b"), ("neck", r"\bneck\b"), ("jaw", r"\bjaws?\b"), ("face", r"\bface\b"), ("temple", r"\btemples?\b"),
         ("head", r"\bhead\b"), ("chin", r"\bchin\b"), ("tongue", r"\btongue\b"), ("palate", r"palate|roof of (my|the) mouth"), ("lip", r"\blips?\b"),
         ("eye", r"\beyes?\b"), ("throat", r"\bthroat\b")]


def _location(t: str) -> dict | None:
    loc: dict = {}
    m = re.search(r"\btooth\s*(number|no\.?|#)?\s*(\d{2})\b", t)
    if m and m.group(2)[0] in "1234" and m.group(2)[1] in "12345678":
        loc["tooth"] = m.group(2)
    if re.search(r"\b(upper|top)\b", t):
        loc["arch"] = "upper"
    elif re.search(r"\b(lower|bottom)\b", t):
        loc["arch"] = "lower"
    if re.search(r"\bleft\b", t):
        loc["side"] = "left"
    elif re.search(r"\bright\b(?! now| away)", t):
        loc["side"] = "right"
    if re.search(r"\bfront\b|incisor", t):
        loc["position"] = "front"
    elif re.search(r"\bback\b|molar|wisdom", t):
        loc["position"] = "back"
    if re.search(r"whole mouth|all (my|the) teeth|everywhere", t):
        loc["area"] = "generalised"
    areas = [name for name, pat in AREAS if re.search(pat, t)]
    if areas:
        loc["areas"] = areas
    spread = re.findall(r"(?:to|towards|into|up to|down to|down my|up my|spreads? to|radiat\w* to)\s+(?:my\s+|the\s+)?(ear|neck|jaw|temple|head|eye|throat|shoulder|cheek)", t)
    if spread:
        loc["spreads_to"] = sorted(set(spread))
    return loc or None


def extract_symptoms(text: str) -> dict:
    t = " " + (text or "").lower() + " "
    complaints = []
    for label, key, pat in COMPLAINTS:
        if re.search(pat, t):
            complaints.append({"label": label, "key": key})
    keys = [c["key"] for c in complaints]
    # 'pain' is implied by most complaints; keep the most specific first
    if "sensitivity" in keys and "pain" in keys and not re.search(r"tooth\s?ache|throbb|constant", t):
        complaints = [c for c in complaints if c["key"] != "pain"]
        keys.remove("pain")
    triggers = [name for name, pat in TRIGGERS if re.search(pat, t)]
    character = [name for name, pat in CHARACTER if re.search(pat, t)]
    fever = None
    if re.search(r"\b(no|not|without|don'?t have)\s+(a\s+)?(fever|temperature)", t):
        fever = False
    elif re.search(r"fever|temperature|chills|feel unwell|feeling unwell", t):
        fever = True
    pain_present = True if re.search(r"pain|hurt|ache|sensitiv", t) else (False if re.search(r"no pain|doesn'?t hurt|not painful", t) else None)
    structured = {
        "complaint": complaints[0]["label"] if complaints else None,
        "complaints": [c["label"] for c in complaints],
        "complaint_keys": keys,
        "trigger": triggers[0] if len(triggers) == 1 else (triggers or None),
        "duration": _duration(t),
        "location": _location(t),
        "severity": _severity(t),
        "character": character or None,
        "fever": fever,
        "pain_present": pain_present,
        "terminology": normalize_terms(t),
        "nlp_version": NLP_VERSION,
    }
    missing = []
    for key in keys:
        for field in REQUIRED.get(key, []):
            if structured.get(field) in (None, [], {}) and field not in missing:
                missing.append(field)
    if not keys:
        missing = ["complaint"]
    structured["missing_information"] = missing
    structured["follow_up_questions"] = ([QUESTIONS[m] for m in missing if m in QUESTIONS][:3] if keys else
                                         ["Could you describe what you are noticing in your mouth — for example pain, sensitivity, bleeding or swelling?"])
    structured["complete"] = bool(keys) and not missing
    return structured


def summarize_complaint(s: dict) -> str:
    if not s.get("complaint"):
        return "No specific dental complaint identified yet."
    parts = [", ".join(s["complaints"])]
    if s.get("trigger"):
        parts.append("triggered by " + (s["trigger"] if isinstance(s["trigger"], str) else ", ".join(s["trigger"])))
    loc = s.get("location") or {}
    if loc:
        bits = [f"tooth {loc['tooth']}"] if loc.get("tooth") else [v for k, v in loc.items() if k in ("arch", "side", "position", "area")]
        if loc.get("areas"):
            bits.append("/".join(loc["areas"]))
        text = " ".join(bits)
        if loc.get("spreads_to"):
            text += (", " if text else "") + "spreading to " + " and ".join(loc["spreads_to"])
        parts.append("location: " + text)
    if s.get("duration"):
        parts.append("for " + s["duration"])
    if s.get("severity"):
        sev = s["severity"]
        parts.append(f"severity {sev['score']}/10" if sev.get("score") is not None else f"{sev['label']} severity")
    return "; ".join(parts)


CARRY_FIELDS = ("trigger", "duration", "location", "severity", "character", "fever", "pain_present")
FIELD_LABELS = {"trigger": "trigger", "duration": "how long", "location": "where", "severity": "strength", "character": "type of pain",
                "fever": "fever", "pain_present": "pain"}
MAX_ASKS = 2
MAX_QUESTIONS_PER_TURN = 2


def _describe(field: str, value) -> str:
    if field == "severity":
        return f"{value['score']}/10" if value.get("score") is not None else f"{value['label']}"
    if field == "duration":
        return f"for {value}"
    if field == "location":
        return summarize_complaint({"complaint": "x", "complaints": [], "location": value}).split("location: ", 1)[-1]
    if field == "character":
        return ", ".join(value) if isinstance(value, list) else str(value)
    if field == "trigger":
        return "triggered by " + (value if isinstance(value, str) else ", ".join(value))
    if field == "fever":
        return "fever" if value else "no fever"
    return str(value)


def continue_conversation(full_text: str, latest: str, previous: dict | None) -> dict:
    """Structure the whole conversation, using what was asked last turn to interpret short answers
    (e.g. "8" after the 0-10 question), keep earlier answers, and never repeat the same question endlessly."""
    prev = previous or {}
    s = extract_symptoms(full_text)
    latest_l = " " + (latest or "").lower() + " "
    asked_last = prev.get("asked_fields") or []
    if s.get("severity") is None and "severity" in asked_last:
        s["severity"] = _bare_score(latest_l)
    for f in CARRY_FIELDS:  # answers given earlier are kept even if this turn's parse misses them
        if s.get(f) in (None, [], {}) and prev.get(f) not in (None, [], {}):
            s[f] = prev[f]
    newly = [f for f in CARRY_FIELDS if s.get(f) not in (None, [], {}) and prev.get(f) in (None, [], {}) and previous is not None]

    counts = dict(prev.get("asked_counts") or {})
    if re.search(r"\b(not sure|don'?t know|no idea|can'?t say|unsure|not certain|dunno)\b", latest_l):
        for f in asked_last:  # an honest "not sure" counts as an answer
            counts[f] = MAX_ASKS
    keys = s["complaint_keys"]
    missing = []
    for key in keys:
        for field in REQUIRED.get(key, []):
            if s.get(field) in (None, [], {}) and field not in missing:
                missing.append(field)
    not_provided = [f for f in missing if counts.get(f, 0) >= MAX_ASKS]
    missing = [f for f in missing if f not in not_provided]
    if not keys:
        missing = ["complaint"]
    ask = [f for f in missing if f in QUESTIONS][:MAX_QUESTIONS_PER_TURN]
    for f in ask:
        counts[f] = counts.get(f, 0) + 1
    if keys:
        questions = []
        for f in ask:
            q = QUESTIONS[f]
            if counts[f] > 1:  # second time: shorter, with an easy way out
                q = REASK.get(f, q) + " (If you are not sure, just say so.)"
            questions.append(q)
    else:
        questions = ["Could you describe what you are noticing in your mouth — for example pain, sensitivity, bleeding or swelling?"]
    s["missing_information"] = missing
    s["not_provided"] = not_provided
    s["asked_fields"] = ask
    s["asked_counts"] = counts
    s["follow_up_questions"] = questions
    s["complete"] = bool(keys) and not missing
    s["summary"] = summarize_complaint(s)
    ack = ("Thanks — noted: " + "; ".join(_describe(f, s[f]) for f in newly) + ".") if newly else ""
    if s["complete"]:
        tail = ("That" if ack else "Thank you, that") + " gives your dentist a clear picture. Your summary is ready on the right."
    else:
        tail = " ".join(questions)
    s["reply"] = (ack + " " + tail).strip()
    return s


REASK = {
    "duration": "Roughly how long has this been going on — for example 3 days, 2 weeks or 6 months?",
    "severity": "Could you give it a number from 0 (no pain) to 10 (worst pain)?",
    "character": "Is the pain more sharp, dull or throbbing — and is it constant or does it come and go?",
    "location": "Which side of your mouth is it on, and is it upper or lower?",
    "trigger": "Does anything make it worse, like cold, hot, sweet food or chewing?",
    "fever": "Have you had a fever?",
    "pain_present": "Does it hurt?",
}
