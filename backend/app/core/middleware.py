"""Request context, security headers, rate limiting and technical metrics."""
import contextvars
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger("dentedge")
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
client_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)


# --------------------------------------------------------------------------- metrics
class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = 0
        self.errors = 0
        self.rate_limited = 0
        self.latencies: deque[float] = deque(maxlen=5000)
        self.by_route: dict[str, dict] = defaultdict(lambda: {"count": 0, "errors": 0, "total_ms": 0.0})

    def record(self, route: str, status: int, ms: float):
        with self.lock:
            self.requests += 1
            self.latencies.append(ms)
            r = self.by_route[route]
            r["count"] += 1
            r["total_ms"] += ms
            if status >= 500:
                self.errors += 1
                r["errors"] += 1

    def snapshot(self) -> dict:
        with self.lock:
            lat = sorted(self.latencies)

            def pct(p):
                return round(lat[min(len(lat) - 1, int(len(lat) * p))], 2) if lat else 0.0
            routes = {k: {"count": v["count"], "errors": v["errors"], "avg_ms": round(v["total_ms"] / v["count"], 2)} for k, v in self.by_route.items()}
            return {
                "uptime_seconds": int(time.time() - self.started), "requests": self.requests, "server_errors": self.errors,
                "rate_limited": self.rate_limited, "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99)},
                "routes": dict(sorted(routes.items(), key=lambda kv: -kv[1]["count"])[:25]),
            }


metrics = Metrics()


# --------------------------------------------------------------------------- rate limiting
class RateLimiter:
    """Sliding-window limiter. Uses Redis when REDIS_URL is configured so limits are shared across replicas."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.redis = None
        if settings.redis_url:
            try:
                import redis  # type: ignore
                self.redis = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5)
                self.redis.ping()
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis unavailable, falling back to in-process rate limiting: %s", exc)
                self.redis = None

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        if limit <= 0:
            return True
        if self.redis is not None:
            try:
                bucket = f"rl:{key}:{int(time.time() // window)}"
                count = self.redis.incr(bucket)
                if count == 1:
                    self.redis.expire(bucket, window + 1)
                return count <= limit
            except Exception:  # pragma: no cover
                pass
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self.lock:
            self.hits.clear()


rate_limiter = RateLimiter()


def _bucket(request: Request) -> tuple[str, int]:
    path = request.url.path
    if path.startswith("/api/v1/auth/login") or path.startswith("/api/v1/auth/register"):
        return "auth", settings.auth_rate_limit_per_minute
    if request.method == "POST" and any(s in path for s in ("/oral-images", "/xrays", "/smile-analysis", "/voice/transcribe")):
        return "upload", settings.upload_rate_limit_per_minute
    return "api", settings.rate_limit_per_minute


def _client_key(request: Request, ip: str) -> str:
    """Authenticated traffic is limited per user (clinics often share one public IP); anonymous traffic per IP.
    The token is only used as a bucket key here; it is fully verified by the auth dependency."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            from jose import jwt
            sub = jwt.get_unverified_claims(auth[7:]).get("sub")
            if sub:
                return f"user:{str(sub)[:36]}"
        except Exception:
            pass
    return f"ip:{ip}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        rid = rid[:64]
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        request_id_var.set(rid)
        client_ip_var.set(ip)
        start = time.perf_counter()

        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            bucket, limit = _bucket(request)
            key = _client_key(request, ip)
            # per-user bucket plus a coarse per-IP ceiling so rotating forged tokens cannot bypass limiting
            over = not rate_limiter.allow(f"{bucket}:{key}", limit)
            if not over and key.startswith("user:"):
                over = not rate_limiter.allow(f"{bucket}:ipcap:{ip}", limit * 5)
            if over:
                metrics.rate_limited += 1
                return JSONResponse({"detail": "Too many requests. Please wait a moment and try again."}, status_code=429, headers={"Retry-After": "60", "X-Request-ID": rid})

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error request_id=%s path=%s", rid, request.url.path)
            metrics.record(request.url.path, 500, (time.perf_counter() - start) * 1000)
            return JSONResponse({"detail": "An unexpected error occurred", "request_id": rid}, status_code=500, headers={"X-Request-ID": rid})

        elapsed = (time.perf_counter() - start) * 1000
        route = request.scope.get("route")
        metrics.record(getattr(route, "path", request.url.path), response.status_code, elapsed)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
