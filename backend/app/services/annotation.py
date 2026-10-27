"""Annotation Generator: Original -> AI analysis -> detected regions -> overlay for dentist review."""
import cv2
import numpy as np

from app.services.image_utils import encode_png

COLORS = {
    "uncertain": (245, 158, 11), "pending": (14, 165, 233), "confirm": (16, 185, 129), "reject": (148, 163, 184),
    "edit": (139, 92, 246), "further_evaluation": (239, 68, 68),
}


def annotate(rgb: np.ndarray, findings: list[dict], *, grayscale: bool = False) -> bytes:
    img = rgb.copy()
    if grayscale and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    h, w = img.shape[:2]
    thick = max(2, int(round(max(h, w) / 400)))
    font = max(0.45, max(h, w) / 1600)
    overlay = img.copy()
    for f in findings:
        bbox = f.get("bbox")
        if not bbox:
            continue
        x, y, bw, bh = [int(v) for v in bbox]
        color = COLORS.get(f.get("review_status", "pending"), COLORS["pending"])
        cv2.rectangle(overlay, (x, y), (x + bw, y + bh), color, -1)
        cv2.rectangle(img, (x, y), (x + bw, y + bh), color, thick)
        label = f"{f.get('finding_code', '')} {round(float(f.get('confidence', 0)) * 100)}%"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, 1)
        ty = max(th + 4, y - 4)
        cv2.rectangle(img, (x, ty - th - 4), (x + tw + 6, ty + 2), color, -1)
        cv2.putText(img, label, (x + 3, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, font, (255, 255, 255), 1, cv2.LINE_AA)
    img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)
    cv2.putText(img, "AI-assisted annotation - dentist review required", (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, font * 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "AI-assisted annotation - dentist review required", (8, h - 10), cv2.FONT_HERSHEY_SIMPLEX, font * 0.9, (20, 40, 40), 1, cv2.LINE_AA)
    return encode_png(img)
