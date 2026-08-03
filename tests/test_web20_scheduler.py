"""Web 2.0 scheduler, retry, token refresh tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import social_auto_web20_store as store
from app.services.social_auto_web20_scheduler import run_web20_scheduler
from app.services.web20_oauth_tokens import refresh_blogger_token, refresh_tumblr_token


@pytest.fixture()
def web20_files(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(store, "POSTS_FILE", tmp_path / "posts.json")
    monkeypatch.setattr(store, "LOGS_FILE", tmp_path / "logs.json")
    monkeypatch.setattr(store, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path


def _wp_account(user_id: int = 1) -> dict:
    return store.create_account(
        user_id=user_id,
        site_url="https://sat.example.com",
        username="u",
        app_password="pass1234",
    )


def _post(user_id: int, account_id: str, **extra) -> dict:
    row = store.create_post(
        user_id=user_id,
        account_id=account_id,
        title="Test bài Web 2.0 đủ dài để pass safety check content minimum",
        html_content="<p>Nội dung spin khác biệt hoàn toàn so với bài gốc về chủ đề SEO local.</p>",
        main_site_url="https://main.com",
        source_content="Nội dung gốc khác hẳn.",
    )
    if extra:
        store.update_post(row["id"], user_id, extra)
        row = store._find_post(row["id"], user_id)  # type: ignore[attr-defined]
        return store._public_post(row)  # type: ignore[attr-defined]
    return row


def test_daily_quota_blocks_fourth_post(web20_files):
    acc = _wp_account()
    from app.services.social_auto_web20_safety import run_web20_safety_checks

    for i in range(3):
        p = _post(1, acc["id"], title=f"Bài {i} " + "x" * 40)
        store.update_post(
            p["id"],
            1,
            {"status": "published", "published_at": datetime.now(timezone.utc).isoformat()},
        )
    result = run_web20_safety_checks(
        1,
        title="Bài thứ 4 " + "y" * 40,
        html_content="<p>Nội dung mới không trùng bài cũ về SEO và marketing digital.</p>",
        account_id=acc["id"],
        main_site_url="https://main.com",
    )
    codes = {c["code"] for c in result["checks"]}
    assert "daily_quota" in codes
    assert result["can_publish"] is False


def test_list_due_scheduled_posts(web20_files):
    acc = _wp_account()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    p1 = _post(1, acc["id"], status="scheduled", scheduled_at=past)
    _post(1, acc["id"], status="scheduled", scheduled_at=future)
    due = store.list_due_scheduled_posts()
    assert len(due) == 1
    assert due[0]["id"] == p1["id"]


@patch("app.services.social_auto_web20_scheduler.publish_web20_post")
def test_scheduler_runs_due_posts(mock_publish, web20_files):
    acc = _wp_account()
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    p = _post(1, acc["id"], status="scheduled", scheduled_at=past)
    mock_publish.return_value = {"item": {"id": p["id"], "status": "ready"}}
    out = run_web20_scheduler(limit=5)
    assert out["queued"] == 1
    assert out["processed"][0]["ok"] is True
    mock_publish.assert_called_once()


@patch("app.services.social_auto_web20_scheduler.publish_web20_post")
def test_scheduler_marks_failed_after_exception(mock_publish, web20_files):
    acc = _wp_account()
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    p = _post(1, acc["id"], status="scheduled", scheduled_at=past)
    mock_publish.side_effect = HTTPException(status_code=502, detail="API down")
    out = run_web20_scheduler(limit=5)
    assert out["processed"][0]["ok"] is False
    row = store._find_post(p["id"], 1)  # type: ignore[attr-defined]
    assert row is not None


def test_blogger_refresh_mock_token():
    out = refresh_blogger_token("mock_blogger_refresh")
    assert out["access_token"] == "mock_blogger_token"


def test_tumblr_refresh_mock_token():
    out = refresh_tumblr_token("mock_tumblr_refresh")
    assert out["access_token"] == "mock_tumblr_token"


@patch("app.services.web20_oauth_tokens.requests.post")
def test_blogger_refresh_live(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"access_token": "new_access", "refresh_token": "new_refresh"}
    out = refresh_blogger_token("real_refresh_token")
    assert out["access_token"] == "new_access"
