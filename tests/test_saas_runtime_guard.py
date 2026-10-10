"""Production SaaS runtime guard."""

from __future__ import annotations

import logging

from app.services.saas_runtime_guard import log_saas_runtime_guard


def test_runtime_guard_logs_error_when_prod_flags_missing(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SAAS_ENFORCEMENT", raising=False)
    monkeypatch.delenv("CREDITS_ENABLED", raising=False)
    monkeypatch.setenv("COST_CONTROL_ENABLED", "1")

    with caplog.at_level(logging.CRITICAL):
        try:
            log_saas_runtime_guard()
        except Exception:
            pass

    assert any("PRODUCTION HARD-FAIL" in r.message for r in caplog.records)


def test_runtime_guard_ok_when_all_flags_on(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SAAS_ENFORCEMENT", "1")
    monkeypatch.setenv("CREDITS_ENABLED", "1")
    monkeypatch.setenv("COST_CONTROL_ENABLED", "1")

    with caplog.at_level(logging.INFO):
        log_saas_runtime_guard()

    assert any("production_security_ok" in r.message for r in caplog.records)
