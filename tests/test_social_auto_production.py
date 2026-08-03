"""Social Auto production: quota, scheduler, retry, isolation, mock guard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import social_auto_store as fb_store
from app.services import social_auto_web20_store as w20_store
from app.services.social_auto_production import assert_publish_not_mock, is_production
from app.services.social_auto_quota import FEATURE_KEY, assert_publish_allowed
from app.services.social_auto_scheduler import run_facebook_scheduler
from app.services.social_auto_store import compute_next_retry_at


@pytest.fixture(autouse=True)
def _isolate_json_stores(tmp_path, monkeypatch):
    fb_c = tmp_path / "fb_c.json"
    fb_p = tmp_path / "fb_p.json"
    w_a = tmp_path / "w_a.json"
    w_p = tmp_path / "w_p.json"
    w_l = tmp_path / "w_l.json"
    w_s = tmp_path / "w_s.json"
    for p in (fb_c, fb_p, w_a, w_p, w_l, w_s):
        p.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(fb_store, "CAMPAIGNS_FILE", fb_c)
    monkeypatch.setattr(fb_store, "POSTS_FILE", fb_p)
    monkeypatch.setattr(w20_store, "ACCOUNTS_FILE", w_a)
    monkeypatch.setattr(w20_store, "POSTS_FILE", w_p)
    monkeypatch.setattr(w20_store, "LOGS_FILE", w_l)
    monkeypatch.setattr(w20_store, "SETTINGS_FILE", w_s)
    yield


def test_compute_next_retry_at():
    assert compute_next_retry_at(1)


def test_user_isolation_admin_sees_all():
    fb_store.create_campaign(user_id=1, name="A", source_title="A")
    fb_store.create_campaign(user_id=2, name="B", source_title="B")
    assert len(fb_store.list_campaigns(1)) == 1
    assert len(fb_store.list_campaigns(1, "admin")) == 2


def test_cancel_schedule_sets_cancelled():
    uid = 7
    c = fb_store.create_campaign(user_id=uid, name="C", source_title="T")
    p = fb_store.create_post(user_id=uid, campaign_id=c["id"], platform="facebook", title="x", content="y")
    fb_store.schedule_post(p["id"], uid, "2026-12-01T09:00:00+00:00")
    item = fb_store.cancel_schedule(p["id"], uid)
    assert item["status"] == "cancelled"


def test_retry_fields_on_create():
    c = fb_store.create_campaign(user_id=1, name="R", source_title="T")
    p = fb_store.create_post(user_id=1, campaign_id=c["id"], platform="facebook", title="a", content="b")
    assert p.get("retry_count") == 0
    assert p.get("next_retry_at") is None


def test_mock_guard_blocks_non_admin_on_production(monkeypatch):
    user = MagicMock()
    user.role = "user"
    monkeypatch.setenv("APP_ENV", "production")
    assert is_production()
    with pytest.raises(Exception):
        assert_publish_not_mock(user, is_mock=True, platform="Facebook")


def test_admin_bypasses_mock_guard(monkeypatch):
    admin = MagicMock()
    admin.role = "admin"
    monkeypatch.setenv("APP_ENV", "production")
    assert_publish_not_mock(admin, is_mock=True, platform="Facebook")


def test_facebook_scheduler_publishes_due_post():
    uid = 99
    c = fb_store.create_campaign(user_id=uid, name="Sched", source_title="T")
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    p = fb_store.create_post(user_id=uid, campaign_id=c["id"], platform="facebook", title="Hi", content="Body", page_id="pg1")
    fb_store.update_post(p["id"], uid, {"status": "scheduled", "scheduled_at": past, "page_id": "pg1"})

    db = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = MagicMock(id=uid, role="user")

    with patch("app.services.social_auto_facebook_publish.assert_publish_allowed"):
        with patch("app.services.social_auto_facebook_publish.record_publish_usage"):
            with patch("app.services.social_auto_facebook_publish.publish_to_fanpage") as pub:
                pub.return_value = {"permalink_url": "https://facebook.com/post/1", "id": "1"}
                with patch("app.services.social_auto_facebook_publish.list_pages") as lp:
                    lp.return_value = [{"page_id": "pg1", "page_name": "Test", "is_mock": False}]
                    with patch("app.services.social_auto_facebook_publish.is_mock_mode", return_value=False):
                        with patch("app.services.social_auto_facebook_publish.run_safety_checks") as saf:
                            saf.return_value = {"passed": True, "can_schedule": True}
                            out = run_facebook_scheduler(db=db, limit=5)
    assert out["queued"] >= 1
    assert any(x.get("ok") for x in out["processed"])


def test_quota_enforcement(monkeypatch):
    monkeypatch.setenv("SOCIAL_AUTO_QUOTA_ENFORCEMENT", "1")
    user = MagicMock()
    user.id = 1
    user.role = "user"
    db = MagicMock()
    with patch("app.services.social_auto_quota.get_monthly_limit", return_value=5):
        with patch("app.services.social_auto_quota.get_monthly_used", return_value=5):
            with pytest.raises(Exception):
                assert_publish_allowed(db, user)


def test_web20_user_isolation_admin_sees_all():
    w20_store.create_manual_account(user_id=1, label="U1")
    w20_store.create_manual_account(user_id=2, label="U2")
    assert len(w20_store.list_accounts(1)) == 1
    assert len(w20_store.list_accounts(1, role="admin")) == 2


def test_web20_retry_backoff_uses_next_retry_at():
    uid = 3
    acc = w20_store.create_manual_account(user_id=uid, label="GS")
    post = w20_store.create_post(user_id=uid, account_id=acc["id"], title="T", html_content="<p>x</p>")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    w20_store.update_post(post["id"], uid, {"status": "retrying", "retry_count": 1, "next_retry_at": future})
    due = w20_store.list_retrying_posts(now=datetime.now(timezone.utc))
    assert not any(str(x.get("id")) == str(post["id"]) for x in due)
