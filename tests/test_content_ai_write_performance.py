"""Smoke/perf helpers for Content AI write path optimizations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.content_ai_project_store import (
    PROJECT_FILE,
    save_or_update_written_bulk_project,
    update_content_ai_project_fields,
)
from app.services.content_ai_request_cache import cache_get, cache_get_or_set, reset_request_cache
from app.services.content_ai_word_count_policy import build_word_count_response
from app.services.content_ai_write_timing import ContentAiWriteTimer, STEP_LLM, bind_write_timer, mark_step


def _user(*, plan: str = "pro") -> SimpleNamespace:
    return SimpleNamespace(id=42, plan_slug=plan, plan=plan, is_admin=False, api_access_enabled=False)


def test_request_cache_key_stable_for_same_site_keyword():
    reset_request_cache()
    seen: list[str] = []

    def factory():
        seen.append("hit")
        return (("https://x.test", "text"), [{"title": "A", "url": "https://x.test/a"}])

    key = "webctx:https://x.test:seo:8"
    cache_get_or_set(key, factory)
    cache_get_or_set(key, factory)
    assert seen == ["hit"]


def test_cache_get_or_set_once():
    reset_request_cache()
    n = {"v": 0}

    def factory():
        n["v"] += 1
        return {"found": True}

    assert cache_get_or_set("kb:test", factory)["found"] is True
    assert cache_get_or_set("kb:test", factory)["found"] is True
    assert n["v"] == 1
    assert cache_get("kb:test")["found"] is True


def test_skip_client_enforce_within_15_percent_band():
    user = _user()
    html = "<p>" + "word " * 920 + "</p>"
    resp = build_word_count_response(client_value=1000, user=user, db=None, html=html)
    assert resp["skip_client_enforce"] is True
    assert resp["needs_repair"] is False


def test_timing_accumulates_steps():
    timer = ContentAiWriteTimer(endpoint="/test", request_id="req-smoke-1", user_id=1)
    bind_write_timer(timer)
    mark_step(STEP_LLM, field="content")
    summary = timer.finish()
    assert summary["request_id"] == "req-smoke-1"
    assert summary["total_ms"] >= 0
    assert any(s["step"] == STEP_LLM for s in summary["steps"])


def test_project_store_mutate_single_update(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    source = {
        "target_website": "https://site.test",
        "primary_keyword": "kw a",
        "title": "T",
        "content": "<p>one</p>",
        "target_word_count": 1000,
    }
    draft = {"title": "T", "content": "<p>one</p>", "slug": "t", "tags": [], "meta_description": "m"}
    pid = save_or_update_written_bulk_project(user_id=7, source_payload=source, draft_payload=draft)
    before_mtime = PROJECT_FILE.stat().st_mtime
    row = update_content_ai_project_fields(pid, {"content": "<p>two words here</p>"}, user_id=7)
    assert row and row["id"] == pid
    raw = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    assert len(raw) == 1
    assert "two words" in str(raw[0].get("content") or "")
    assert PROJECT_FILE.stat().st_mtime >= before_mtime
