"""Clinical audit trail. Every important AI / clinical event is recorded."""
from sqlalchemy.orm import Session

from app.core.middleware import client_ip_var, request_id_var
from app.models.records import AuditLog


def log_event(db: Session, actor_id: str | None, action: str, resource_type: str, resource_id: str | None = None,
              details: dict | None = None, *, actor_role: str | None = None, patient_id: str | None = None,
              model_name: str | None = None, model_version: str | None = None, confidence: float | None = None,
              decision: str | None = None) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_id, actor_role=actor_role, action=action, resource_type=resource_type, resource_id=resource_id,
        patient_user_id=patient_id, model_name=model_name, model_version=model_version, confidence=confidence,
        decision=decision, details=details or {}, request_id=request_id_var.get(), ip_address=client_ip_var.get(),
    )
    db.add(entry)
    return entry
