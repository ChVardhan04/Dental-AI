"""DentEdge Perio — voice periodontal charting state machine.

Dentist voice -> speech recognition -> command recognition -> tooth/surface state machine -> measurement extraction
-> validation -> periodontal chart -> dentist confirmation -> patient report.

Teeth use FDI numbering. Each tooth has six sites: buccal pass DB, B, MB and lingual/palatal pass DL, L, ML.
"""
import copy
import re

PERIO_VERSION = "1.0.0"
UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
LOWER = [38, 37, 36, 35, 34, 33, 32, 31, 41, 42, 43, 44, 45, 46, 47, 48]
TOOTH_ORDER = [str(t) for t in UPPER + LOWER]
SITES = {"buccal": ["DB", "B", "MB"], "lingual": ["DL", "L", "ML"]}
ALL_SITES = SITES["buccal"] + SITES["lingual"]
MOLARS = {str(t) for t in (16, 17, 18, 26, 27, 28, 36, 37, 38, 46, 47, 48)}
NUM_WORDS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "ate": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
SITE_WORDS = {"distobuccal": "DB", "disto-buccal": "DB", "db": "DB", "buccal": "B", "mid buccal": "B", "mesiobuccal": "MB", "mesio-buccal": "MB", "mb": "MB",
              "distolingual": "DL", "dl": "DL", "lingual": "L", "palatal": "L", "mesiolingual": "ML", "ml": "ML", "distal": "D", "mesial": "M"}


class PerioError(ValueError):
    pass


def new_state() -> dict:
    return {"status": "ready", "pass": "buccal", "tooth_index": 0, "site_index": 0, "missing": [], "seq": 0, "snapshots": [], "last": None, "warnings": []}


def _position(state) -> dict:
    tooth = TOOTH_ORDER[state["tooth_index"]] if state["tooth_index"] < len(TOOTH_ORDER) else None
    sites = SITES[state["pass"]]
    site = sites[state["site_index"]] if tooth and state["site_index"] < len(sites) else None
    return {"tooth": tooth, "pass": state["pass"], "site": site}


def _advance_tooth(state):
    state["site_index"] = 0
    state["tooth_index"] += 1
    while state["tooth_index"] < len(TOOTH_ORDER) and TOOTH_ORDER[state["tooth_index"]] in state["missing"]:
        state["tooth_index"] += 1
    if state["tooth_index"] >= len(TOOTH_ORDER):
        if state["pass"] == "buccal":
            state["pass"] = "lingual"
            state["tooth_index"] = -1
            _advance_tooth(state)
        else:
            state["status"] = "completed"


def _words_to_numbers(text: str) -> list[int]:
    out = []
    for tok in re.findall(r"\d+|[a-z]+", text):
        if tok.isdigit():
            # "323" spoken quickly is three separate depths; two-digit values are kept (and validated) as-is
            if len(tok) > 2:
                out.extend(int(c) for c in tok)
            else:
                out.append(int(tok))
        elif tok in NUM_WORDS:
            out.append(NUM_WORDS[tok])
    return out


