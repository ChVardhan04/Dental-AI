"""DentEdge X-Ray AI pipeline.

Upload -> file validation -> image type classification -> quality -> preprocessing -> anatomy detection ->
tooth/region localisation -> specialised finding models -> classification/localisation -> confidence ->
clinical rules -> annotation -> dentist review -> patient explanation.
"""
import cv2
import numpy as np

from app.services.taxonomy import XRAY_FINDINGS

XRAY_TYPES = ("periapical", "bitewing", "panoramic")


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb


def classify_type(gray: np.ndarray, declared: str | None = None) -> dict:
    """Geometry/intensity classifier for radiograph type (model: xray-type-classifier)."""
    h, w = gray.shape[:2]
    ratio = w / h
    scores = {
        "panoramic": float(np.clip((ratio - 1.6) / 0.6, 0, 1)),
        "bitewing": float(np.clip(1 - abs(ratio - 1.3) / 0.35, 0, 1)),
        "periapical": float(np.clip(1 - abs(ratio - 0.78) / 0.3, 0, 1) if ratio < 1 else np.clip(1 - abs(ratio - 1.3) / 0.6, 0, 0.5)),
    }
    # Panoramic images are typically very wide AND large; small wide crops are less likely panoramic.
    if w < 1200:
        scores["panoramic"] *= 0.8
    detected = max(scores, key=scores.get)
    total = sum(scores.values()) or 1.0
    confidence = round(scores[detected] / total if scores[detected] > 0 else 0.0, 3)
    if scores[detected] == 0:
        detected, confidence = "unknown", 0.0
    mismatch = bool(declared and declared not in ("other", "unknown") and declared != detected and confidence >= 0.6)
    return {"detected_type": detected, "confidence": confidence, "scores": {k: round(v, 3) for k, v in scores.items()},
            "declared_type": declared, "type_mismatch": mismatch, "aspect_ratio": round(ratio, 3),
            "warning": (f"You selected '{declared}', but this image looks like a {detected} radiograph. Please confirm the X-ray type." if mismatch else None)}


