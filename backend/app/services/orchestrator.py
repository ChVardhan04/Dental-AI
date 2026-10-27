"""AI Orchestrator.

Coordinates specialised models and enforces the fixed processing order:
Input validation -> preprocessing -> specialised model -> structured findings -> confidence + quality ->
clinical rules -> evidence retrieval -> LLM explanation -> safety gateway -> dentist review -> patient report.
No module may bypass this sequence.
"""
import secrets
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.records import AIAnalysis, AIFinding, ImageAsset, XRayStudy
from app.models.user import User
from app.services import confidence as conf_engine
from app.services.annotation import annotate
from app.services.audit import log_event
from app.services.clinical_rules import apply_rules
from app.services.explainer import explain
from app.services.image_utils import load_rgb
from app.services.knowledge import retrieve
from app.services.model_registry import get_active
from app.services.storage import get_storage
from app.services.timeline import add_event
from app.services.vision.models import get_vision_model
from app.services.xray import pipeline as xp


class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    @contextmanager
    def step(self, name: str, **meta):
        start = time.perf_counter()
        entry = {"step": name, "status": "ok", **meta}
        try:
            yield entry
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)[:300]
            raise
        finally:
            entry["ms"] = round((time.perf_counter() - start) * 1000, 1)
            self.steps.append(entry)

    def skip(self, name: str, reason: str):
        self.steps.append({"step": name, "status": "skipped", "reason": reason, "ms": 0})


def new_finding_code() -> str:
    return "F-" + secrets.token_hex(3).upper()


def _persist_findings(db: Session, analysis: AIAnalysis, findings: list[dict], patient_id: str) -> list[AIFinding]:
    rows = []
    for f in findings:
        row = AIFinding(
            finding_code=f["finding_code"], analysis_id=analysis.id, patient_user_id=patient_id, image_asset_id=f.get("image_asset_id"),
            finding_type=f["finding_type"], label=f.get("label", ""), location=f.get("location", {}), bbox=f.get("bbox"),
            confidence=f["confidence"], raw_confidence=f.get("raw_confidence", f["confidence"]), severity=f.get("severity", "uncertain"),
            evidence=f.get("evidence", ""), model_name=f.get("model", ""), model_version=f.get("model_version", ""),
            requires_review=True, review_status=f.get("review_status", "pending"),
        )
        db.add(row)
        rows.append(row)
    return rows


def finding_out(f: AIFinding) -> dict:
    return {
        "id": f.id, "finding_id": f.finding_code, "finding_code": f.finding_code, "finding_type": f.finding_type, "label": f.label,
        "location": f.location, "bbox": f.bbox, "confidence": f.confidence, "confidence_band": conf_engine.band(f.confidence, settings.confidence_threshold),
        "severity": f.severity, "evidence": f.evidence, "model": f.model_name, "model_version": f.model_version,
        "requires_review": f.requires_review, "review_status": f.review_status, "review_note": f.review_note,
        "image_asset_id": f.image_asset_id, "analysis_id": f.analysis_id, "created_at": f.created_at,
    }


def _fuse(findings: list[dict], assets: list[ImageAsset]) -> dict:
    """Multi-image fusion: associate observations across views by finding type and mouth region."""
    views = {a.id: a.view for a in assets}
    groups: dict[tuple, dict] = {}
    for f in findings:
        loc = f.get("location", {})
        key = (f["finding_type"], loc.get("arch"), (loc.get("side") or "").replace(" side", ""))
        g = groups.setdefault(key, {"finding_type": f["finding_type"], "label": f.get("label"), "region": loc.get("region"),
                                    "finding_codes": [], "supporting_views": [], "image_ids": [], "max_confidence": 0.0})
        g["finding_codes"].append(f["finding_code"])
        if f.get("image_asset_id") not in g["image_ids"]:
            g["image_ids"].append(f.get("image_asset_id"))
            g["supporting_views"].append(views.get(f.get("image_asset_id")) or "unspecified")
        g["max_confidence"] = max(g["max_confidence"], f["confidence"])
    fused = []
    for g in groups.values():
        n = len(g["image_ids"])
        g["consistency"] = "seen in multiple views" if n > 1 else "single view"
        g["fused_confidence"] = round(min(conf_engine.RESEARCH_CONFIDENCE_CAP, g["max_confidence"] + (0.05 * (n - 1))), 3)
        fused.append(g)
    coverage = sorted({a.view or "unspecified" for a in assets})
    missing = [v for v in ("front_smile", "upper_teeth", "lower_teeth", "left_side", "right_side") if v not in coverage]
    return {"regions": sorted(fused, key=lambda g: -g["fused_confidence"]), "views_analyzed": coverage, "views_missing": missing,
            "method": "view/region association"}


