"""Mandatory Image Quality Gate.

Image -> is it an image? -> is it a dental image? -> resolution -> lighting -> blur -> teeth visible
-> relevant area visible -> YES analyze / NO request a better image.
"""
import cv2
import numpy as np

from app.core.config import settings
from app.services.image_utils import (
    ImageDecodeError, decode_and_sanitize, is_grayscale, sniff_mime, soft_tissue_mask, tooth_mask, tooth_row_bbox, working_copy,
)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
QUALITY_GATE_VERSION = "1.2.0"

PHOTO_VIEWS = {"front_smile", "upper_teeth", "lower_teeth", "left_side", "right_side", "close_up", "problem_area"}
XRAY_TYPES = {"periapical", "bitewing", "panoramic", "other", "unknown"}
GUM_VIEWS = {"front_smile", "upper_teeth", "lower_teeth", "left_side", "right_side"}


def _reject(reason: str, checks: dict, status: str = "rejected") -> dict:
    return {"accepted": False, "status": status, "reason": reason, "messages": [reason], "checks": checks,
            "dental_image_verified": False, "gate_version": QUALITY_GATE_VERSION}


def image_stats(gray: np.ndarray) -> dict:
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {
        "brightness_mean": round(float(gray.mean()), 2),
        "contrast_std": round(float(gray.std()), 2),
        "blur_score": round(lap, 2),
        "clipped_dark": round(float((gray < 12).mean()), 4),
        "clipped_bright": round(float((gray > 245).mean()), 4),
    }


def _screenshot_likelihood(rgb: np.ndarray) -> float:
    small = rgb[::4, ::4].reshape(-1, 3)
    unique_ratio = len(np.unique(small, axis=0)) / max(1, len(small))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    flat = float((cv2.Laplacian(gray, cv2.CV_64F) == 0).mean())
    return round(min(1.0, max(0.0, (flat - 0.55) * 2.2) + max(0.0, 0.05 - unique_ratio) * 8), 3)


