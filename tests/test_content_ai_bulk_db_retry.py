"""Bulk write: DB session release + transient retry + job item retry reset."""

from __future__ import annotations

import pytest

from app.services.content_ai_bulk_runner import (
    _humanize_bulk_error,
    _is_non_retryable_llm_error,
    _is_transient_db_error,
    _is_transient_llm_error,
    reset_bulk_job_items_for_retry,
)


def test_is_transient_db_error_detects_pgbouncer_kill():
    exc = Exception("(psycopg2.OperationalError) server closed the connection unexpectedly")
    assert _is_transient_db_error(exc) is True


def test_humanize_bulk_error_db_message():
    exc = Exception("(psycopg2.OperationalError) server closed the connection unexpectedly")
    msg = _humanize_bulk_error(exc)
    assert "DB" in msg or "kết nối" in msg


def test_llm_auth_not_retryable():
    assert _is_non_retryable_llm_error(Exception("401 Unauthorized invalid api key")) is True
    assert _is_transient_llm_error(Exception("401 Unauthorized")) is False


def test_reset_bulk_job_items_for_retry(monkeypatch):
    from app.services import content_ai_bulk_runner as runner

    captured: dict = {}

    class _St:
        state = "SUCCESS"
        result = {
            "total": 2,
            "success": 0,
            "failed": 2,
            "items": [
                {"keyword": "kw a", "status": "error", "error": "db down"},
                {"keyword": "kw b", "status": "success", "project_id": "p1"},
            ],
        }

    monkeypatch.setattr("app.services.job_store.get_job", lambda jid: _St())
    monkeypatch.setattr(
        "app.services.job_store.update_job",
        lambda jid, **kw: captured.update(kw),
    )
    retried = reset_bulk_job_items_for_retry("job-x", keywords=["kw a"])
    assert retried == ["kw a"]
    assert captured["state"] == "QUEUED"
    items = captured["result"]["items"]
    assert items[0]["status"] == "pending"
    assert "error" not in items[0]
    assert items[1]["status"] == "success"
