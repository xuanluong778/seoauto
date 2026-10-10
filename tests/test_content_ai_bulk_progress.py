"""Bulk runner must persist x/y after each article and resume without resetting."""

from __future__ import annotations

from app.services.content_ai_bulk_runner import (
    count_bulk_success_items,
    end_bulk_job,
    restore_bulk_item_states,
    try_begin_bulk_job,
)


def test_restore_keeps_success_items_and_skips_pending():
    rows = [{"keyword": f"kw {i}"} for i in range(1, 13)]
    prev = {
        "total": 12,
        "success": 4,
        "items": [
            {"keyword": "kw 1", "status": "success", "project_id": "p1", "word_count": 500},
            {"keyword": "kw 2", "status": "success", "project_id": "p2", "word_count": 520},
            {"keyword": "kw 3", "status": "success", "project_id": "p3", "word_count": 480},
            {"keyword": "kw 4", "status": "success", "project_id": "p4", "word_count": 510},
            {"keyword": "kw 5", "status": "running"},
        ],
    }
    items = restore_bulk_item_states(rows, prev)
    assert len(items) == 12
    assert count_bulk_success_items(items) == 4
    assert items[0]["status"] == "success" and items[0]["project_id"] == "p1"
    assert items[4]["status"] == "pending"
    assert items[11]["status"] == "pending"


def test_process_lock_prevents_double_run():
    jid = "job-lock-1"
    try:
        assert try_begin_bulk_job(jid) is True
        assert try_begin_bulk_job(jid) is False
    finally:
        end_bulk_job(jid)
    assert try_begin_bulk_job(jid) is True
    end_bulk_job(jid)


def test_runner_persists_progress_each_of_12_keywords(monkeypatch):
    from app.services import content_ai_bulk_runner as runner

    captured: list[dict] = []

    def _capture_update(job_id, **kw):
        captured.append(dict(kw))

    def _capture_finish(job_id, *, result=None, **kw):
        captured.append({"finish": result})

    class _User:
        id = 1

    class _Db:
        def get(self, *args, **kwargs):
            return _User()

        def close(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(runner, "get_job", lambda job_id: None)
    monkeypatch.setattr(runner, "update_job", _capture_update)
    monkeypatch.setattr(runner, "finish_job", _capture_finish)
    monkeypatch.setattr("app.db.SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        "app.services.content_ai_word_count_policy.validate_target_word_count",
        lambda *a, **k: 1000,
    )
    monkeypatch.setattr(
        runner,
        "_write_one_article",
        lambda **kw: {"project_id": "p-" + kw["primary_keyword"], "word_count": 400},
    )
    monkeypatch.setattr(runner, "_auto_target_word_count_for_row", lambda **kw: 1000)

    keywords = [f"keyword {i}" for i in range(1, 13)]
    bulk_rows = [{"keyword": k, "target_word_count": 1000} for k in keywords]
    runner._run_content_ai_bulk_job_body(
        job_id="job-12",
        payload={"user_id": 1, "target_website": "https://example.com"},
        bulk_rows=bulk_rows,
        keywords=keywords,
        bulk_user_id=1,
    )

    success_snapshots = [
        int((u.get("result") or {}).get("success") or 0)
        for u in captured
        if isinstance(u, dict) and "result" in u
    ]
    first_live = next(
        (u.get("result") or {}) for u in captured if isinstance(u, dict) and u.get("result")
    )
    assert first_live["items"][0]["status"] == "running"
    assert success_snapshots[-1] == 12
    assert 1 in success_snapshots and 6 in success_snapshots and 12 in success_snapshots
    finish = next(u for u in captured if "finish" in u)
    assert finish["finish"]["success"] == 12
    assert finish["finish"]["total"] == 12
    assert count_bulk_success_items(finish["finish"]["items"]) == 12


def test_runner_resume_does_not_reset_written(monkeypatch):
    from types import SimpleNamespace

    from app.services import content_ai_bulk_runner as runner

    captured: list[dict] = []
    prev = SimpleNamespace(
        state="RUNNING",
        result={
            "total": 12,
            "success": 5,
            "items": [
                {"keyword": f"keyword {i}", "status": "success", "project_id": f"p{i}", "word_count": 400}
                for i in range(1, 6)
            ],
        },
    )
    wrote: list[str] = []

    monkeypatch.setattr(runner, "get_job", lambda job_id: prev)
    monkeypatch.setattr(runner, "update_job", lambda job_id, **kw: captured.append(dict(kw)))
    monkeypatch.setattr(runner, "finish_job", lambda job_id, *, result=None, **kw: captured.append({"finish": result}))

    class _User:
        id = 1

    class _Db:
        def get(self, *args, **kwargs):
            return _User()

        def close(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("app.db.SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        "app.services.content_ai_word_count_policy.validate_target_word_count",
        lambda *a, **k: 1000,
    )

    def _write(**kw):
        wrote.append(kw["primary_keyword"])
        return {"project_id": "n-" + kw["primary_keyword"], "word_count": 400}

    monkeypatch.setattr(runner, "_write_one_article", _write)
    monkeypatch.setattr(runner, "_auto_target_word_count_for_row", lambda **kw: 1000)

    keywords = [f"keyword {i}" for i in range(1, 13)]
    bulk_rows = [{"keyword": k, "target_word_count": 1000} for k in keywords]
    runner._run_content_ai_bulk_job_body(
        job_id="job-resume",
        payload={"user_id": 1, "target_website": "https://example.com"},
        bulk_rows=bulk_rows,
        keywords=keywords,
        bulk_user_id=1,
    )

    assert wrote == [f"keyword {i}" for i in range(6, 13)]
    first_result = next(u["result"] for u in captured if u.get("result"))
    assert int(first_result["success"]) == 5
    assert first_result["items"][5]["status"] == "running"
    finish = next(u for u in captured if "finish" in u)
    assert finish["finish"]["success"] == 12
    assert finish["finish"]["items"][0]["project_id"] == "p1"
