# DentEdge AI  Oral Health Intelligence Platform

Multimodal dental AI platform implementing the *DentEdge AI Production Plan v1.0*:

> **AI detects. The system validates. Clinical rules constrain. The LLM explains. The dentist decides.**

| Layer | Stack |
|---|---|
| Frontend | React 19 + TypeScript + Vite, served by Nginx (patient, dentist and admin portals) |
| API | Python 3.12 + FastAPI, versioned under `/api/v1` |
| Database | PostgreSQL 16 (SQLite for local development), Alembic migrations |
| Object storage | Local volume or S3-compatible bucket; **every object Fernet-encrypted at rest** |
| Cache / rate limiting | Redis (optional; in-process fallback) |
| Computer vision | OpenCV + pluggable model classes (heuristic research models, vision-LLM, ONNX production slot) |
| LLM | Provider abstraction: deterministic templates (default), OpenAI, Anthropic, any OpenAI-compatible local server |
| Speech | Browser Web Speech API, or server STT provider (OpenAI Whisper / local Whisper-compatible) |

## Quick start (development)

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m scripts.seed_demo             # demo admin / dentist / patient (non-production only)
uvicorn app.main:app --reload --port 8000

# Frontend (new terminal) — proxies /api to :8000
cd frontend && npm ci && npm run dev    # http://localhost:5173
```

Demo logins: `patient@dentedge.example / PatientPass2026`, `dentist@dentedge.example / DentistPass2026`, `admin@dentedge.example / AdminPass2026`.

## Production (Docker Compose)

```bash
cp .env.example .env      # set JWT_SECRET_KEY, STORAGE_ENCRYPTION_KEY, BOOTSTRAP_ADMIN_PASSWORD, CORS_ORIGINS, provider keys
docker compose up -d --build
# → http://<host>:8080  (put TLS in front: load balancer / Caddy / Nginx with certificates)
```

The API container runs `alembic upgrade head` before starting. With `APP_ENV=production` the API **refuses to start** with a weak JWT secret, no storage encryption key or a SQLite database. Interactive API docs are disabled in production (`/docs` available in development).

## Tests

```bash
cd backend && pytest                    # 55 tests: unit, model behaviour, safety, RBAC/isolation, red-team, end-to-end API
TEST_DATABASE_URL=postgresql+psycopg://... pytest   # same suite against PostgreSQL
cd frontend && npm run build            # strict TypeScript build
```

## Key configuration

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `template` (default, offline, deterministic) · `openai` · `anthropic` · `local` |
| `VISION_PROVIDER` | `research` (OpenCV measurement model) · `llm` (vision-LLM constrained to vocabulary) · `none` |
| `SPEECH_PROVIDER` | `none` (browser dictation only) · `openai` · `local` |
| `ALLOWED_MODEL_STATUSES` | Registry statuses the orchestrator may run. **Set to `production` for a clinical launch.** |
| `CONFIDENCE_THRESHOLD` | Below this, findings are marked *uncertain* (rule R004) |
| `APPOINTMENT_BOOKING_URL` | DentEdge booking page used by every “Book appointment” CTA |

See `docs/PLAN_COMPLIANCE.md` for the section-by-section traceability against the production plan and `docs/GO_LIVE.md` for what must happen before clinical use.
