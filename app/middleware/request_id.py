"""Request ID correlation + structured access log (WAVE 9)."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_PROBE_PATHS = frozenset({"/health", "/ready", "/metrics"})


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
        request.state.request_id = rid
        path = request.url.path or ""
        if path in _PROBE_PATHS:
            response = await call_next(request)
            response.headers["X-Request-Id"] = rid
            return response

        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = int(getattr(response, "status_code", 500) or 500)
            response.headers["X-Request-Id"] = rid
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            if path.startswith("/auth"):
                from app.services.auth_ops_metrics import record_auth_status

                record_auth_status(status)
            from app.services.observability_rollout import structured_request_logging_enabled

            if structured_request_logging_enabled():
                user_id = None
                org_id = None
                cu = getattr(request.state, "current_user", None)
                if cu is not None:
                    user_id = getattr(cu, "id", None)
                    org_id = getattr(cu, "organization_id", None) or user_id
                from app.services.structured_log import log_request_event

                log_request_event(
                    event="http_request",
                    request_id=rid,
                    method=request.method,
                    path=path[:200],
                    status=status,
                    latency_ms=elapsed_ms,
                    user_id=user_id,
                    organization_id=org_id,
                )
