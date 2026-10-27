"""Evidence / Knowledge Layer. Explanations may only use APPROVED, versioned documents."""
from sqlalchemy.orm import Session

from app.models.records import KnowledgeDocument, KnowledgeVersion
from app.seed.knowledge_seed import DOCS, PUB, REVIEW, REVIEWER, SOURCE


def seed_knowledge(db: Session) -> None:
    for slug, title, topics, content in DOCS:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.slug == slug).first()
        if not doc:
            doc = KnowledgeDocument(slug=slug, title=title, topics=topics)
            db.add(doc)
            db.flush()
            db.add(KnowledgeVersion(document_id=doc.id, version="1.0", content=content, source=SOURCE, publication_date=PUB,
                                    review_date=REVIEW, reviewer=REVIEWER, status="approved"))
    db.commit()


def retrieve(db: Session, topics: list[str]) -> list[dict]:
    """Return the latest approved version of every document covering any of the requested topics."""
    wanted = set(topics)
    if not wanted:
        return []
    out = []
    for doc in db.query(KnowledgeDocument).all():
        if not wanted.intersection(doc.topics or []):
            continue
        versions = db.query(KnowledgeVersion).filter(KnowledgeVersion.document_id == doc.id, KnowledgeVersion.status == "approved").all()
        if not versions:
            continue
        v = sorted(versions, key=lambda x: x.created_at)[-1]
        out.append({"document_id": doc.id, "slug": doc.slug, "title": doc.title, "topics": doc.topics, "version": v.version,
                    "source": v.source, "publication_date": v.publication_date, "review_date": v.review_date,
                    "reviewer": v.reviewer, "status": v.status, "content": v.content})
    return out


def citation(e: dict) -> dict:
    return {k: e[k] for k in ("slug", "title", "version", "source", "reviewer", "review_date")}