def run_photo_analysis(db: Session, patient: User, requester: User, assets: list[ImageAsset], context: dict | None = None) -> AIAnalysis:
    trace = Trace()
    storage = get_storage()
    provider = settings.vision_provider
    model_name = {"llm": "oral-vision-llm", "research": "oral-vision-heuristic"}.get(provider, "")
    active = get_active(db, model_name) if model_name else None
    model = get_vision_model(provider) if active else None
    qgate = get_active(db, "dental-image-quality-gate")

    images_out, all_findings, blocked = [], [], []
    for asset in assets:
        q = asset.quality_result or {}
        with trace.step("input_validation", image=asset.id) as s:
            s["accepted"] = bool(q.get("accepted"))
            s["gate_version"] = q.get("gate_version")
        img_summary = {"image_id": asset.id, "view": asset.view, "quality": {k: q.get(k) for k in ("accepted", "status", "reason", "quality_score", "checks", "warnings")}}
        if not q.get("accepted"):
            blocked.append(asset.id)
            trace.skip("dental_vision_model", f"quality gate failed for {asset.id}")
            images_out.append({**img_summary, "status": "blocked_quality_gate", "finding_count": 0})
            continue
        if not model:
            trace.skip("dental_vision_model", "no permitted model version")
            images_out.append({**img_summary, "status": "model_not_permitted", "finding_count": 0})
            continue
        with trace.step("preprocessing", image=asset.id):
            rgb = load_rgb(storage.get(asset.storage_key))
        try:
            with trace.step("dental_vision_model", image=asset.id, model=active.name, version=active.version):
                raw = model.analyze(rgb, asset.view)
        except Exception as exc:  # failure testing: model unavailable must not crash the workflow
            images_out.append({**img_summary, "status": "model_error", "error": "The analysis model is temporarily unavailable.", "finding_count": 0})
            log_event(db, requester.id, "analysis.model_error", "image_asset", asset.id, {"error": str(exc)[:200]}, actor_role=requester.role, patient_id=patient.id)
            continue
        with trace.step("confidence_engine", image=asset.id):
            for f in raw["findings"]:
                f["confidence"] = conf_engine.calibrate(f["raw_confidence"], quality_score=q.get("quality_score", 1.0), model_metrics=active.metrics, research=active.is_research)
                f["image_asset_id"] = asset.id
                f["model"], f["model_version"] = active.name, active.version
                f["finding_code"] = new_finding_code()
        all_findings.extend(raw["findings"])
        images_out.append({**img_summary, "status": "analyzed", "finding_count": len(raw["findings"]), "measurements": raw.get("regions", {})})

    any_accepted = any(a.quality_result.get("accepted") for a in assets)
    with trace.step("clinical_rules_engine") as s:
        gate = apply_rules(all_findings, module="vision", quality={"accepted": any_accepted, "messages": _quality_messages(assets)},
                           model_permitted=bool(model), research=bool(active and active.is_research))
        s["rules_fired"] = gate["rules_fired"]
    findings = gate["findings"]

    with trace.step("multi_image_fusion"):
        fusion = _fuse(findings, assets)
    with trace.step("evidence_retrieval") as s:
        topics = list({f["finding_type"] for f in findings}) or ["no_findings"]
        evidence = retrieve(db, topics)
        s["documents"] = len(evidence)
    with trace.step("llm_explanation_and_safety") as s:
        exp = explain(findings, evidence, gate["urgency"], context=context, modality="photo",
                      blocked_messages=None if gate["allowed"] else gate["messages"])
        s["provider"], s["safety_passed"] = exp["provider"], exp["safety"]["passed"]

    status = "review_required" if gate["allowed"] else gate["status"]
    analysis = AIAnalysis(
        user_id=patient.id, requested_by=requester.id, image_asset_id=assets[0].id if assets else None, module="vision", status=status,
        model_name=active.name if active else "none", model_version=active.version if active else "", rules_version=gate["rules_version"],
        prompt_version=exp["prompt_version"], urgency=gate["urgency"], summary=exp["explanation"]["summary"][:2000],
        result_json={
            "images": images_out, "clinical_gate": {k: v for k, v in gate.items() if k != "findings"}, "fusion": fusion,
            "explanation": exp["explanation"], "explanation_provider": exp["provider"], "citations": exp["citations"], "safety": exp["safety"],
            "pipeline_trace": trace.steps, "model": {"name": active.name, "version": active.version, "deployment_status": active.deployment_status} if active else None,
            "quality_gate_version": qgate.version if qgate else None, "context": context or {},
            "disclaimer": "AI-assisted screening of visible characteristics. Not a diagnosis. Dentist review required.",
        },
    )
    db.add(analysis)
    db.flush()
    _persist_findings(db, analysis, findings, patient.id)

    # Annotation generator: one overlay per analysed image.
    annotated = {}
    with trace.step("annotation_generator"):
        for asset in assets:
            fs = [f for f in findings if f.get("image_asset_id") == asset.id]
            if not fs:
                continue
            rgb = load_rgb(storage.get(asset.storage_key))
            key = f"{patient.id}/annotated/{asset.id}-{analysis.id[:8]}.png"
            storage.put(key, annotate(rgb, fs))
            asset.annotated_storage_key = key
            annotated[asset.id] = key
    analysis.result_json = {**analysis.result_json, "pipeline_trace": trace.steps, "annotated": annotated}

    add_event(db, patient.id, "photo_analysis", "Oral photo analysis",
              f"{len(assets)} image(s) · {len(findings)} observation(s) awaiting dentist review" if gate["allowed"] else exp["explanation"]["summary"],
              ref_type="ai_analysis", ref_id=analysis.id, created_by=requester.id)
    log_event(db, requester.id, "analysis.created", "ai_analysis", analysis.id, {"module": "vision", "status": status, "image_count": len(assets),
              "finding_count": len(findings), "rules_fired": gate["rules_fired"], "safety_passed": exp["safety"]["passed"]},
              actor_role=requester.role, patient_id=patient.id, model_name=analysis.model_name, model_version=analysis.model_version)
    return analysis


