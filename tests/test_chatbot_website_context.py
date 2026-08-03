"""Tests for chatbot website context service."""

from __future__ import annotations

import pytest

from app.services.chatbot_tab_registry import validate_prepare_params, INTENT_QUICK_KEYWORD_ARTICLE
from app.services.chatbot_website_context import (
    AMBIGUOUS_KEYWORD_PREFIX,
    is_ambiguous_keyword,
    prepare_write_params_with_website_context,
    validate_content_alignment,
    build_vertical_context,
)


def test_is_ambiguous_keyword_entity():
    assert is_ambiguous_keyword("Dịch vụ Entity") is True
    assert is_ambiguous_keyword("dịch vụ seo tại tphcm") is False


def test_validate_prepare_params_includes_website_url():
    out = validate_prepare_params(
        INTENT_QUICK_KEYWORD_ARTICLE,
        {
            "primary_keyword": "seo onpage",
            "website_url": "example.com",
            "word_count": 1500,
            "image_source": "none",
        },
    )
    assert out["website_url"].startswith("https://")
    assert out["target_website"]


def test_ambiguous_without_website_raises():
    with pytest.raises(ValueError) as exc:
        prepare_write_params_with_website_context(
            {"primary_keyword": "Dịch vụ Entity", "word_count": 1500}
        )
    assert AMBIGUOUS_KEYWORD_PREFIX in str(exc.value)


def test_ambiguous_with_vertical_ok():
    out = prepare_write_params_with_website_context(
        {
            "primary_keyword": "Dịch vụ Entity",
            "business_vertical": "seo_entity",
            "word_count": 1500,
        }
    )
    assert out["website_context"]["industry_key"] == "seo_entity"


def test_content_alignment_detects_wrong_industry():
    ctx = build_vertical_context("seo_entity")
    ok, reason = validate_content_alignment(
        "<p>Dịch vụ sửa máy tính quận 1 uy tín, thay màn hình laptop nhanh.</p>",
        website_context=ctx,
        primary_keyword="Dịch vụ Entity",
    )
    assert ok is False
    assert reason
