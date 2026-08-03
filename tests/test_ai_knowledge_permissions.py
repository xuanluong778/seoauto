"""Phân quyền & kế thừa AI Knowledge Base."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import ai_knowledge_store as store


@pytest.fixture()
def kb_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "ai_knowledge_bases.json"
    monkeypatch.setattr(store, "KB_FILE", path)
    return path


def _write(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def test_user_cannot_read_other_users_kb(kb_file: Path):
    _write(
        kb_file,
        [
            {"id": "u1-kb", "user_id": 1, "scope": "user", "name": "User1 KB", "enabled": True},
            {"id": "u2-kb", "user_id": 2, "scope": "user", "name": "User2 KB", "enabled": True},
        ],
    )
    assert store.get_base("u2-kb", user_id=1, role="user") is None
    ids = [x["id"] for x in store.list_bases(user_id=1, role="user")]
    assert "u2-kb" not in ids
    assert "u1-kb" in ids


def test_admin_sees_all_user_kbs(kb_file: Path):
    _write(
        kb_file,
        [
            {"id": "u1-kb", "user_id": 1, "scope": "user", "name": "A", "enabled": True},
            {"id": "u2-kb", "user_id": 2, "scope": "user", "name": "B", "enabled": True},
        ],
    )
    ids = {x["id"] for x in store.list_bases(user_id=99, role="admin")}
    assert ids == {"u1-kb", "u2-kb"}


def test_global_inherited_read_only_for_user(kb_file: Path):
    _write(
        kb_file,
        [
            {
                "id": "g1",
                "user_id": 0,
                "scope": "global",
                "inherit_mode": "all",
                "name": "Global KB",
                "enabled": True,
            },
            {"id": "u1", "user_id": 5, "scope": "user", "name": "Mine", "enabled": True},
        ],
    )
    item = store.get_base("g1", user_id=5, role="user")
    assert item is not None
    assert item["is_inherited"] is True
    assert item["can_edit"] is False
    assert item["inheritance_label"] == "Kế thừa từ hệ thống"
    with pytest.raises(PermissionError):
        store.delete_base("g1", user_id=5, role="user")


def test_only_admin_writes_global(kb_file: Path):
    _write(
        kb_file,
        [
            {
                "id": "g1",
                "user_id": 0,
                "scope": "global",
                "inherit_mode": "all",
                "name": "Global",
                "enabled": True,
            },
        ],
    )
    with pytest.raises(PermissionError):
        store.update_base("g1", {"name": "Hack"}, user_id=3, role="user")
    updated = store.update_base("g1", {"name": "Global OK"}, user_id=1, role="admin")
    assert updated and updated["name"] == "Global OK"


def test_global_match_by_website(kb_file: Path):
    _write(
        kb_file,
        [
            {
                "id": "g-match",
                "user_id": 0,
                "scope": "global",
                "inherit_mode": "match",
                "website_url": "https://example.com",
                "name": "Matched",
                "enabled": True,
            },
            {
                "id": "u-kb",
                "user_id": 7,
                "scope": "user",
                "website_url": "https://www.example.com",
                "name": "User site",
                "enabled": True,
            },
        ],
    )
    ids = [x["id"] for x in store.list_bases(user_id=7, role="user")]
    assert "g-match" in ids
    ids2 = [x["id"] for x in store.list_bases(user_id=8, role="user")]
    assert "g-match" not in ids2


def test_user_can_clone_inherited_global(kb_file: Path, monkeypatch: pytest.MonkeyPatch):
    from app.services import ai_knowledge_docs as docs

    _write(
        kb_file,
        [
            {
                "id": "g1",
                "user_id": 0,
                "scope": "global",
                "inherit_mode": "all",
                "name": "Global",
                "brand_name": "Brand",
                "enabled": True,
            },
        ],
    )
    monkeypatch.setattr(docs, "clone_kb_docs", lambda s, t: {"documents": 1, "chunks": 2, "embeddings_done": 0, "embeddings_total": 2, "tokens": 10})
    cloned = store.clone_base("g1", user_id=4, role="user", name="My copy")
    assert cloned["scope"] == "user"
    assert cloned["user_id"] == 4
    assert cloned["can_edit"] is True
    assert cloned["cloned_from"] == "g1"


def test_idor_update_other_user_kb(kb_file: Path):
    _write(
        kb_file,
        [{"id": "x", "user_id": 2, "scope": "user", "name": "Other", "enabled": True}],
    )
    with pytest.raises(PermissionError):
        store.update_base("x", {"name": "Stolen"}, user_id=1, role="user")
    assert store.get_base("x", user_id=1, role="user") is None
