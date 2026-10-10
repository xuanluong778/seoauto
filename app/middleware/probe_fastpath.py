"""ASGI fast-path for liveness/readiness probes — bypass middleware stack."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LOG = logging.getLogger(__name__)

_HEALTH_BODY = json.dumps({"status": "ok"}).encode("utf-8")
_HEALTH_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-type", b"application/json; charset=utf-8"),
    (b"content-length", str(len(_HEALTH_BODY)).encode()),
    (b"cache-control", b"no-store"),
]

_ready_lock = threading.Lock()
_ready_body: bytes | None = None
_ready_status: int = 503
_ready_headers: list[tuple[bytes, bytes]] = []
_ready_bg_started = False


def _ready_cache_sec() -> float:
    raw = (os.getenv("READY_FULL_CACHE_SEC") or "3").strip()
    try:
        return max(0.5, min(30.0, float(raw)))
    except ValueError:
        return 3.0


_READY_LITE_OK_BODY = (
    b'{"status":"ready","lite":true,"checks":{"database":{"ok":true},"redis":{"ok":true}}}'
)
_READY_LITE_FAIL_BODY = (
    b'{"status":"not_ready","lite":true,"checks":{"database":{"ok":false},"redis":{"ok":false}}}'
)


def _ready_headers_for(body: bytes) -> list[tuple[bytes, bytes]]:
    return [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
        (b"connection", b"close"),
    ]


def refresh_ready_cache(*, lite: bool = True) -> tuple[bytes, int]:
    """Refresh cached /ready JSON from readiness checks (lite DB+Redis only)."""
    from app.services.health_probes import readiness_payload

    global _ready_body, _ready_status, _ready_headers
    try:
        body, ready = readiness_payload(lite=lite)
    except Exception:
        _LOG.exception("probe_ready_cache_refresh_failed")
        with _ready_lock:
            if _ready_body is not None:
                return _ready_body, _ready_status
        body, ready = {"status": "not_ready", "lite": lite, "checks": {}}, False

    if lite:
        payload = _READY_LITE_OK_BODY if ready else _READY_LITE_FAIL_BODY
    else:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    status = 200 if ready else 503
    headers = _ready_headers_for(payload)
    with _ready_lock:
        if not ready and _ready_body is not None and _ready_status == 200:
            return _ready_body, _ready_status
        _ready_body = payload
        _ready_status = status
        _ready_headers = headers
    return payload, status


def warm_ready_cache(*, lite: bool = True) -> None:
    try:
        refresh_ready_cache(lite=lite)
    except Exception:
        _LOG.exception("probe_ready_cache_warm_failed")


def _ready_background_loop() -> None:
    interval = _ready_cache_sec()
    while True:
        try:
            refresh_ready_cache(lite=True)
        except Exception:
            _LOG.exception("probe_ready_cache_refresh_failed")
        time.sleep(interval)


def start_ready_cache_background() -> None:
    """Daemon thread keeps /ready cache warm — probes never hit DB on request path."""
    global _ready_bg_started
    if _ready_bg_started:
        return
    if (os.getenv("READY_FASTPATH_BG", "1") or "1").strip().lower() in ("0", "false", "no", "off"):
        return
    _ready_bg_started = True
    warm_ready_cache(lite=True)
    t = threading.Thread(target=_ready_background_loop, name="probe-ready-cache", daemon=True)
    t.start()


def _cached_ready() -> tuple[bytes, int, list[tuple[bytes, bytes]]]:
    with _ready_lock:
        body = _ready_body
        status = _ready_status
        headers = _ready_headers
    if body is None:
        body, status = refresh_ready_cache(lite=True)
        with _ready_lock:
            headers = list(_ready_headers)
    return body, status, headers


class ProbeFastPathMiddleware:
    """Return /health and cached /ready immediately without traversing BaseHTTPMiddleware layers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method", "GET").upper() != "GET":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")

        if path == "/health":
            await send({"type": "http.response.start", "status": 200, "headers": _HEALTH_HEADERS})
            await send({"type": "http.response.body", "body": _HEALTH_BODY})
            return

        if path == "/ready":
            # Only lite readiness on fast path; ?full=1 falls through to route handler.
            raw_qs = scope.get("query_string") or b""
            if isinstance(raw_qs, (bytes, bytearray)):
                qs = bytes(raw_qs).decode("latin-1", errors="ignore")
            else:
                qs = str(raw_qs)
            if "full=1" in qs or "full=true" in qs.lower():
                await self.app(scope, receive, send)
                return
            body, status, headers = _cached_ready()
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
