"""Chatbot content must not save LLM stub fallback when target word count is set."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.content_ai_bulk_runner import (
    _fallback_content_html,
    _is_stub_content_html,
    ensure_article_content_word_count,
)


def test_stub_detector_matches_fallback_html():
    stub = _fallback_content_html(
        primary_keyword="sửa máy tính bình dương",
        title="Tiêu đề test",
        outline_content="NGÀNH/DỊCH VỤ: IT\nKHU VỰC: quận thủ đức",
    )
    assert _is_stub_content_html(stub) is True


@patch("app.services.llm_content_writer.generate_content_ai_suggestion")
@patch("app.services.llm_content_writer.enforce_content_ai_word_count")
def test_ensure_regenerates_stub_content(mock_enforce, mock_gen):
    import app.services.llm_content_writer  # noqa: F401 — ensure patch target is loaded
    stub = _fallback_content_html(
        primary_keyword="sửa máy tính",
        title="Test",
        outline_content="Giới thiệu",
    )
    long_html = "<h1>Test</h1><p>" + "từ vựng seo marketing " * 280 + "</p>"
    mock_gen.return_value = long_html
    mock_enforce.return_value = (long_html, {"actual_word_count": 1000})

    out = ensure_article_content_word_count(
        content_html=stub,
        target_word_count=1000,
        primary_keyword="sửa máy tính",
        title="Test",
        use_system_llm=True,
    )
    assert _is_stub_content_html(out) is False
    mock_gen.assert_called_once()


@patch("app.services.llm_content_writer.generate_content_ai_suggestion")
@patch("app.services.llm_content_writer.enforce_content_ai_word_count")
def test_ensure_raises_when_still_short(mock_enforce, mock_gen):
    stub = _fallback_content_html(primary_keyword="kw", title="t", outline_content="a")
    mock_gen.return_value = stub
    mock_enforce.return_value = (stub, {"actual_word_count": 50})

    with pytest.raises(RuntimeError, match="Không sinh được bài đủ"):
        ensure_article_content_word_count(
            content_html=stub,
            target_word_count=1000,
            primary_keyword="kw",
            title="t",
            use_system_llm=True,
        )
