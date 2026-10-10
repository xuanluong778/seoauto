"""Tests for Chatbot CSKH knowledge retrieval (SEO training query)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chatbot_cskh_entitlement import NO_DATA_REPLY, build_no_data_reply
from app.services.chatbot_cskh_retrieval import resolve_public_phone


def test_build_no_data_reply_includes_phone():
    reply = build_no_data_reply("0934.077.360")
    assert NO_DATA_REPLY in reply
    assert "0934.077.360" in reply
    assert "liên hệ" in reply.lower()


def test_resolve_public_phone_from_kb_content():
    bot = SimpleNamespace(
        hotline="",
        main_services="",
        website_url="https://thegioidigi.com",
    )
    kb_chunks = [
        {
            "title": "Liên hệ",
            "content": "Số điện thoại chính | 0934.077.360 | Hotline 0976086500",
        }
    ]
    phone = resolve_public_phone(bot, kb_chunks=kb_chunks)
    assert phone.startswith("0")
    assert len(phone.replace(".", "")) >= 10


def test_seo_training_query_finds_kb_content():
    """Mandatory test case: đào tạo SEO must hit thegioidigi KB chunks."""
    from app.services.shared_knowledge import (
        _all_docs,
        _score_text_block,
        _tokenize,
    )

    kb_id = "295cd663-bfdf-42fe-b24e-21bd0bfa6064"
    query = "Tôi muốn hỏi về dịch vụ đào tạo SEO"
    tokens = _tokenize(query)
    hits: list[tuple[int, str, str]] = []
    for doc in _all_docs(kb_id):
        title = str(doc.get("title") or "")
        for ch in doc.get("chunks") or []:
            text = str(ch.get("text") or "")
            score = _score_text_block(title, text, query, tokens)
            if score > 0:
                hits.append((score, title, text))
    hits.sort(key=lambda x: -x[0])
    assert hits, "Expected KB chunks for đào tạo SEO query"
    best_text = hits[0][2].lower()
    assert "seo" in best_text
    assert "đào tạo" in best_text or "khóa học" in best_text
    assert hits[0][0] >= 3
