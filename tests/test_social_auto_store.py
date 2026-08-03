"""Social Auto store — unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import social_auto_store as store


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    camp = tmp_path / "campaigns.json"
    posts = tmp_path / "posts.json"
    monkeypatch.setattr(store, "CAMPAIGNS_FILE", camp)
    monkeypatch.setattr(store, "POSTS_FILE", posts)
    camp.write_text("[]", encoding="utf-8")
    posts.write_text("[]", encoding="utf-8")
    yield


def test_campaign_and_post_flow():
    uid = 42
    c = store.create_campaign(
        user_id=uid,
        name="Test camp",
        source_title="Title",
        source_content="Body text",
        keyword="seo",
        target_url="https://example.com/a",
    )
    assert c["user_id"] == uid
    p = store.create_post(
        user_id=uid,
        campaign_id=c["id"],
        platform="facebook",
        title="FB",
        content="Hello",
    )
    assert p["status"] == "draft"
    store.schedule_post(p["id"], uid, "2026-06-15T09:00:00+00:00")
    scheduled = store.list_posts(uid, status="scheduled")
    assert len(scheduled) == 1
    store.mark_published(p["id"], uid, "https://facebook.com/post/1")
    stats = store.get_overview_stats(uid)
    assert stats["campaigns"] == 1
    assert stats["published"] == 1


def test_user_isolation():
    c1 = store.create_campaign(user_id=1, name="A", source_title="A")
    c2 = store.create_campaign(user_id=2, name="B", source_title="B")
    assert len(store.list_campaigns(1)) == 1
    assert store.list_campaigns(1)[0]["id"] == c1["id"]
    assert store.list_campaigns(2)[0]["id"] == c2["id"]