def _quality_messages(assets: list[ImageAsset]) -> list[str]:
    msgs = []
    for a in assets:
        msgs.extend(a.quality_result.get("messages") or [])
    return list(dict.fromkeys(msgs)) or ["The image-quality gate did not pass."]


def run_xray_analysis(db: Session, patient: User, requester: User, asset: ImageAsset, declared_type: str | None, context: dict | None = None) -> AIAnalysis:
    trace = Trace()
    storage = get_storage()
    q = asset.quality_result or {}
    type_model = get_active(db, "xray-type-classifier")
    anatomy_model = get_active(db, "xray-anatomy-detector")
    finding_model = get_active(db, "xray-radiolucency-candidate")
    gray = None
    type_info = {"detected_type": declared_type or "unknown", "confidence": 0.0, "declared_type": declared_type}
    anatomy = None
    raw_findings: list[dict] = []
    with trace.step("file_validation") as s:
        s["accepted"] = bool(q.get("accepted"))
    if q.get("accepted"):
        gray = xp.to_gray(load_rgb(storage.get(asset.storage_key)))
        if type_model:
            with trace.step("image_type_classification", model=type_model.name, version=type_model.version):
                type_info = xp.classify_type(gray, declared_type)
        else:
            trace.skip("image_type_classification", "model not permitted")
        with trace.step("preprocessing"):
            pre = xp.preprocess(gray)
        if anatomy_model:
            with trace.step("dental_anatomy_detection", model=anatomy_model.name, version=anatomy_model.version) as s:
                anatomy = xp.detect_anatomy(pre, type_info["detected_type"])
                s["structures"] = anatomy["structure_count"]
        else:
            trace.skip("dental_anatomy_detection", "model not permitted")
        if finding_model and anatomy:
            with trace.step("specialized_finding_models", model=finding_model.name, version=finding_model.version):
                raw_findings = xp.radiolucency_candidates(pre, anatomy["mask"], type_info["detected_type"])
                for f in raw_findings:
                    f["model"], f["model_version"] = finding_model.name, finding_model.version
                for f in xp.restoration_findings(anatomy, gray.shape[1], gray.shape[0], type_info["detected_type"]):
                    f["model"], f["model_version"] = anatomy_model.name, anatomy_model.version
                    raw_findings.append(f)
        with trace.step("confidence_engine"):
            for f in raw_findings:
                f["confidence"] = conf_engine.calibrate(f["raw_confidence"], quality_score=q.get("quality_score", 1.0),
                                                        model_metrics=finding_model.metrics if finding_model else {}, research=True)
                f["image_asset_id"] = asset.id
                f["finding_code"] = new_finding_code()

    supported = (finding_model.metrics.get("supported_types") if finding_model else None)
    with trace.step("clinical_rules_engine") as s:
        gate = apply_rules(raw_findings, module="xray", quality=q, model_permitted=bool(finding_model and anatomy_model),
                           research=True, xray_type=type_info["detected_type"], supported_xray_types=supported)
        s["rules_fired"] = gate["rules_fired"]
    findings = gate["findings"]
    with trace.step("evidence_retrieval"):
        evidence = retrieve(db, list({f["finding_type"] for f in findings}) or ["no_findings"])
    with trace.step("llm_explanation_and_safety") as s:
        exp = explain(findings, evidence, gate["urgency"], context=context, modality="xray", blocked_messages=None if gate["allowed"] else gate["messages"])
        s["provider"] = exp["provider"]
        if gate["allowed"] and not findings:
            exp["explanation"]["summary"] = ("No areas were flagged for review by the research models. This does not rule out any condition; "
                                             "your dentist will review the X-ray.")

    study = XRayStudy(patient_user_id=patient.id, image_asset_id=asset.id, declared_type=declared_type or "unknown",
                      detected_type=type_info["detected_type"], type_confidence=type_info["confidence"], created_by=requester.id)
    db.add(study)
    status = "review_required" if gate["allowed"] else gate["status"]
    analysis = AIAnalysis(
        user_id=patient.id, requested_by=requester.id, image_asset_id=asset.id, module="xray", status=status,
        model_name=finding_model.name if finding_model else "none", model_version=finding_model.version if finding_model else "",
        rules_version=gate["rules_version"], prompt_version=exp["prompt_version"], urgency=gate["urgency"], summary=exp["explanation"]["summary"][:2000],
        result_json={
            "xray_type": type_info, "anatomy": {"structure_count": anatomy["structure_count"], "structures": anatomy["structures"][:20],
                                                 "restoration_fraction": anatomy["restoration_fraction"]} if anatomy else None,
            "quality": {k: q.get(k) for k in ("accepted", "status", "reason", "quality_score", "checks", "warnings")},
            "clinical_gate": {k: v for k, v in gate.items() if k != "findings"}, "explanation": exp["explanation"],
            "explanation_provider": exp["provider"], "citations": exp["citations"], "safety": exp["safety"], "pipeline_trace": trace.steps,
            "models": [m.__dict__ for m in (type_model, anatomy_model, finding_model) if m],
            "disclaimer": "Research-stage radiograph processing. Highlighted areas are for dentist review only and are not diagnoses.",
        },
    )
    db.add(analysis)
    db.flush()
    _persist_findings(db, analysis, findings, patient.id)
    if gray is not None:
        with trace.step("annotation_generator"):
            import cv2
            rgb = cv2.cvtColor(xp.preprocess(gray), cv2.COLOR_GRAY2RGB)
            key = f"{patient.id}/annotated/{asset.id}-{analysis.id[:8]}.png"
            storage.put(key, annotate(rgb, findings))
            asset.annotated_storage_key = key
        analysis.result_json = {**analysis.result_json, "pipeline_trace": trace.steps, "annotated": {asset.id: key}}
    add_event(db, patient.id, "xray_analysis", f"X-ray analysis ({type_info['detected_type']})",
              f"{len(findings)} area(s) flagged for dentist review" if gate["allowed"] else gate["messages"][0] if gate["messages"] else "",
              ref_type="ai_analysis", ref_id=analysis.id, created_by=requester.id)
    log_event(db, requester.id, "analysis.created", "ai_analysis", analysis.id, {"module": "xray", "status": status, "xray_type": type_info,
              "finding_count": len(findings), "rules_fired": gate["rules_fired"]}, actor_role=requester.role, patient_id=patient.id,
              model_name=analysis.model_name, model_version=analysis.model_version)
    return analysis


