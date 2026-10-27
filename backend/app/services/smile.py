"""DentEdge Smile — cosmetic intelligence. Visual/cosmetic assessment only; never a medical score."""
import cv2
import numpy as np

from app.services.image_utils import soft_tissue_mask, tooth_mask, tooth_row_bbox, working_copy

SMILE_VERSION = "0.3.0"
WEIGHTS = {"symmetry": 0.22, "alignment": 0.22, "staining": 0.2, "smile_balance": 0.16, "tooth_visibility": 0.1, "gum_display": 0.1}
DISCLAIMER = "The DentEdge Smile Score is a visual, cosmetic assessment of one photo. It is not a medical score and does not assess dental health."


def _clip(v):
    return int(round(float(np.clip(v, 0, 100))))


def analyze_smile(rgb: np.ndarray) -> dict:
    work, _ = working_copy(rgb, 900)
    tm = tooth_mask(work)
    sm = soft_tissue_mask(work)
    bb = tooth_row_bbox(tm)
    if not bb or (tm > 0).sum() < 0.01 * tm.size:
        return {"status": "not_scored", "reason": "Teeth were not clearly visible. Use a front-facing, well-lit smile photo.", "metrics": {}, "overall": None}
    x, y, w, h = bb
    # mouth region: teeth bbox expanded to include surrounding soft tissue
    pad_x, pad_y = int(w * 0.15), int(h * 0.6)
    X0, Y0 = max(0, x - pad_x), max(0, y - pad_y)
    X1, Y1 = min(work.shape[1], x + w + pad_x), min(work.shape[0], y + h + pad_y)
    teeth = tm[Y0:Y1, X0:X1] > 0
    tissue = sm[Y0:Y1, X0:X1] > 0
    region = work[Y0:Y1, X0:X1]
    cols = np.where(teeth.any(axis=0))[0]
    cx = (cols.min() + cols.max()) / 2 if cols.size else teeth.shape[1] / 2

    # Symmetry: mirror IoU of the tooth mask about the tooth-row midline
    c = int(round(cx))
    half = min(c, teeth.shape[1] - c)
    left = teeth[:, c - half:c]
    right = np.fliplr(teeth[:, c:c + half])
    inter, union = (left & right).sum(), (left | right).sum()
    symmetry = _clip(100 * (inter / union if union else 0) ** 0.7)

    # Alignment: smoothness of the incisal edge (lower boundary of the upper tooth row)
    edges = []
    for col in range(teeth.shape[1]):
        rows = np.where(teeth[:, col])[0]
        if rows.size:
            edges.append(rows.max())
    if len(edges) > 10:
        e = np.array(edges, dtype=float)
        fit = np.polyval(np.polyfit(np.arange(len(e)), e, 2), np.arange(len(e)))
        rough = float(np.abs(e - fit).mean()) / max(1.0, h)
        alignment = _clip(100 - rough * 900)
    else:
        alignment = 50

    # Staining: enamel yellowness / darkness (LAB)
    lab = cv2.cvtColor(region, cv2.COLOR_RGB2LAB).astype(float)
    b_mean = float(lab[..., 2][teeth].mean())
    l_mean = float(lab[..., 0][teeth].mean())
    yellow = max(0.0, b_mean - 128)
    staining = _clip(100 - yellow * 3.2 - max(0.0, 200 - l_mean) * 0.35)

    # Tooth visibility: share of the mouth opening occupied by teeth
    mouth_area = (teeth | tissue).sum()
    vis_ratio = teeth.sum() / mouth_area if mouth_area else 0
    tooth_visibility = _clip(100 - abs(vis_ratio - 0.65) * 180)

    # Gum display: gum pixels directly above the upper teeth relative to tooth height (ideal small)
    above = tissue[: max(1, y - Y0), :]
    gum_ratio = above.sum() / max(1, teeth.sum())
    gum_display = _clip(100 - max(0.0, gum_ratio - 0.15) * 160)

    # Smile balance: tooth-row centre vs mouth-region centre and width ratio
    centre_offset = abs(cx - teeth.shape[1] / 2) / max(1, teeth.shape[1])
    smile_balance = _clip(100 - centre_offset * 250 - abs(w / max(1, h) - 3.0) * 6)

    metrics = {"symmetry": symmetry, "alignment": alignment, "staining": staining, "tooth_visibility": tooth_visibility,
               "gum_display": gum_display, "smile_balance": smile_balance}
    overall = _clip(sum(metrics[k] * wgt for k, wgt in WEIGHTS.items()))
    return {
        "status": "scored", "overall": overall, "metrics": metrics, "weights": WEIGHTS,
        "measurements": {"enamel_b_mean": round(b_mean, 1), "enamel_l_mean": round(l_mean, 1), "tooth_to_mouth_ratio": round(float(vis_ratio), 3),
                         "gum_to_tooth_ratio": round(float(gum_ratio), 3)},
        "descriptions": {
            "symmetry": "How evenly the visible teeth mirror each other across the midline.",
            "alignment": "How smooth and even the biting edges of the visible teeth appear.",
            "staining": "Visible colour brightness of the teeth (higher = fewer visible stains).",
            "tooth_visibility": "How much of the smile opening is occupied by teeth.",
            "gum_display": "How much gum shows above the teeth when smiling (higher = less gum display).",
            "smile_balance": "Overall left-right balance and proportions of the smile.",
        },
        "disclaimer": DISCLAIMER, "version": SMILE_VERSION,
    }


def compare_scores(previous: dict | None, current: dict) -> dict | None:
    if not previous or not previous.get("metrics") or current.get("overall") is None:
        return None
    return {"overall_change": current["overall"] - (previous.get("overall") or 0),
            "metric_changes": {k: current["metrics"][k] - previous["metrics"].get(k, 0) for k in current["metrics"]},
            "note": "Changes can reflect different lighting, angle or expression as well as cosmetic changes."}