class PerioEngine:
    def __init__(self, state: dict | None):
        self.state = copy.deepcopy(state) if state else new_state()
        self.new: list[dict] = []
        self.removed_seqs: list[int] = []
        self.messages: list[str] = []

    # ------------------------------------------------------------------ helpers
    def _snapshot(self):
        snap = {k: copy.deepcopy(self.state[k]) for k in ("status", "pass", "tooth_index", "site_index", "missing", "last")}
        self.state["seq"] += 1
        snap["seq"] = self.state["seq"]
        self.state["snapshots"] = (self.state["snapshots"] + [snap])[-60:]
        return self.state["seq"]

    def _record(self, seq, tooth, site, kind, value):
        self.new.append({"seq": seq, "tooth": tooth, "site": site, "kind": kind, "value": float(value)})

    def _require_active(self):
        if self.state["status"] == "paused":
            raise PerioError("Charting is paused. Say 'resume' to continue.")
        if self.state["status"] == "ready":
            self.state["status"] = "in_progress"
        if self.state["status"] in ("completed", "confirmed"):
            raise PerioError("Charting is complete. Jump to a tooth to make corrections.")

    def _target_sites(self, text: str) -> list[str]:
        pos = _position(self.state)
        found = []
        for word, code in sorted(SITE_WORDS.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{re.escape(word)}\b", text):
                if code in ("D", "M"):
                    code = code + ("B" if self.state["pass"] == "buccal" else "L")
                if code not in found:
                    found.append(code)
                text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
        if re.search(r"\ball\b", text):
            last = self.state.get("last") or {}
            return last.get("sites") or SITES[self.state["pass"]]
        if found:
            return found
        last = self.state.get("last")
        if last and last.get("sites"):
            return last["sites"][-1:]
        return [pos["site"]] if pos["site"] else []

    # ------------------------------------------------------------------ main entry
    def process(self, utterance: str) -> dict:
        self.new, self.removed_seqs, self.messages = [], [], []
        text = utterance.lower().strip()
        text = re.sub(r"[,.;!?]", " ", text)
        if not text:
            raise PerioError("Empty command")
        handled = False
        for clause in [c.strip() for c in re.split(r"\bthen\b|\band then\b", text) if c.strip()]:
            handled = self._clause(clause) or handled
        if not handled:
            raise PerioError(f"Command not recognised: '{utterance[:60]}'. Try numbers like '3 2 3', 'bleeding', 'mobility 1', 'jump to 26', 'undo'.")
        return {"state": self.public_state(), "new": self.new, "removed_seqs": self.removed_seqs, "messages": self.messages}

    def _clause(self, text: str) -> bool:
        st = self.state
        if re.fullmatch(r"(start|begin)( charting)?", text):
            if st["status"] in ("ready", "paused"):
                st["status"] = "in_progress"
            self.messages.append(f"Charting started at tooth {_position(st)['tooth']} {st['pass']}.")
            return True
        if re.fullmatch(r"pause|stop|hold", text):
            st["status"] = "paused"
            self.messages.append("Charting paused.")
            return True
        if re.fullmatch(r"resume|continue|carry on", text):
            if st["status"] == "paused":
                st["status"] = "in_progress"
            p = _position(st)
            self.messages.append(f"Resumed at tooth {p['tooth']} {p['pass']} {p['site']}.")
            return True
        if re.fullmatch(r"repeat|read back|say again", text):
            p, last = _position(st), st.get("last")
            msg = f"Current position: tooth {p['tooth']} {p['pass']} {p['site'] or ''}."
            if last:
                msg += f" Last entry: {last['summary']}."
            self.messages.append(msg)
            return True
        if re.fullmatch(r"undo|scratch that|delete last|go back", text):
            if not st["snapshots"]:
                raise PerioError("Nothing to undo.")
            snap = st["snapshots"].pop()
            self.removed_seqs.append(snap["seq"])
            for k in ("status", "pass", "tooth_index", "site_index", "missing", "last"):
                st[k] = snap[k]
            self.new = [n for n in self.new if n["seq"] != snap["seq"]]
            self.messages.append(f"Undone. Back at tooth {_position(st)['tooth']} {st['pass']}.")
            return True
        if re.fullmatch(r"(complete|finish|done|end)( charting)?", text):
            st["status"] = "completed"
            self.messages.append("Charting marked complete. Review and confirm the chart.")
            return True
        m = re.search(r"\b(jump|go|move|skip)\s*(to)?\s*(tooth)?\s*(\d{2})\b(\s+(buccal|facial|lingual|palatal))?", text) or re.fullmatch(r"tooth\s+(\d{2})()()()(\s+(buccal|facial|lingual|palatal))?", text)
        if m:
            tooth = m.group(4) if m.lastindex and m.group(4) else m.group(1)
            if tooth not in TOOTH_ORDER:
                raise PerioError(f"Tooth {tooth} is not a valid adult FDI tooth number.")
            surface = m.group(6) if m.lastindex and m.lastindex >= 6 else None
            self._snapshot()
            if st["status"] in ("ready", "completed", "paused"):
                st["status"] = "in_progress"
            st["tooth_index"] = TOOTH_ORDER.index(tooth)
            st["site_index"] = 0
            if surface:
                st["pass"] = "lingual" if surface in ("lingual", "palatal") else "buccal"
            st["last"] = None
            self.messages.append(f"Moved to tooth {tooth} {st['pass']}.")
            return True
        if re.fullmatch(r"(skip|next)( tooth)?", text):
            self._require_active()
            self._snapshot()
            _advance_tooth(st)
            self.messages.append(f"Next: tooth {_position(st)['tooth']}.")
            return True
        m = re.search(r"(?:tooth\s+)?(\d{2})?\s*(is\s+)?missing", text)
        if m:
            self._require_active()
            tooth = m.group(1) or _position(st)["tooth"]
            if tooth not in TOOTH_ORDER:
                raise PerioError(f"Tooth {tooth} is not valid.")
            seq = self._snapshot()
            if tooth not in st["missing"]:
                st["missing"].append(tooth)
            self._record(seq, tooth, None, "missing", 1)
            st["last"] = {"tooth": tooth, "sites": [], "summary": f"tooth {tooth} missing"}
            if tooth == _position(st)["tooth"]:
                _advance_tooth(st)
            self.messages.append(f"Tooth {tooth} marked missing.")
            return True

        for kind, pattern, lo, hi, tooth_level in [("mobility", r"mobility|mobile", 0, 3, True), ("furcation", r"furcation|furca", 0, 3, True),
                                                   ("recession", r"recession|gingival margin", 0, 12, False)]:
            if re.search(pattern, text):
                self._require_active()
                rest = re.sub(pattern, " ", text)
                nums = _words_to_numbers(rest)
                if not nums:
                    raise PerioError(f"Say a value for {kind}, e.g. '{kind} 1'.")
                pos = _position(st)
                last = st.get("last") or {}
                tooth = last.get("tooth") or pos["tooth"]
                seq = self._snapshot()
                if tooth_level:
                    v = nums[0]
                    if not lo <= v <= hi:
                        raise PerioError(f"{kind.capitalize()} must be between {lo} and {hi}.")
                    if kind == "furcation" and tooth not in MOLARS and tooth[1] not in "45":
                        st["warnings"].append(f"Furcation recorded on tooth {tooth}, which is not a multi-rooted tooth — please verify.")
                    self._record(seq, tooth, None, kind, v)
                    summary = f"tooth {tooth} {kind} {v}"
                else:
                    sites = self._target_sites(rest) if len(nums) == 1 else SITES[st["pass"]][: len(nums)]
                    for site, v in zip(sites, nums):
                        if not lo <= v <= hi:
                            raise PerioError(f"{kind.capitalize()} must be between {lo} and {hi} mm.")
                        self._record(seq, tooth, site, kind, v)
                    summary = f"tooth {tooth} {kind} " + ", ".join(f"{s} {v}" for s, v in zip(sites, nums))
                st["last"] = {**last, "tooth": tooth, "summary": summary}
                self.messages.append(summary.capitalize() + ".")
                return True

        for kind, pattern in [("bleeding", r"bleed\w*|bop|blood"), ("plaque", r"plaque"), ("suppuration", r"suppuration|pus")]:
            if re.search(pattern, text):
                self._require_active()
                rest = re.sub(pattern, " ", text)
                pos = _position(st)
                last = st.get("last") or {}
                tooth = last.get("tooth") or pos["tooth"]
                sites = self._target_sites(rest)
                nums = _words_to_numbers(rest)
                if nums and not re.search(r"\b(on|at|site)\b", rest) and all(1 <= n <= 3 for n in nums):
                    pass_sites = SITES[st["pass"]]
                    sites = [pass_sites[n - 1] for n in nums]
                if not sites:
                    raise PerioError("No site to attach this to. Record probing depths first or name the site.")
                seq = self._snapshot()
                for s in sites:
                    self._record(seq, tooth, s, kind, 1)
                st["last"] = {**last, "tooth": tooth, "summary": f"{kind} on tooth {tooth} {', '.join(sites)}"}
                self.messages.append(f"{kind.capitalize()} recorded on tooth {tooth} {', '.join(sites)}.")
                return True

        nums = _words_to_numbers(text)
        if nums and re.fullmatch(r"[\d\s]+|(?:(?:zero|oh|one|two|to|too|three|four|for|five|six|seven|eight|ate|nine|ten|eleven|twelve|\d+)\s*)+", text):
            self._require_active()
            if len(nums) > 6:
                raise PerioError("Too many values. Dictate up to three sites at a time (e.g. '3 2 3').")
            seq = self._snapshot()
            recorded = []
            for v in nums:
                pos = _position(st)
                if not pos["tooth"]:
                    break
                if not 0 <= v <= 15:
                    raise PerioError(f"Probing depth {v} mm is outside the valid range (0-15).")
                if v >= 10:
                    st["warnings"].append(f"Tooth {pos['tooth']} {pos['site']}: {v} mm is unusually deep — please verify.")
                self._record(seq, pos["tooth"], pos["site"], "probing_depth", v)
                recorded.append((pos["tooth"], pos["site"], v))
                st["site_index"] += 1
                if st["site_index"] >= 3:
                    tooth_done = pos["tooth"]
                    _advance_tooth(st)
                    st["last"] = {"tooth": tooth_done, "sites": [r[1] for r in recorded if r[0] == tooth_done], "summary": ""}
            if recorded:
                t0 = recorded[-1][0]
                sites = [r[1] for r in recorded if r[0] == t0]
                st["last"] = {"tooth": t0, "sites": sites, "summary": f"tooth {t0} " + ", ".join(f"{r[1]} {r[2]}" for r in recorded if r[0] == t0)}
                self.messages.append("Recorded " + "; ".join(f"{t} {s} {v}" for t, s, v in recorded) + f". Next: tooth {_position(st)['tooth'] or '-'} {st['pass']}.")
            return True
        return False

    def public_state(self) -> dict:
        p = _position(self.state)
        return {"status": self.state["status"], "position": p, "missing": self.state["missing"], "last": self.state.get("last"),
                "warnings": self.state.get("warnings", [])[-10:], "can_undo": bool(self.state["snapshots"])}


def build_chart(measurements: list[dict]) -> dict:
    """Aggregate measurements into a chart (latest value wins per tooth/site/kind)."""
    teeth: dict[str, dict] = {t: {"sites": {s: {} for s in ALL_SITES}, "mobility": None, "furcation": None, "missing": False} for t in TOOTH_ORDER}
    for m in sorted(measurements, key=lambda x: (x["seq"], x.get("id", ""))):
        t = teeth.get(m["tooth"])
        if t is None:
            continue
        if m["kind"] == "missing":
            t["missing"] = True
        elif m["kind"] in ("mobility", "furcation"):
            t[m["kind"]] = m["value"]
        elif m.get("site") in t["sites"]:
            t["sites"][m["site"]][m["kind"]] = m["value"]
    depths, bop_sites, plaque_sites, total_sites = [], 0, 0, 0
    deep4, deep6 = [], []
    for tooth, t in teeth.items():
        if t["missing"]:
            continue
        for site, v in t["sites"].items():
            if "probing_depth" in v:
                total_sites += 1
                d = v["probing_depth"]
                depths.append(d)
                if d >= 4:
                    deep4.append(f"{tooth}{site}")
                if d >= 6:
                    deep6.append(f"{tooth}{site}")
            bop_sites += 1 if v.get("bleeding") else 0
            plaque_sites += 1 if v.get("plaque") else 0
    summary = {
        "sites_recorded": total_sites, "mean_probing_depth": round(sum(depths) / len(depths), 2) if depths else None,
        "sites_4mm_or_more": len(deep4), "sites_6mm_or_more": len(deep6), "deep_sites": deep4[:40],
        "bleeding_on_probing_percent": round(100 * bop_sites / total_sites, 1) if total_sites else None,
        "plaque_percent": round(100 * plaque_sites / total_sites, 1) if total_sites else None,
        "mobile_teeth": [t for t, v in teeth.items() if v["mobility"]], "furcation_teeth": [t for t, v in teeth.items() if v["furcation"]],
        "missing_teeth": [t for t, v in teeth.items() if v["missing"]],
    }
    return {"teeth": teeth, "summary": summary, "perio_version": PERIO_VERSION}


def patient_report(chart: dict) -> dict:
    s = chart["summary"]
    lines = [f"Your dentist measured the gum pockets around your teeth at {s['sites_recorded']} places."]
    if s["sites_recorded"]:
        if s["sites_4mm_or_more"]:
            lines.append(f"{s['sites_4mm_or_more']} place(s) measured 4 mm or deeper. Deeper pockets can be harder to keep clean; your dentist will explain what this means for you.")
        else:
            lines.append("No places measured 4 mm or deeper in this chart.")
        if s["bleeding_on_probing_percent"] is not None:
            lines.append(f"Bleeding was recorded at {s['bleeding_on_probing_percent']}% of measured places. Bleeding gums are worth discussing with your dentist.")
    return {"summary": " ".join(lines), "questions_for_dentist": ["What do my gum measurements mean?", "How can I improve my cleaning at home?", "When should my gums be re-measured?"],
            "note": "This report summarises measurements confirmed by your dentist. It is not a diagnosis."}
