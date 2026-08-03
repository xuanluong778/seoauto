"""Social Auto safety checks."""

from __future__ import annotations

import pytest

from app.services import social_auto_facebook_store as fb_store
from app.services import social_auto_safety as safety
from app.services import social_auto_store as store


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    camp = tmp_path / "c.json"
    posts = tmp_path / "p.json"
    settings = tmp_path / "s.json"
    monkeypatch.setattr(store, "CAMPAIGNS_FILE", camp)
    monkeypatch.setattr(store, "POSTS_FILE", posts)
    monkeypatch.setattr(fb_store, "SETTINGS_FILE", settings)
    camp.write_text("[]", encoding="utf-8")
    posts.write_text("[]", encoding="utf-8")
    settings.write_text("{}", encoding="utf-8")
    yield


def test_duplicate_content_blocked():
    uid = 7
    c = store.create_campaign(user_id=uid, name="c", source_title="T")
    p = store.create_post(
        user_id=uid,
        campaign_id=c["id"],
        platform="facebook",
        title="Same",
        content="Hello world post",
        status="published",
        page_id="p1",
    )
    store.update_post(p["id"], uid, {"page_id": "p1"})
    r = safety.check_duplicate_content(uid, "Same\nHello world post\n", page_id="p1")
    assert r["ok"] is False


def test_hashtag_spam():
    r = safety.check_hashtag_spam("#a #b #c #d #e #f #g #h #i")
    assert r["ok"] is False


def test_posting_density_limit():
    uid = 3
    from app.services.social_auto_facebook_store import save_safety_settings

    save_safety_settings(uid, {"max_posts_per_day": 2, "min_hours_between_posts": 3})
    c = store.create_campaign(user_id=uid, name="c", source_title="T")
    p1 = store.create_post(user_id=uid, campaign_id=c["id"], platform="facebook", title="a", content="x", page_id="pg1")
    store.update_post(p1["id"], uid, {"page_id": "pg1"})
    store.schedule_post(p1["id"], uid, "2026-06-15T10:00:00+00:00")
    r = safety.check_posting_density(uid, "2026-06-15T11:00:00+00:00", page_id="pg1")
    assert r["ok"] is False
