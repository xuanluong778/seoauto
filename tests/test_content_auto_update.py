"""Content Auto Update — backup, slug parsing, publish guard."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import content_backup as backup
from app.services import content_publish as publish
from app.services.wp_site_connector import _slug_from_url


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    backups = tmp_path / "backups.json"
    sessions = tmp_path / "sessions.json"
    history = tmp_path / "history.json"
    monkeypatch.setattr(backup, "BACKUPS_FILE", backups)
    monkeypatch.setattr(backup, "SESSIONS_FILE", sessions)
    monkeypatch.setattr(backup, "HISTORY_FILE", history)
    backups.write_text("[]", encoding="utf-8")
    sessions.write_text("[]", encoding="utf-8")
    history.write_text("[]", encoding="utf-8")
    yield


def test_slug_from_url_matches_site_host():
    base = "https://example.com"
    assert _slug_from_url("https://example.com/blog/my-post/", base) == "my-post"
    assert _slug_from_url("https://other.com/my-post/", base) == ""


def test_create_backup_requires_old_fields():
    with pytest.raises(HTTPException) as exc:
        backup.create_backup(
            user_id=1,
            session_id="sess-1",
            site_id="site-1",
            wp_id=10,
            post_type="post",
            post_url="https://example.com/p",
            snapshot={"old_title": "T", "old_content": "C"},
        )
    assert exc.value.status_code == 400


def test_publish_blocked_without_backup(monkeypatch):
    monkeypatch.setattr(
        publish,
        "get_site_credentials",
        lambda site_id, user_id: {
            "url": "https://example.com",
            "username": "u",
            "app_password": "pwd",
        },
    )
    with pytest.raises(HTTPException) as exc:
        publish.publish_update(
            user_id=1,
            site_id="site-1",
            backup_id="missing",
            wp_id=10,
            post_type="post",
            title="New",
            content="Body",
            excerpt="",
            mode="draft",
        )
    assert exc.value.status_code == 400
    assert "backup" in str(exc.value.detail).lower()


def test_publish_requires_matching_wp_id(monkeypatch):
    b = backup.create_backup(
        user_id=1,
        session_id="sess-1",
        site_id="site-1",
        wp_id=10,
        post_type="post",
        post_url="https://example.com/p",
        snapshot={
            "old_title": "Old",
            "old_content": "Old body",
            "old_excerpt": "Ex",
            "old_status": "publish",
        },
    )
    monkeypatch.setattr(publish, "get_backup", lambda bid, uid: b)
    monkeypatch.setattr(
        publish,
        "get_site_credentials",
        lambda site_id, user_id: {
            "url": "https://example.com",
            "username": "u",
            "app_password": "pwd",
        },
    )
    with pytest.raises(HTTPException) as exc:
        publish.publish_update(
            user_id=1,
            site_id="site-1",
            backup_id=b["id"],
            wp_id=99,
            post_type="post",
            title="New",
            content="Body",
            excerpt="",
            mode="draft",
        )
    assert exc.value.status_code == 400
