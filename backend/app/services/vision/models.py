"""Dental Vision models.

VisionModel
 ├── HeuristicOralVisionModel  (research: deterministic colour-space measurements)
 ├── LLMVisionModel            (research: vision-language model constrained to the finding vocabulary)
 └── OnnxVisionModel           (production slot: drop in a trained, validated detector)

All models return *raw* findings; confidence calibration and clinical rules are applied downstream.
"""
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

from app.services.image_utils import encode_png, fill_holes, soft_tissue_mask, tooth_mask, tooth_row_bbox, working_copy
from app.services.llm.providers import ProviderUnavailable, get_llm_provider
from app.services.taxonomy import PHOTO_FINDINGS

logger = logging.getLogger("dentedge.vision")


class VisionModel(ABC):
    name: str
    version: str

    @abstractmethod
    def analyze(self, rgb: np.ndarray, view: str | None) -> dict:
        """Return {"findings": [...], "regions": {...}} with bboxes in source-image pixels."""


def describe_region(cx: float, cy: float, width: int, height: int, view: str | None) -> dict:
    """Map an image position to a patient-oriented region. Patient's right appears on the image's left."""
    horiz = "patient's right" if cx < width / 3 else ("patient's left" if cx > 2 * width / 3 else "front")
    if view == "upper_teeth":
        arch = "upper"
    elif view == "lower_teeth":
        arch = "lower"
    else:
        arch = "upper" if cy < height / 2 else "lower"
    if view == "left_side":
        horiz = "patient's left side"
    elif view == "right_side":
        horiz = "patient's right side"
    region = f"{arch} {horiz}".strip()
    return {"arch": arch, "side": horiz, "region": region, "view": view, "tooth": None,
            "description": f"{region} area" + (f", {view.replace('_', ' ')} view" if view else "")}