def run_xray_comparison(db: Session, patient: User, requester: User, previous: ImageAsset, current: ImageAsset) -> AIAnalysis:
    trace = Trace()
    storage = get_storage()
    model = get_active(db, "xray-comparison")
    result = {"alignment": {"success": False, "reason": "Comparison model not permitted"}, "changes": []}
    xray_type = "unknown"
    if model and previous.quality_result.get("accepted") and current.quality_result.get("accepted"):
        prev_gray = xp.to_gray(load_rgb(storage.get(previous.storage_key)))
        curr_gray = xp.to_gray(load_rgb(storage.get(current.storage_key)))
        xray_type = xp.classify_type(curr_gray, current.view)["detected_type"]
        with trace.step("anatomy_alignment_and_comparison", model=model.name, version=model.version) as s:
            result = xp.compare(prev_gray, curr_gray, xray_type)
            s["alignment"] = result["alignment"]
    for c in result["changes"]:
        c["confidence"] = conf_engine.calibrate(c["raw_confidence"], quality_score=min(previous.quality_result.get("quality_score", 1), current.quality_result.get("quality_score", 1)), research=True)
        c["image_asset_id"] = current.id
        c["model"], c["model_version"] = model.name, model.version
        c["finding_code"] = new_finding_code()
    aligned = result["alignment"].get("success")
    gate = apply_rules(result["changes"], module="xray_comparison", quality={"accepted": True}, model_permitted=bool(model), research=True)
    findings = gate["findings"] if aligned else []
    if not aligned:
        status_text = {"previous": "Not comparable", "current": "Comparison not reliable", "reason": result["alignment"].get("reason")}
    elif findings:
        top = findings[0]
        status_text = {"previous": "Baseline", "current": "Potential change detected", "region": top["location"].get("description"),
                       "ai_confidence": f"{round(top['confidence'] * 100)}%"}
    else:
        status_text = {"previous": "Baseline", "current": "No significant change detected by the research model", "region": None}
    status_text["dentist_review"] = "Required"
    status_text["note"] = "A detected difference does not by itself mean disease progression; image angle and exposure also change radiographs."
    evidence = retrieve(db, ["potential_change_for_review"])
    exp = explain(findings, evidence, gate["urgency"], modality="xray")
    analysis = AIAnalysis(
        user_id=patient.id, requested_by=requester.id, image_asset_id=current.id, module="xray_comparison",
        status="review_required" if aligned else "comparison_unreliable", model_name=model.name if model else "none",
        model_version=model.version if model else "", rules_version=gate["rules_version"], prompt_version=exp["prompt_version"],
        summary=f"Historical comparison: {status_text['current']}.",
        result_json={"previous_image_id": previous.id, "current_image_id": current.id, "xray_type": xray_type, "comparison": status_text,
                     "alignment": result["alignment"], "changed_area_fraction": result.get("changed_area_fraction"),
                     "explanation": exp["explanation"], "safety": exp["safety"], "citations": exp["citations"], "pipeline_trace": trace.steps},
    )
    db.add(analysis)
    db.flush()
    _persist_findings(db, analysis, findings, patient.id)
    if findings:
        rgb = load_rgb(storage.get(current.storage_key))
        key = f"{patient.id}/annotated/{current.id}-cmp-{analysis.id[:8]}.png"
        storage.put(key, annotate(rgb, findings))
        analysis.result_json = {**analysis.result_json, "annotated": {current.id: key}}
    add_event(db, patient.id, "xray_comparison", "X-ray historical comparison", analysis.summary, ref_type="ai_analysis", ref_id=analysis.id, created_by=requester.id)
    log_event(db, requester.id, "analysis.created", "ai_analysis", analysis.id, {"module": "xray_comparison", "aligned": aligned, "changes": len(findings)},
              actor_role=requester.role, patient_id=patient.id, model_name=analysis.model_name, model_version=analysis.model_version)
    return analysis
