"""Tests for write tab workflows (quick vs deep)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.chatbot_tab_registry import (
    INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
    INTENT_QUICK_KEYWORD_ARTICLE,
    estimate_workflow_credits,
    init_progress_for_intent,
    validate_prepare_params,
)
from app.services.chatbot_write_planner import build_quick_planning


def test_write_progress_has_five_steps():
    steps = init_progress_for_intent(INTENT_QUICK_KEYWORD_ARTICLE)
    assert [s["id"] for s in steps] == ["outline", "credits", "writing", "images", "complete"]


def test_validate_quick_write_params():
    out = validate_prepare_params(
        INTENT_QUICK_KEYWORD_ARTICLE,
        {
            "primary_keyword": "dịch vụ SEO",
            "word_count_preset": "2000",
            "image_source": "google",
            "tone": "chuyên gia",
        },
    )
    assert out["primary_keyword"] == "dịch vụ SEO"
    assert out["word_count"] == 2000
    assert out["include_images"] is True
    assert out["tone"] == "chuyên gia"


def test_validate_custom_word_count():
    out = validate_prepare_params(
        INTENT_QUICK_KEYWORD_ARTICLE,
        {
            "primary_keyword": "seo onpage",
            "word_count_preset": "custom",
            "word_count_custom": 1800,
            "image_source": "none",
        },
    )
    assert out["word_count"] == 1800
    assert out["include_images"] is False


def test_validate_word_count_field_only():
    out = validate_prepare_params(
        INTENT_QUICK_KEYWORD_ARTICLE,
        {
            "keyword": "sửa máy tính",
            "word_count": 1750,
            "image_source": "google",
            "tone": "Chuyên nghiệp",
        },
    )
    assert out["keyword"] == "sửa máy tính"
    assert out["word_count"] == 1750
    assert out["tone"] == "Chuyên nghiệp"
    assert out["word_count_preset"] == "custom"


def test_quick_credits_lower_than_deep():
    params = {
        "primary_keyword": "seo",
        "word_count": 1500,
        "image_source": "google",
        "include_images": True,
    }
    quick = estimate_workflow_credits(INTENT_QUICK_KEYWORD_ARTICLE, params)
    deep = estimate_workflow_credits(INTENT_KEYWORD_CLUSTER_TO_ARTICLE, params)
    assert quick["research"] == 0
    assert quick["clustering"] == 0
    assert deep["research"] > 0
    assert deep["clustering"] > 0
    assert quick["total"] < deep["total"]


@patch("app.services.chatbot_write_planner.suggest_content_ai_field")
def test_build_quick_planning(mock_suggest):
    mock_suggest.side_effect = lambda **kw: {
        "title": "Tiêu đề test",
        "meta_description": "Meta test",
        "secondary_keywords": "kw1, kw2",
        "outline_content": "<h2>Intro</h2>",
    }.get(kw.get("field"), "")

    plan = build_quick_planning({"primary_keyword": "seo tool", "language": "vi"})
    assert plan["mode"] == "quick"
    assert plan["title"] == "Tiêu đề test"
    assert plan["outline"] == "<h2>Intro</h2>"
    assert plan["secondary_keywords"] == ["kw1", "kw2"]
