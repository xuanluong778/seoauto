"""Health/ready probes — DB + Redis checks."""

from __future__ import annotations


def test_readiness_payload_structure(monkeypatch):
    from app.services import health_probes

    monkeypatch.setattr(
        health_probes,
        "check_database",
        lambda timeout_sec=2.0: {"ok": True, "latency_ms": 1},
    )
    monkeypatch.setattr(
        health_probes,
        "check_redis",
        lambda timeout_sec=1.0: {"ok": True, "latency_ms": 2},
    )
    body, ready = health_probes.readiness_payload()
    assert ready is True
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True


def test_readiness_fails_when_redis_down(monkeypatch):
    from app.services import health_probes

    health_probes._readiness_full_cache["at"] = 0.0
    health_probes._readiness_full_cache["body"] = None
    monkeypatch.setattr(health_probes, "_full_cache_sec", lambda: 0.0)
    monkeypatch.setattr(
        health_probes,
        "check_database",
        lambda timeout_sec=2.0: {"ok": True, "latency_ms": 1},
    )
    monkeypatch.setattr(
        health_probes,
        "check_redis",
        lambda timeout_sec=1.0: {"ok": False, "error": "ConnectionError", "latency_ms": 5},
    )
    body, ready = health_probes.readiness_payload()
    assert ready is False
    assert body["status"] == "not_ready"
