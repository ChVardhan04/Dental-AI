"""AI monitoring and model drift detection.

Drift never triggers automatic retraining or deployment: it raises an alert for investigation.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.records import AIAnalysis, AIFinding, AIModel, AIModelVersion, ClinicalReview, ImageAsset
from app.models.user import utcnow

DRIFT_FEATURES = ("brightness_mean", "blur_score", "contrast_std")


def ai_metrics(db: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    since_naive = since.replace(tzinfo=None)

    def recent(q, col):
        try:
            return q.filter(col >= since).all()
        except Exception:
            return q.filter(col >= since_naive).all()

    findings = recent(db.query(AIFinding), AIFinding.created_at)
    analyses = recent(db.query(AIAnalysis), AIAnalysis.created_at)
    images = recent(db.query(ImageAsset), ImageAsset.created_at)
    reviews = recent(db.query(ClinicalReview), ClinicalReview.created_at)

    buckets = Counter()
    for f in findings:
        buckets[min(9, int(f.confidence * 10))] += 1
    conf_dist = [{"range": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "count": buckets.get(i, 0)} for i in range(10)]

    rejected = [i for i in images if not (i.quality_result or {}).get("accepted")]
    reasons = Counter()
    for i in rejected:
        q = i.quality_result or {}
        for k, v in (q.get("checks") or {}).items():
            if v is False:
                reasons[k] += 1

    decisions = Counter(r.decision for r in reviews)
    overrides = decisions.get("reject", 0) + decisions.get("edit", 0)
    by_version = defaultdict(lambda: {"findings": 0, "reviewed": 0, "confirmed": 0, "rejected": 0, "edited": 0, "avg_confidence": 0.0})
    for f in findings:
        v = by_version[f"{f.model_name}@{f.model_version}"]
        v["findings"] += 1
        v["avg_confidence"] += f.confidence
        if f.reviewer_id:
            v["reviewed"] += 1
            v["confirmed"] += f.review_status == "confirm"
            v["rejected"] += f.review_status == "reject"
            v["edited"] += f.review_status == "edit"
    for v in by_version.values():
        v["avg_confidence"] = round(v["avg_confidence"] / v["findings"], 3) if v["findings"] else 0
        v["false_positive_feedback_rate"] = round(v["rejected"] / v["reviewed"], 3) if v["reviewed"] else None
        v["dentist_override_rate"] = round((v["rejected"] + v["edited"]) / v["reviewed"], 3) if v["reviewed"] else None

    status_counts = Counter(a.status for a in analyses)
    return {
        "window_days": days, "analyses": len(analyses), "analyses_by_status": dict(status_counts),
        "analyses_by_module": dict(Counter(a.module for a in analyses)), "images_uploaded": len(images),
        "quality_rejection_rate": round(len(rejected) / len(images), 3) if images else None, "quality_rejection_reasons": dict(reasons),
        "confidence_distribution": conf_dist, "uncertain_rate": round(sum(1 for f in findings if f.review_status == "uncertain" or f.confidence < 0.6) / len(findings), 3) if findings else None,
        "reviews": len(reviews), "review_decisions": dict(decisions),
        "dentist_override_rate": round(overrides / len(reviews), 3) if reviews else None,
        "false_negative_feedback": decisions.get("further_evaluation", 0),
        "pending_reviews": db.query(AIFinding).filter(AIFinding.review_status.in_(["pending", "uncertain"])).count(),
        "model_version_performance": dict(by_version),
        "emergency_escalations": status_counts.get("emergency_escalation", 0),
    }


def _psi_like(values: list[float], ref: dict) -> float:
    """Standardised mean shift (z) between production values and the reference distribution."""
    if not values or not ref or not ref.get("std"):
        return 0.0
    mean = sum(values) / len(values)
    return round(abs(mean - ref["mean"]) / ref["std"], 3)


def drift_report(db: Session, days: int = 30, threshold: float = 1.0) -> dict:
    since = (utcnow() - timedelta(days=days)).replace(tzinfo=None)
    out = []
    for model in db.query(AIModel).all():
        versions = db.query(AIModelVersion).filter(AIModelVersion.model_id == model.id, AIModelVersion.deployment_status.in_(["production", "staging", "research"])).all()
        for v in versions:
            ref = v.reference_stats or {}
            if not ref:
                continue
            kind = "xray" if model.modality == "xray" else ("oral_photo", "smile")
            q = db.query(ImageAsset).filter(ImageAsset.image_kind.in_([kind] if isinstance(kind, str) else list(kind)))
            try:
                imgs = q.filter(ImageAsset.created_at >= since).all()
            except Exception:
                imgs = q.all()
            imgs = [i for i in imgs if (i.quality_result or {}).get("metrics")]
            feats = {}
            for f in DRIFT_FEATURES:
                vals = [float(i.quality_result["metrics"][f]) for i in imgs if f in i.quality_result["metrics"]]
                score = _psi_like(vals, ref.get(f, {}))
                feats[f] = {"production_mean": round(sum(vals) / len(vals), 2) if vals else None, "reference_mean": ref.get(f, {}).get("mean"), "shift_z": score,
                            "drift": score > threshold}
            drifted = [k for k, val in feats.items() if val["drift"]]
            out.append({"model": model.name, "version": v.version, "deployment_status": v.deployment_status, "samples": len(imgs), "features": feats,
                        "drift_detected": bool(drifted) and len(imgs) >= 20, "insufficient_data": len(imgs) < 20,
                        "action": ("Alert: investigate input distribution, expand dataset, retrain and validate before controlled deployment. Never auto-retrain."
                                   if drifted and len(imgs) >= 20 else "No action")})
    return {"window_days": days, "threshold_z": threshold, "models": out}
