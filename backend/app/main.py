import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401  (register tables)
from app.api import admin, analysis, auth, perio, review, voice, workflows
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.middleware import RequestContextMiddleware
from app.core.security import get_current_user, hash_password
from app.models.user import User
from app.services.knowledge import seed_knowledge
from app.services.model_registry import seed_models
from app.services.storage import get_storage

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("dentedge")


def bootstrap():
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if not settings.seed_reference_data:
        return
    with SessionLocal() as db:
        seed_models(db)
        seed_knowledge(db)
        if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            email = settings.bootstrap_admin_email.lower()
            if not db.query(User).filter(User.email == email).first():
                db.add(User(full_name="Platform Administrator", email=email, password_hash=hash_password(settings.bootstrap_admin_password), role="admin"))
                db.commit()
                logger.info("Bootstrap administrator created: %s", email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="DentEdge AI API", version=settings.app_version, lifespan=lifespan,
    description="DentEdge AI Oral Health Intelligence platform. AI detects. The system validates. Clinical rules constrain. "
                "The LLM explains. The dentist decides. Outputs are AI-assisted observations, not diagnoses.",
    docs_url=None if settings.is_production else "/docs", redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json",
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                   expose_headers=["X-Request-ID"])


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "dentedge-ai-api", "version": app.version, "environment": settings.app_env}


@app.get("/ready", tags=["System"])
def ready():
    checks = {}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    checks["storage"] = "ok" if get_storage().healthy() else "error"
    ok = all(v == "ok" for v in checks.values())
    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@app.get("/api/v1/system/info", tags=["System"])
def system_info(_: User = Depends(get_current_user)):
    from app.services.llm.providers import get_speech_provider
    return {"version": app.version, "environment": settings.app_env, "appointment_booking_url": settings.appointment_booking_url,
            "llm_provider": settings.llm_provider, "vision_provider": settings.vision_provider,
            "server_speech": get_speech_provider() is not None, "max_upload_mb": settings.max_upload_mb,
            "confidence_threshold": settings.confidence_threshold}


for r in (auth.router, analysis.router, review.router, voice.router, perio.router, workflows.router, admin.router):
    app.include_router(r, prefix="/api/v1")