def assess_image(data: bytes, content_type: str, *, image_kind: str = "oral_photo", view: str | None = None) -> dict:
    """Returns the gate result. When accepted, `sanitized` holds metadata-free PNG bytes to store."""
    declared = (content_type or "").split(";")[0].strip().lower()
    sniffed = sniff_mime(data)
    if declared not in ALLOWED_MIME or sniffed is None:
        return _reject("Unsupported file type. Upload a JPEG, PNG or WebP image.", {"is_image": False})
    if sniffed != declared and not (declared == "image/jpeg" and sniffed == "image/jpeg"):
        return _reject("The file contents do not match its declared image type.", {"is_image": False, "type_mismatch": True})
    try:
        rgb, sanitized, info = decode_and_sanitize(data)
    except ImageDecodeError as exc:
        return _reject(str(exc), {"is_image": False, "decode": False})

    height, width = rgb.shape[:2]
    work, _ = working_copy(rgb)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY)
    stats = image_stats(gray)
    total = gray.size
    checks: dict[str, bool] = {"is_image": True}
    messages: list[str] = []
    detected_modality = "radiograph" if is_grayscale(work) else "photograph"
    metrics = {**stats, "width": width, "height": height, **info}

    # --- Is it the right kind of dental image? -------------------------------------------------
    if image_kind == "xray":
        checks["dental_image"] = detected_modality == "radiograph" and stats["contrast_std"] > 18
        if detected_modality != "radiograph":
            messages.append("This looks like a colour photograph, not a dental X-ray. Please upload the radiograph image.")
        elif not checks["dental_image"]:
            messages.append("The image has too little contrast to be a usable radiograph.")
        teeth_fraction = float((gray > np.percentile(gray, 80)).mean())
        checks["anatomy_visible"] = stats["contrast_std"] > 25
        if checks["dental_image"] and not checks["anatomy_visible"]:
            messages.append("Dental anatomy is not clearly visible. Upload the original radiograph without cropping or heavy compression.")
        metrics["radiopaque_fraction"] = round(teeth_fraction, 4)
        min_w, min_h = 400, 300
    else:
        tmask = tooth_mask(work)
        smask = soft_tissue_mask(work)
        tooth_frac = float((tmask > 0).sum() / total)
        tissue_frac = float((smask > 0).sum() / total)
        adjacency = cv2.dilate(smask, np.ones((9, 9), np.uint8))
        contact = float(((adjacency > 0) & (tmask > 0)).sum() / max(1, (tmask > 0).sum()))
        bbox = tooth_row_bbox(tmask)
        coverage = (bbox[2] * bbox[3]) / total if bbox else 0.0
        metrics.update(tooth_fraction=round(tooth_frac, 4), soft_tissue_fraction=round(tissue_frac, 4),
                       tooth_tissue_contact=round(contact, 4), tooth_region_coverage=round(coverage, 4))
        if detected_modality == "radiograph":
            checks["dental_image"] = False
            messages.append("This looks like an X-ray. Please use the X-ray workflow for radiographs.")
        else:
            checks["dental_image"] = tooth_frac > 0.012 and tissue_frac > 0.02 and contact > 0.04
            if not checks["dental_image"]:
                messages.append("We could not detect teeth and gums in this image. Please upload a photo of your mouth.")
        checks["teeth_visible"] = tooth_frac > 0.02
        if checks["dental_image"] and not checks["teeth_visible"]:
            messages.append("Teeth are not clearly visible. Please open your mouth or move closer.")
        min_cov = 0.12 if view in {"close_up", "problem_area"} else 0.04
        checks["relevant_area_visible"] = coverage >= min_cov
        if checks["dental_image"] and not checks["relevant_area_visible"]:
            messages.append("Please provide a closer image of the affected tooth." if view in {"close_up", "problem_area"} else "The teeth occupy too little of the frame. Please move the camera closer.")
        if view in GUM_VIEWS:
            checks["gums_visible"] = tissue_frac > 0.03
            if checks["dental_image"] and not checks["gums_visible"]:
                messages.append("The image does not provide enough visibility of the gums.")
        min_w, min_h = settings.quality_min_width, settings.quality_min_height

    checks["minimum_resolution"] = width >= min_w and height >= min_h and min(width, height) >= 200
    if not checks["minimum_resolution"]:
        messages.append(f"Resolution is too low ({width}x{height}). Please upload a larger image (at least {min_w}x{min_h}).")
    if image_kind == "xray":
        checks["lighting"] = 20 <= stats["brightness_mean"] <= 235 and stats["clipped_bright"] < 0.5
    else:
        checks["lighting"] = 40 <= stats["brightness_mean"] <= 225 and stats["clipped_dark"] < 0.45 and stats["clipped_bright"] < 0.3
    if not checks["lighting"]:
        messages.append("Lighting is too dark or overexposed. Please retake the image in bright, even light.")
    blur_threshold = 15 if image_kind == "xray" else 35
    checks["sharpness"] = stats["blur_score"] >= blur_threshold
    if not checks["sharpness"]:
        messages.append("The image is too blurry to analyze reliably. Hold the camera steady and retake it.")

    screenshot = _screenshot_likelihood(work)
    metrics["screenshot_likelihood"] = screenshot
    warnings = []
    if screenshot > 0.6:
        warnings.append("This image may be a screenshot or edited graphic. Original camera images give more reliable results.")
    if info.get("frames", 1) > 1:
        warnings.append("Animated or multi-frame image detected; only the first frame was used.")

    accepted = all(checks.values())
    seen, unique = set(), []
    for m in messages:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    result = {
        "accepted": accepted,
        "status": "passed" if accepted else ("not_dental" if not checks.get("dental_image", True) else "needs_better_image"),
        "reason": "Image quality checks passed." if accepted else " ".join(unique),
        "messages": unique,
        "warnings": warnings,
        "checks": checks,
        "metrics": metrics,
        "width": width,
        "height": height,
        "detected_modality": detected_modality,
        "dental_image_verified": bool(checks.get("dental_image")),
        "quality_score": round(_quality_score(stats, checks, image_kind), 3),
        "gate_version": QUALITY_GATE_VERSION,
    }
    result["sanitized"] = sanitized
    return result


def _quality_score(stats: dict, checks: dict, kind: str) -> float:
    """0..1 score used by the confidence engine to down-weight marginal images."""
    blur_ref = 60 if kind == "xray" else 150
    sharp = min(1.0, stats["blur_score"] / blur_ref)
    b = stats["brightness_mean"]
    light = 1.0 - min(1.0, abs(b - 130) / 130)
    passed = sum(1 for v in checks.values() if v) / max(1, len(checks))
    return 0.45 * sharp + 0.25 * light + 0.30 * passed
