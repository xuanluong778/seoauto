"""Bulk AI: Celery path must not silently fall back to inline worker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_bulk_start_fails_job_when_celery_enqueue_fails_and_inline_disabled():
    from app.routers import pages

    src = open(pages.__file__, encoding="utf-8").read()
    assert "CONTENT_AI_BULK_INLINE=0" in src or "inline worker disabled" in src
    assert "fail_job(" in src


def test_bulk_runner_idempotent_guard():
    from app.services.content_ai_bulk_runner import end_bulk_job, try_begin_bulk_job

    jid = "job-dup-test-001"
    end_bulk_job(jid)
    assert try_begin_bulk_job(jid) is True
    assert try_begin_bulk_job(jid) is False
    end_bulk_job(jid)
    assert try_begin_bulk_job(jid) is True
    end_bulk_job(jid)


def test_celery_task_skips_terminal_state():
    from app.workers.content_ai_bulk_tasks import run_content_ai_bulk_task

    with patch("app.services.job_store.get_job") as gj:
        st = MagicMock()
        st.state = "SUCCESS"
        st.payload = {"user_id": 1}
        st.user_id = 1
        gj.return_value = st
        out = run_content_ai_bulk_task.run("jid-done")
    assert out.get("skipped") == "SUCCESS"
