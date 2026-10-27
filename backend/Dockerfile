FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r dentedge && useradd -r -g dentedge -d /app dentedge
COPY requirements.txt requirements-optional.txt ./
ARG INSTALL_OPTIONAL=false
RUN pip install -r requirements.txt && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install -r requirements-optional.txt; fi
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN mkdir -p /data/uploads && chown -R dentedge:dentedge /app /data
USER dentedge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/ready || exit 1
# Migrations run first; then the API with multiple workers behind the reverse proxy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]
