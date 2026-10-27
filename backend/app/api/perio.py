"""DentEdge Perio API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import ensure_patient_access, get_current_user, require_roles
from app.models.records import PerioChart, PerioMeasurement
from app.models.user import User, utcnow
from app.services import insight, perio as engine
from app.services.audit import log_event
from app.services.timeline import add_event

router = APIRouter(prefix="/perio", tags=["Perio charting"])


def _rows(db: Session, chart_id: str) -> list[dict]:
    return [{"id": r.id, "seq": r.seq, "tooth": r.tooth, "site": r.site, "kind": r.kind, "value": r.value}
            for r in db.query(PerioMeasurement).filter(PerioMeasurement.chart_id == chart_id).order_by(PerioMeasurement.seq.asc()).all()]


def _out(db: Session, chart: PerioChart, extra: dict | None = None, viewer: User | None = None) -> dict:
    rows = _rows(db, chart.id)
    built = engine.build_chart(rows)
    st = engine.PerioEngine(chart.state).public_state()
    out = {"id": chart.id, "patient_id": chart.patient_user_id, "dentist_id": chart.dentist_user_id, "status": chart.status,
           "state": st, "chart": built, "measurement_count": len(rows), "created_at": chart.created_at, "confirmed_at": chart.confirmed_at,
           "tooth_order": engine.TOOTH_ORDER, "sites": engine.SITES}
    if chart.status == "confirmed":
        out["patient_report"] = engine.patient_report(built)
    return {**out, **(extra or {})}


def _chart(db: Session, user: User, chart_id: str) -> PerioChart:
    chart = db.get(PerioChart, chart_id)
    if not chart:
        raise HTTPException(404, "Perio chart not found")
    ensure_patient_access(db, user, chart.patient_user_id)
    return chart


class SessionPayload(BaseModel):
    patient_id: str | None = None
    patient_user_id: str | None = None  # backwards compatibility
    measurements: list[dict] | None = None


@router.post("/session", status_code=201)
def create_session(payload: SessionPayload, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    pid = payload.patient_id or payload.patient_user_id
    if not pid:
        raise HTTPException(422, "patient_id is required")
    ensure_patient_access(db, user, pid)
    chart = PerioChart(patient_user_id=pid, dentist_user_id=user.id, status="in_progress", state=engine.new_state())
    db.add(chart)
    db.flush()
    if payload.measurements:
        _apply_structured(db, chart, payload.measurements)
    log_event(db, user.id, "perio.chart.created", "perio_chart", chart.id, actor_role=user.role, patient_id=pid)
    db.commit()
    return _out(db, chart)


class CommandPayload(BaseModel):
    session_id: str
    command: str | None = Field(default=None, max_length=500)
    measurements: list[dict] | None = None  # structured entry: [{tooth, site, kind, value}]


def _apply_structured(db: Session, chart: PerioChart, items: list[dict]):
    state = dict(chart.state or engine.new_state())
    state["seq"] = state.get("seq", 0) + 1
    seq = state["seq"]
    ranges = {"probing_depth": (0, 15), "recession": (0, 12), "mobility": (0, 3), "furcation": (0, 3), "bleeding": (0, 1), "plaque": (0, 1), "suppuration": (0, 1), "missing": (0, 1)}
    for m in items:
        tooth, kind = str(m.get("tooth", "")), str(m.get("kind", "probing_depth"))
        site = m.get("site")
        if "probing_depth_mm" in m:  # legacy payload
            kind, m = "probing_depth", {**m, "value": m["probing_depth_mm"]}
        if tooth not in engine.TOOTH_ORDER:
            raise HTTPException(422, f"Invalid tooth '{tooth}'")
        if kind not in ranges:
            raise HTTPException(422, f"Invalid measurement kind '{kind}'")
        if site is not None and site not in engine.ALL_SITES:
            site = {"B": "B", "L": "L", "M": "MB", "D": "DB"}.get(str(site))
        try:
            value = float(m.get("value", 1))
        except (TypeError, ValueError):
            raise HTTPException(422, "Measurement value must be numeric")
        lo, hi = ranges[kind]
        if not lo <= value <= hi:
            raise HTTPException(422, f"{kind} value {value} outside valid range {lo}-{hi}")
        db.add(PerioMeasurement(chart_id=chart.id, seq=seq, tooth=tooth, site=site, kind=kind, value=value))
    snaps = state.get("snapshots", [])
    snaps.append({k: state.get(k) for k in ("status", "pass", "tooth_index", "site_index", "missing", "last")} | {"seq": seq})
    state["snapshots"] = snaps[-60:]
    chart.state = state


@router.post("/measurements")
def add_measurements(payload: CommandPayload, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    chart = _chart(db, user, payload.session_id)
    if chart.status == "confirmed":
        raise HTTPException(409, "This chart has been confirmed. Start a new chart to record changes.")
    if payload.measurements:
        _apply_structured(db, chart, payload.measurements)
        db.commit()
        return _out(db, chart, {"messages": [f"{len(payload.measurements)} measurement(s) recorded."]})
    if not payload.command:
        raise HTTPException(422, "Provide a command or measurements")
    eng = engine.PerioEngine(chart.state)
    try:
        result = eng.process(payload.command)
    except engine.PerioError as exc:
        raise HTTPException(422, str(exc))
    for seq in result["removed_seqs"]:
        db.query(PerioMeasurement).filter(PerioMeasurement.chart_id == chart.id, PerioMeasurement.seq == seq).delete()
    for m in result["new"]:
        db.add(PerioMeasurement(chart_id=chart.id, seq=m["seq"], tooth=m["tooth"], site=m["site"], kind=m["kind"], value=m["value"]))
    chart.state = eng.state
    chart.status = {"paused": "paused", "completed": "completed"}.get(eng.state["status"], "in_progress")
    log_event(db, user.id, "perio.command", "perio_chart", chart.id, {"command": payload.command[:120], "recorded": len(result["new"]),
              "undone": result["removed_seqs"]}, actor_role=user.role, patient_id=chart.patient_user_id, model_name="perio-voice-parser", model_version=engine.PERIO_VERSION)
    db.commit()
    return _out(db, chart, {"messages": result["messages"]})


@router.get("/session/{session_id}")
def get_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chart = _chart(db, user, session_id)
    if user.role == "patient" and chart.status != "confirmed":
        raise HTTPException(404, "Perio chart not found")
    return _out(db, chart)


@router.post("/session/{session_id}/confirm")
def confirm(session_id: str, user: User = Depends(require_roles("dentist")), db: Session = Depends(get_db)):
    chart = _chart(db, user, session_id)
    rows = _rows(db, chart.id)
    if not any(r["kind"] == "probing_depth" for r in rows):
        raise HTTPException(422, "Record at least one probing depth before confirming")
    chart.status, chart.confirmed_at = "confirmed", utcnow()
    built = engine.build_chart(rows)
    chart.measurements = [built["summary"]]
    add_event(db, chart.patient_user_id, "perio_chart", "Periodontal chart confirmed", engine.patient_report(built)["summary"],
              ref_type="perio_chart", ref_id=chart.id, created_by=user.id)
    log_event(db, user.id, "perio.chart.confirmed", "perio_chart", chart.id, built["summary"], actor_role=user.role, patient_id=chart.patient_user_id, decision="confirm")
    insight.build_profile(db, db.get(User, chart.patient_user_id))
    db.commit()
    return _out(db, chart)


@router.get("/sessions")
def list_sessions(patient_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pid = patient_id or user.id
    ensure_patient_access(db, user, pid)
    q = db.query(PerioChart).filter(PerioChart.patient_user_id == pid)
    if user.role == "patient":
        q = q.filter(PerioChart.status == "confirmed")
    return [{"id": c.id, "status": c.status, "created_at": c.created_at, "confirmed_at": c.confirmed_at,
             "summary": engine.build_chart(_rows(db, c.id))["summary"]} for c in q.order_by(PerioChart.created_at.desc()).limit(50).all()]
