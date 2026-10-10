"""Sensitive rate-limit must fail-closed when Redis down in production."""

from __future__ import annotations


def test_sensitive_path_fail_closed_without_redis(monkeypatch):
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "1")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RATE_LIMIT_REDIS", "1")
    from app.services import rate_limiter as rl

    monkeypatch.setattr(rl, "_check_redis", lambda *a, **k: None)
    monkeypatch.setattr(rl, "_check_memory", lambda *a, **k: True)
    ok, rule = rl.check_request_rate_limit("/auth/login", "203.0.113.10", method="POST")
    assert ok is False
    assert rule == "/auth/login"


def test_non_sensitive_still_memory_fallback(monkeypatch):
    monkeypatch.setenv("SEOAUTO_PRODUCTION", "1")
    monkeypatch.setenv("APP_ENV", "production")
    from app.services import rate_limiter as rl

    monkeypatch.setattr(rl, "_check_redis", lambda *a, **k: None)
    monkeypatch.setattr(rl, "clear_rate_limit", lambda **k: 0)
    rl.clear_rate_limit(path_prefix="/analyze", client_ip="203.0.113.11")
    # force memory path
    for _ in range(30):
        ok, _ = rl.check_request_rate_limit("/analyze/technical", "203.0.113.11", method="POST")
        assert ok
    ok, rule = rl.check_request_rate_limit("/analyze/technical", "203.0.113.11", method="POST")
    assert ok is False
    assert rule == "/analyze"
