"""Record per-request latency for /metrics."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_PROBE_PATHS = frozenset({"/health", "/ready", "/metrics"})


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PROBE_PATHS:
            return await call_next(request)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = int(getattr(response, "status_code", 500) or 500)
            return response
        except Exception:
            status = 500
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            path = request.url.path
            if len(path) > 120:
                path = path[:117] + "..."
            from app.services.request_metrics import record_request

            record_request(
                path=path,
                method=request.method,
                status=status,
                latency_ms=elapsed_ms,
            )
