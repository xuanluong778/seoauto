"""WAVE 9 — observability, structured logging, alerting."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.request_id import RequestIdMiddleware
from app.services.llm_ops_metrics import llm_snapshot, record_llm_call
from app.services.ops_alerting import evaluate_alerts, simulate_alert_test
from app.services.structured_log import log_request_event, redact_dict, redact_string


@pytest.fixture()
def obs_env(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_WAVE9", "1")
    monkeypatch.setenv("OPS_ALERTING_ENABLED", "1")
    monkeypatch.setenv("STRUCTURED_REQUEST_LOG", "1")
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "0")


def test_secret_redaction():
    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret and sk-abcdefghijklmnopqrstuvwxyz1234"
    assert "[REDACTED]" in redact_string(raw)
    safe = redact_dict(
        {
            "password": "secret123",
            "access_token": "tok",
            "user_id": 42,
            "nested": {"api_key": "k", "ok": "yes"},
        }
    )
    assert safe["password"] == "[REDACTED]"
    assert safe["access_token"] == "[REDACTED]"
    assert safe["user_id"] == 42
    assert safe["nested"]["api_key"] == "[REDACTED]"


def test_structured_log_no_secrets(caplog):
    caplog.set_level(logging.INFO, logger="seoauto.request")
    log_request_event(
        event="http_request",
        request_id="abc123",
        user_id=1,
        organization_id=1,
        password="leak",
        authorization="Bearer secret-token",
    )
    assert caplog.records
    payload = json.loads(caplog.records[-1].message)
    assert payload["request_id"] == "abc123"
    assert payload["password"] == "[REDACTED]"
    assert payload["authorization"] == "[REDACTED]"


def test_request_id_middleware_header():
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    app.add_middleware(RequestIdMiddleware)
    client = TestClient(app)
    resp = client.get("/ping", headers={"X-Request-Id": "custom-rid-99"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "custom-rid-99"


def test_alert_simulation_and_dedup(obs_env):
    from app.services.ops_alerting import reset_alert_state_for_tests

    reset_alert_state_for_tests()
    result = simulate_alert_test()
    assert result["first_alert_count"] >= 5
    assert result["duplicate_suppressed"] is True
    assert "api_5xx_rate" in result["alert_types"]
    assert "queue_backlog" in result["alert_types"]
    assert "worker_down" in result["alert_types"]
    assert "db_unhealthy" in result["alert_types"]
    assert "redis_unhealthy" in result["alert_types"]
    assert result["recovery_detected"] is True


def test_evaluate_alerts_respects_dedup(obs_env):
    from app.services.ops_alerting import reset_alert_state_for_tests

    reset_alert_state_for_tests()
    bad = {
        "http": {"total_requests": 50, "error_5xx": 5, "p95_ms": 100},
        "queue": {"queued_count": 0},
        "celery": {"workers_online": 2},
        "db_probe": {"ok": True},
        "redis_probe": {"ok": True},
        "auth": {"401_count": 0},
    }
    first = evaluate_alerts(bad, force=True)
    second = evaluate_alerts(bad, force=True)
    assert len(first) >= 1
    assert len(second) == 0


def test_llm_metrics_counter():
    before = llm_snapshot()["calls"]
    record_llm_call(ok=False, rate_limited=True)
    record_llm_call(ok=True, tokens=100)
    snap = llm_snapshot()
    assert snap["calls"] == before + 2
    assert snap["rate_limited_429"] >= 1


def test_ops_metrics_shape(obs_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.ops_metrics.db_pool_stats",
        lambda: {"pool_size": 5, "checked_out": 1, "overflow": 0},
    )
    monkeypatch.setattr(
        "app.services.ops_metrics.queue_backlog_stats",
        lambda: {"queued_count": 0, "running_count": 0},
    )
    monkeypatch.setattr(
        "app.services.ops_metrics.celery_worker_stats",
        lambda timeout_sec=0.8: {"workers_online": 1, "ping_ok": True},
    )
    monkeypatch.setattr(
        "app.services.ops_metrics.redis_queue_stats",
        lambda: {"configured": True, "ping_ms": 1.0, "memory_mb": 10},
    )
    monkeypatch.setattr(
        "app.services.ops_metrics.pg_connection_stats",
        lambda: {"pg": True, "connections_total": 3},
    )
    monkeypatch.setattr(
        "app.services.health_probes.check_database",
        lambda timeout_sec=1.0: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.health_probes.check_redis",
        lambda timeout_sec=0.8: {"ok": True},
    )
    from app.services.ops_metrics import collect_ops_metrics

    payload = collect_ops_metrics()
    assert "http" in payload
    assert "slo" in payload
    assert "alerts" in payload
    assert "llm" in payload
    assert "auth" in payload
    assert "redis" in payload
    assert "db_connections" in payload
