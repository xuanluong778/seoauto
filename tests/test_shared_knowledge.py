"""Shared AI Knowledge Base is the single source for Chatbot + Content AI."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import ai_knowledge_docs as docs
from app.services import ai_knowledge_store as store
from app.services import shared_knowledge as shared_kb


@pytest.fixture()
def kb_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "KB_FILE", tmp_path / "ai_knowledge_bases.json")
    monkeypatch.setattr(docs, "DOCS_DIR", tmp_path / "knowledge_docs")
    monkeypatch.setattr(docs, "_embed_chunks", lambda chunks: None)
    return tmp_path


def test_ensure_creates_one_default_kb(kb_dirs: Path):
    a = shared_kb.ensure_user_knowledge_base(11)
    b = shared_kb.ensure_user_knowledge_base(11)
    assert a["id"] == b["id"]
    assert a["scope"] == "user"
    assert a["user_id"] == 11
    assert a["is_default"] is True
    listed = [x for x in store.list_bases(user_id=11, role="user") if x.get("scope") == "user"]
    assert len(listed) == 1


def test_upsert_same_source_key_does_not_duplicate(kb_dirs: Path):
    n1 = shared_kb.upsert_document(
        11,
        title="Bảng giá sửa laptop",
        content="Sửa mainboard laptop từ 800.000đ.",
        source_key="cskh_node:11:99",
        tags=["bảng giá"],
    )
    n2 = shared_kb.upsert_document(
        11,
        title="Bảng giá sửa laptop",
        content="Sửa mainboard laptop từ 900.000đ.",
        source_key="cskh_node:11:99",
        tags=["bảng giá"],
    )
    assert n1["id"] == n2["id"]
    assert "900.000" in n2["content"]
    kid = shared_kb.user_kb_id(11)
    assert len(docs._read_store(kid).get("documents") or []) == 1


def test_search_and_users_are_isolated(kb_dirs: Path):
    shared_kb.upsert_document(
        11,
        title="Chính sách bảo hành",
        content="Bảo hành 6 tháng cho dịch vụ sửa chữa máy in.",
        source_key="cskh_src:11:1",
    )
    shared_kb.upsert_document(
        22,
        title="Chính sách khác",
        content="User 22 có nội dung riêng không liên quan máy in.",
        source_key="cskh_src:22:1",
    )
    hits = shared_kb.search_user_knowledge(11, "bảo hành máy in")
    assert hits
    assert hits[0]["title"] == "Chính sách bảo hành"
    other = shared_kb.search_user_knowledge(22, "bảo hành máy in")
    assert all("máy in" not in (h.get("content") or "").lower() or h["title"] != "Chính sách bảo hành" for h in other)
    assert store.get_base(shared_kb.user_kb_id(11), user_id=22, role="user") is None


def test_search_kb_nodes_reads_shared_ai_kb(kb_dirs: Path, monkeypatch: pytest.MonkeyPatch):
    shared_kb.upsert_document(
        11,
        title="FAQ giá",
        content="Giá vệ sinh máy lạnh 350.000đ/lần.",
        source_key="cskh_node:11:1",
    )
    monkeypatch.setattr(shared_kb, "migrate_legacy_chatbot_kb", lambda *a, **k: {"nodes": 0, "sources": 0, "skipped": 0})
    from app.services.chatbot_cskh_kb_service import _search_kb_nodes_db

    rows = _search_kb_nodes_db(db=None, bot_id=1, user_id=11, query="giá vệ sinh máy lạnh", limit=5)
    assert rows
    assert rows[0]["source"] == "kb_map"
    assert "350.000" in rows[0]["content"]


def test_retrieve_knowledge_does_not_double_hit_sources(kb_dirs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.chatbot_cskh_ai_service.search_kb_nodes",
        lambda *a, **k: [{"title": "KB", "content": "Giá 100k", "score": 2}],
    )
    from app.services.chatbot_cskh_ai_service import _retrieve_knowledge

    kb_chunks, source_chunks = _retrieve_knowledge(db=None, bot_id=1, user_id=11, query="giá")
    assert kb_chunks
    assert source_chunks == []


def test_search_reads_non_default_kb(kb_dirs: Path):
    shared_kb.ensure_user_knowledge_base(11)
    other = store.create_base(
        {"name": "Website KB", "scope": "user", "enabled": True, "website_url": "https://example.com"},
        user_id=11,
        role="user",
    )
    docs.import_text(other["id"], "Bảng giá vệ sinh máy lạnh", "Giá vệ sinh máy lạnh 350.000đ/lần.", embed=False)
    hits = shared_kb.search_user_knowledge(11, "giá vệ sinh máy lạnh")
    assert any("350.000" in (h.get("content") or "") for h in hits)
    other_user = shared_kb.search_user_knowledge(22, "giá vệ sinh máy lạnh")
    assert all("350.000" not in (h.get("content") or "") for h in other_user)


def test_search_keeps_matching_tail_past_old_4000_cap(kb_dirs: Path):
    body = "Giá dịch vụ: 350.000đ. " + ("x" * 5000) + " Mã bảo hành UNIQUE123."
    shared_kb.upsert_document(11, title="Hợp đồng dài", content=body, source_key="cskh_node:11:long")
    hits = shared_kb.search_user_knowledge(11, "UNIQUE123")
    assert hits
    assert "UNIQUE123" in hits[0]["content"]


def test_kb_write_invalidates_chatbot_search_cache(kb_dirs: Path):
    from app.services.chatbot_kb_cache import get_cached_search, make_search_key, set_cached_search

    shared_kb.upsert_document(11, title="Giá cũ", content="Giá cũ 100k", source_key="cskh_node:11:cache")
    key = make_search_key(user_id=11, query="giá", limit=5)
    set_cached_search(1, key, [{"title": "stale", "content": "Giá cũ 100k"}])
    assert get_cached_search(1, key) is not None
    shared_kb.upsert_document(11, title="Giá mới", content="Giá mới 999k", source_key="cskh_node:11:cache")
    assert get_cached_search(1, key) is None
    hits = shared_kb.search_user_knowledge(11, "giá mới")
    assert any("999k" in (h.get("content") or "") for h in hits)


def test_content_ai_and_chatbot_share_non_default_kb(kb_dirs: Path):
    shared_kb.ensure_user_knowledge_base(11)
    other = store.create_base(
        {
            "name": "Site KB",
            "scope": "user",
            "enabled": True,
            "website_url": "https://example.com",
            "brand_name": "Example Co",
        },
        user_id=11,
        role="user",
    )
    docs.import_text(other["id"], "Bảng giá sửa laptop", "Bảng giá sửa laptop 800.000đ / lần.", embed=False)
    from app.services.content_ai_knowledge_context import (
        build_outline_context_from_knowledge,
        get_relevant_knowledge_for_keyword,
    )

    kn = get_relevant_knowledge_for_keyword("sửa laptop", target_website="https://example.com", user_id=11)
    assert kn.get("found") is True
    blob = str(kn.get("sections") or {}) + str(kn.get("hits") or [])
    assert "800.000" in blob
    outline = build_outline_context_from_knowledge(kn)
    assert "800.000" in outline
    hits = shared_kb.search_user_knowledge(11, "sửa laptop")
    assert any("800.000" in (h.get("content") or "") for h in hits)


def test_chatbot_search_skips_global_inherited(kb_dirs: Path):
    g = store.create_base(
        {"name": "Global KB", "scope": "global", "enabled": True, "inherit_mode": "all"},
        user_id=1,
        role="admin",
    )
    docs.import_text(g["id"], "Global secret", "Mã bí mật GLOBALXYZ không thuộc khách hàng.", embed=False)
    shared_kb.upsert_document(11, title="Giá nội bộ", content="Sửa quạt 50k", source_key="cskh_node:11:own")
    hits = shared_kb.search_user_knowledge(11, "GLOBALXYZ")
    assert all("GLOBALXYZ" not in (h.get("content") or "") for h in hits)
    own = shared_kb.search_user_knowledge(11, "sửa quạt")
    assert any("50k" in (h.get("content") or "") for h in own)