def preprocess(gray: np.ndarray) -> np.ndarray:
    """Normalise exposure, reduce noise and enhance local contrast (CLAHE)."""
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    den = cv2.fastNlMeansDenoising(norm, None, h=7, templateWindowSize=7, searchWindowSize=21) if max(gray.shape) <= 2400 else cv2.GaussianBlur(norm, (3, 3), 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(den)


def detect_anatomy(pre: np.ndarray, xray_type: str) -> dict:
    """Radiopaque dental structures via Otsu threshold + morphology (model: xray-anatomy-detector)."""
    h, w = pre.shape
    _, th = cv2.threshold(cv2.GaussianBlur(pre, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = max(3, int(min(h, w) * 0.01) | 1)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats((th > 0).astype(np.uint8), 8)
    min_area = h * w * 0.004
    structures = []
    mask = np.zeros_like(th)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area or area > h * w * 0.6:
            continue
        mask[labels == i] = 255
        cx, cy = cents[i]
        structures.append({"bbox": [int(x), int(y), int(bw), int(bh)], "area": int(area), "location": localize(cx, cy, w, h, xray_type)})
    restorations = (pre >= 250) & (mask > 0)
    rest_frac = float(restorations.sum()) / max(1, int((mask > 0).sum()))
    return {"structures": sorted(structures, key=lambda s: s["bbox"][0])[:40], "mask": mask, "structure_count": len(structures),
            "restoration_mask": (restorations.astype(np.uint8) * 255), "restoration_fraction": round(rest_frac, 4)}


def localize(cx: float, cy: float, w: int, h: int, xray_type: str) -> dict:
    """Approximate FDI region mapping. Radiographs are viewed as if facing the patient (patient's right on image left)."""
    upper = cy < h / 2
    patient_right = cx < w / 2
    if xray_type == "panoramic":
        quadrant = (1 if patient_right else 2) if upper else (4 if patient_right else 3)
        dist_from_mid = abs(cx - w / 2) / (w / 2)
        tooth_pos = min(8, max(1, int(dist_from_mid * 8) + 1))
        tooth = f"{quadrant}{tooth_pos}"
        return {"tooth": tooth, "tooth_approximate": True, "quadrant": quadrant, "region": f"{'upper' if upper else 'lower'} {'right' if patient_right else 'left'}",
                "description": f"approx. tooth {tooth} ({'upper' if upper else 'lower'} {'right' if patient_right else 'left'})"}
    third = "mesial portion" if cx < w / 3 else ("distal portion" if cx > 2 * w / 3 else "central portion")
    arch = ("upper" if upper else "lower") if xray_type == "bitewing" else "imaged"
    return {"tooth": None, "region": f"{arch} {third}", "description": f"{third} of the {arch} area" if arch != "imaged" else f"{third} of the image"}


def radiolucency_candidates(pre: np.ndarray, anatomy_mask: np.ndarray, xray_type: str) -> list[dict]:
    """Dark (radiolucent) blobs enclosed by dental structures (model: xray-radiolucency-candidate, research)."""
    h, w = pre.shape
    k = max(9, int(min(h, w) * 0.06) | 1)
    blackhat = cv2.morphologyEx(pre, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    inner = cv2.erode(anatomy_mask, np.ones((5, 5), np.uint8))
    hull = np.zeros_like(anatomy_mask)
    cnts, _ = cv2.findContours(anatomy_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        cv2.drawContours(hull, [cv2.convexHull(c)], -1, 255, -1)
    region = cv2.erode(hull, np.ones((7, 7), np.uint8))
    vals = blackhat[region > 0]
    if vals.size < 100:
        return []
    thr = max(28.0, float(np.percentile(vals, 99.3)))
    cand = ((blackhat > thr) & (region > 0)).astype(np.uint8) * 255
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(cand, 8)
    out = []
    min_area, max_area = h * w * 0.0004, h * w * 0.02
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (min_area <= area <= max_area):
            continue
        depth = float(blackhat[labels == i].mean())
        surround = float(pre[max(0, y - 5):y + bh + 5, max(0, x - 5):x + bw + 5].mean())
        contrast = depth / max(1.0, surround)
        enclosed = float((inner[labels == i] > 0).mean())
        raw = float(np.clip(0.35 + contrast * 1.4 + enclosed * 0.15, 0, 0.9))
        cx, cy = cents[i]
        pad = int(max(bw, bh) * 0.35)
        out.append({"finding_type": "radiolucent_area_for_review", "label": XRAY_FINDINGS["radiolucent_area_for_review"]["label"],
                    "raw_confidence": round(raw, 3), "bbox": [int(max(0, x - pad)), int(max(0, y - pad)), int(bw + 2 * pad), int(bh + 2 * pad)],
                    "location": localize(cx, cy, w, h, xray_type), "severity": "moderate" if area > h * w * 0.004 else "low",
                    "evidence": f"Localised area {contrast:.0%} darker than surrounding structure inside a radiopaque region.",
                    "measurements": {"area_px": int(area), "relative_darkness": round(contrast, 3), "enclosed_fraction": round(enclosed, 3)}})
    return sorted(out, key=lambda f: -f["raw_confidence"])[:4]


def restoration_findings(anatomy: dict, w: int, h: int, xray_type: str) -> list[dict]:
    if anatomy["restoration_fraction"] < 0.004:
        return []
    m = anatomy["restoration_mask"]
    n, _, stats, cents = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < h * w * 0.001:
            continue
        cx, cy = cents[i]
        out.append({"finding_type": "restoration_present", "label": XRAY_FINDINGS["restoration_present"]["label"], "raw_confidence": 0.7,
                    "bbox": [int(x), int(y), int(bw), int(bh)], "location": localize(cx, cy, w, h, xray_type), "severity": "low",
                    "evidence": "Highly radiopaque, sharply bordered area consistent with dense restorative material."})
    return sorted(out, key=lambda f: -(f["bbox"][2] * f["bbox"][3]))[:4]


def compare(prev_gray: np.ndarray, curr_gray: np.ndarray, xray_type: str) -> dict:
    """Historical comparison: anatomy alignment via ORB + RANSAC homography, then change detection."""
    a, b = preprocess(prev_gray), preprocess(curr_gray)
    target = 1000
    sb = min(1.0, target / max(b.shape))
    b_s = cv2.resize(b, (int(b.shape[1] * sb), int(b.shape[0] * sb))) if sb < 1 else b
    sa = min(1.0, target / max(a.shape))
    a_s = cv2.resize(a, (int(a.shape[1] * sa), int(a.shape[0] * sa))) if sa < 1 else a
    orb = cv2.ORB_create(3000)
    ka, da = orb.detectAndCompute(a_s, None)
    kb, db = orb.detectAndCompute(b_s, None)
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return {"alignment": {"success": False, "inliers": 0, "reason": "Not enough anatomical landmarks to align the images."}, "changes": []}
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    matches = sorted(matches, key=lambda m: m.distance)[:600]
    if len(matches) < 12:
        return {"alignment": {"success": False, "inliers": len(matches), "reason": "Images could not be matched reliably."}, "changes": []}
    src = np.float32([ka[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    inliers = int(inl.sum()) if inl is not None else 0
    ratio = inliers / max(1, len(matches))
    if Hm is None or inliers < 15 or ratio < 0.15:
        return {"alignment": {"success": False, "inliers": inliers, "inlier_ratio": round(ratio, 3), "reason": "Anatomy alignment was not reliable (different angle or region)."}, "changes": []}
    warped = cv2.warpPerspective(a_s, Hm, (b_s.shape[1], b_s.shape[0]))
    valid = cv2.warpPerspective(np.full_like(a_s, 255), Hm, (b_s.shape[1], b_s.shape[0])) > 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    # match global exposure before differencing so brightness changes are not reported as anatomy changes
    wv, bv = warped[valid].astype(np.float32), b_s[valid].astype(np.float32)
    if wv.size:
        warped = np.clip((warped.astype(np.float32) - wv.mean()) / (wv.std() + 1e-6) * bv.std() + bv.mean(), 0, 255).astype(np.uint8)
    diff = cv2.absdiff(cv2.GaussianBlur(warped, (9, 9), 0), cv2.GaussianBlur(b_s, (9, 9), 0))
    diff[~valid] = 0
    thr = max(35.0, float(np.percentile(diff[valid], 99.0))) if valid.any() else 255
    ch = cv2.morphologyEx((diff > thr).astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(ch, 8)
    H2, W2 = b_s.shape
    inv = 1.0 / sb
    changes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < H2 * W2 * 0.0008:
            continue
        mag = float(diff[labels == i].mean())
        raw = float(np.clip(0.3 + (mag - thr) / 80 + min(0.25, ratio * 0.5), 0, 0.88))
        cx, cy = cents[i]
        loc = localize(cx * inv, cy * inv, curr_gray.shape[1], curr_gray.shape[0], xray_type)
        changes.append({"finding_type": "potential_change_for_review", "label": XRAY_FINDINGS["potential_change_for_review"]["label"],
                        "raw_confidence": round(raw, 3), "bbox": [int(x * inv), int(y * inv), int(bw * inv), int(bh * inv)], "location": loc,
                        "severity": "uncertain", "evidence": f"Mean intensity difference {mag:.0f}/255 after anatomy alignment ({inliers} landmark matches)."})
    changes = sorted(changes, key=lambda c: -c["raw_confidence"])[:5]
    return {"alignment": {"success": True, "inliers": inliers, "inlier_ratio": round(ratio, 3)}, "changes": changes,
            "changed_area_fraction": round(float((ch > 0).sum()) / max(1, int(valid.sum())), 4)}
