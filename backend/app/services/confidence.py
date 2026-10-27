"""Confidence Engine. Converts raw model scores into calibrated, quality-aware confidence."""
import math

RESEARCH_CONFIDENCE_CAP = 0.85


def calibrate(raw: float, *, quality_score: float = 1.0, model_metrics: dict | None = None, research: bool = True) -> float:
    raw = min(1.0, max(0.0, float(raw)))
    cal = (model_metrics or {}).get("calibration")
    if cal and {"a", "b"} <= set(cal):  # Platt scaling parameters from validation data
        logit = math.log(max(raw, 1e-6) / max(1 - raw, 1e-6))
        raw = 1 / (1 + math.exp(-(cal["a"] * logit + cal["b"])))
    adjusted = raw * (0.6 + 0.4 * min(1.0, max(0.0, quality_score)))
    if research:
        adjusted = min(adjusted, RESEARCH_CONFIDENCE_CAP)
    return round(adjusted, 3)


def band(confidence: float, threshold: float = 0.6) -> str:
    if confidence < threshold:
        return "low"
    if confidence < 0.8:
        return "moderate"
    return "high"