def _components(mask: np.ndarray, min_area: int, limit: int = 3) -> list[tuple[int, int, int, int, int]]:
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    comps = [tuple(int(v) for v in stats[i]) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    return sorted(comps, key=lambda c: -c[4])[:limit]


class HeuristicOralVisionModel(VisionModel):
    name = "oral-vision-heuristic"
    version = "0.3.0"

    def analyze(self, rgb, view):
        work, scale = working_copy(rgb)
        inv = 1.0 / scale
        H, W = rgb.shape[:2]
        tmask = tooth_mask(work)
        smask = soft_tissue_mask(work)
        tooth_px = int((tmask > 0).sum())
        findings: list[dict] = []
        regions = {"tooth_pixels": tooth_px, "soft_tissue_pixels": int((smask > 0).sum())}
        if tooth_px < 500:
            return {"findings": [], "regions": regions}

        lab = cv2.cvtColor(work, cv2.COLOR_RGB2LAB).astype(np.int16)
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        teeth = tmask > 0
        median_b = float(np.median(B[teeth]))
        median_l = float(np.median(L[teeth]))
        regions.update(enamel_median_L=median_l, enamel_median_b=median_b)

        def emit(ftype, mask, raw, evidence, min_area):
            for x, y, w, h, area in _components(mask, min_area):
                cx, cy = (x + w / 2) * inv, (y + h / 2) * inv
                bbox = [int(x * inv), int(y * inv), int(w * inv), int(h * inv)]
                extent = area / max(1, tooth_px)
                severity = "high" if extent > 0.15 else ("moderate" if extent > 0.05 else "low")
                findings.append({"finding_type": ftype, "label": PHOTO_FINDINGS[ftype]["label"], "raw_confidence": round(raw, 3),
                                 "bbox": bbox, "location": describe_region(cx, cy, W, H, view), "severity": severity,
                                 "evidence": evidence, "measurements": {"area_fraction_of_teeth": round(extent, 4)}})

        # 1) Visible staining: tooth pixels distinctly darker/yellower/browner than the patient's own enamel median.
        broad_teeth = fill_holes(tmask, max(15, (work.shape[1] // 40) | 1)) > 0
        hsv = cv2.cvtColor(work, cv2.COLOR_RGB2HSV)
        stain = broad_teeth & (((B - median_b) > 14) & ((median_l - L) > 10) | ((hsv[..., 0] >= 8) & (hsv[..., 0] <= 25) & (hsv[..., 1] > 90) & (L < median_l - 25)))
        stain = cv2.morphologyEx(stain.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        stain_frac = float((stain > 0).sum()) / tooth_px
        regions["stain_fraction"] = round(stain_frac, 4)
        if stain_frac > 0.03:
            raw = min(0.92, 0.5 + stain_frac * 2.5)
            emit("visible_staining", stain, raw, f"{stain_frac:.1%} of visible tooth surface is darker/yellower than the surrounding enamel (LAB b* +14, L* -10).", max(40, tooth_px // 200))

        # 2) Possible plaque: yellow-dull deposits on the cervical band (tooth pixels touching the gum).
        gum_band = cv2.dilate(smask, np.ones((11, 11), np.uint8)) > 0
        cervical = teeth & gum_band
        cerv_px = int(cervical.sum())
        if cerv_px > 200:
            plaque = cervical & ((B - median_b) > 9) & (np.abs(L - median_l) < 35)
            plaque = cv2.morphologyEx(plaque.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            plaque_frac = float((plaque > 0).sum()) / cerv_px
            regions["cervical_yellow_fraction"] = round(plaque_frac, 4)
            if plaque_frac > 0.18:
                raw = min(0.85, 0.42 + plaque_frac)
                emit("visible_plaque", plaque, raw, f"{plaque_frac:.1%} of the tooth surface at the gum line shows yellowish, dull deposits.", max(30, cerv_px // 100))

        # 3) Visible gum changes: gingival band redness vs. typical healthy pink.
        tissue_near_teeth = (smask > 0) & (cv2.dilate(tmask, np.ones((15, 15), np.uint8)) > 0)
        gpx = int(tissue_near_teeth.sum())
        if gpx > 300:
            red = tissue_near_teeth & (A > 168) & (hsv[..., 1] > 140)
            red_frac = float(red.sum()) / gpx
            regions["gingival_red_fraction"] = round(red_frac, 4)
            if red_frac > 0.25:
                raw = min(0.8, 0.35 + red_frac * 0.6)
                emit("visible_gingival_changes", red.astype(np.uint8) * 255, raw,
                     f"{red_frac:.1%} of gum tissue next to the teeth is strongly red (LAB a* > 168).", max(60, gpx // 50))

        # 4) Visible spacing: dark gaps interrupting the tooth row (front-facing views only).
        if view in (None, "front_smile", "upper_teeth", "lower_teeth"):
            bb = tooth_row_bbox(tmask)
            if bb and bb[2] > 80:
                x, y, w, h = bb
                band = tmask[y + h // 4: y + 3 * h // 4, x:x + w] > 0
                profile = band.mean(axis=0)
                gaps, start = [], None
                for i, val in enumerate(profile):
                    if val < 0.15 and start is None:
                        start = i
                    elif val >= 0.15 and start is not None:
                        if i - start > max(6, w * 0.035) and start > w * 0.05 and i < w * 0.95:
                            gaps.append((start, i))
                        start = None
                for gs, ge in gaps[:3]:
                    gw = ge - gs
                    raw = min(0.75, 0.45 + gw / w * 3)
                    cx, cy = (x + gs + gw / 2) * inv, (y + h / 2) * inv
                    findings.append({"finding_type": "visible_spacing", "label": PHOTO_FINDINGS["visible_spacing"]["label"],
                                     "raw_confidence": round(raw, 3), "bbox": [int((x + gs) * inv), int((y + h // 4) * inv), int(gw * inv), int(h / 2 * inv)],
                                     "location": describe_region(cx, cy, W, H, view), "severity": "low",
                                     "evidence": f"A gap of ~{gw / w:.1%} of the visible tooth-row width interrupts the tooth row.",
                                     "measurements": {"gap_fraction": round(gw / w, 4)}})
        return {"findings": findings, "regions": regions}


VISION_SYSTEM = ("You are a dental photo observation model. Report ONLY clearly visible characteristics from this list: "
                 + ", ".join(PHOTO_FINDINGS) + ". Never diagnose. Return JSON {\"findings\": [{\"finding_type\", \"confidence\" (0-1), "
                 "\"bbox\" [x,y,w,h] normalised 0-1, \"region\" (e.g. 'upper front'), \"evidence\" (what is visible)}]}. "
                 "If the image is not an intraoral/smile photo or nothing is clearly visible, return {\"findings\": []}.")


class LLMVisionModel(VisionModel):
    name = "oral-vision-llm"
    version = "1.0.0"

    def analyze(self, rgb, view):
        provider = get_llm_provider()
        work, _ = working_copy(rgb, 1024)
        H, W = rgb.shape[:2]
        try:
            data = provider.vision_json(VISION_SYSTEM, f"Photo view: {view or 'unspecified'}.", encode_png(work))
        except ProviderUnavailable as exc:
            raise RuntimeError(str(exc)) from exc
        out = []
        for f in (data.get("findings") or [])[:10]:
            ftype = f.get("finding_type")
            if ftype not in PHOTO_FINDINGS:
                continue  # rules engine would also drop it; never trust free-form labels
            bb = f.get("bbox") or [0, 0, 1, 1]
            try:
                bx, by, bw, bh = [float(v) for v in bb]
            except (TypeError, ValueError):
                bx, by, bw, bh = 0, 0, 1, 1
            bbox = [int(bx * W), int(by * H), int(bw * W), int(bh * H)]
            out.append({"finding_type": ftype, "label": PHOTO_FINDINGS[ftype]["label"], "raw_confidence": float(f.get("confidence", 0.5)),
                        "bbox": bbox, "location": describe_region((bx + bw / 2) * W, (by + bh / 2) * H, W, H, view),
                        "severity": "uncertain", "evidence": str(f.get("evidence", ""))[:300]})
        return {"findings": out, "regions": {}}


class OnnxVisionModel(VisionModel):  # pragma: no cover - requires a trained model artefact
    """Production slot. Expects an ONNX detector exported with class names in a sidecar JSON file."""

    def __init__(self, path: str, name: str, version: str):
        import onnxruntime as ort  # optional dependency
        self.session = ort.InferenceSession(path)
        self.classes = json.loads(Path(path).with_suffix(".json").read_text())["classes"]
        self.name, self.version = name, version

    def analyze(self, rgb, view):
        raise NotImplementedError("Wire the trained detector's pre/post-processing here")


def get_vision_model(provider: str) -> VisionModel | None:
    if provider == "llm":
        return LLMVisionModel()
    if provider == "research":
        return HeuristicOralVisionModel()
    return None
