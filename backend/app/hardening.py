"""HTTP hardening: security headers, request ids and a small in-process rate limiter."""

import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("app.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}
HSTS = "max-age=31536000; includeSubDomains"
EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, hsts: bool = False) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if self._hsts:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client sliding window. In-process: with N replicas the effective limit is N times
    higher, so put an edge limiter in front for hard guarantees (see docs/operations.md)."""

    def __init__(self, app: object, limit_per_minute: int, window_seconds: float = 60.0) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._limit = limit_per_minute
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client(self, request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._limit <= 0 or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        now = time.monotonic()
        hits = self._hits[self._client(request)]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            retry = max(1, int(self._window - (now - hits[0])))
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)
        if len(self._hits) > 10_000:
            for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self._window]:
                del self._hits[key]
        return await call_next(request)
