from sqlalchemy.orm import Session

from app.models.records import TimelineEvent


def add_event(db: Session, patient_id: str, event_type: str, title: str, summary: str = "", *, ref_type: str | None = None,
              ref_id: str | None = None, created_by: str | None = None) -> TimelineEvent:
    ev = TimelineEvent(patient_user_id=patient_id, event_type=event_type, title=title, summary=summary[:2000], ref_type=ref_type,
                       ref_id=ref_id, created_by=created_by)
    db.add(ev)
    return ev
