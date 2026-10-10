"""Probe fast-path middleware — /health and cached /ready."""

from __future__ import annotations

import json

import pytest

from app.middleware.probe_fastpath import (
    ProbeFastPathMiddleware,
    refresh_ready_cache,
    warm_ready_cache,
)


@pytest.fixture()
def ready_cache(monkeypatch):
    monkeypatch.setenv("READY_FULL_CACHE_SEC", "5")
    warm_ready_cache(lite=True)
    yield


def test_refresh_ready_cache_returns_bytes(ready_cache):
    body, status = refresh_ready_cache(lite=True)
    assert isinstance(body, (bytes, bytearray))
    assert status in (200, 503)
    parsed = json.loads(body.decode("utf-8"))
    assert "status" in parsed
    assert "checks" in parsed
    assert parsed.get("lite") is True


def test_ready_fastpath_no_query_string_crash(ready_cache):
    """Regression: query_string as bytes must not AttributeError on str.decode."""
    import asyncio

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/ready",
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    app = ProbeFastPathMiddleware(app=lambda s, r, sn: None)
    asyncio.run(app(scope, receive, send))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] in (200, 503)
