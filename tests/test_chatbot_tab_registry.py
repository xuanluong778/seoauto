"""Tests for chatbot tab registry and prepare API."""

from __future__ import annotations

from app.services.chatbot_tab_registry import (
    INTENT_KEYWORD_RESEARCH,
    INTENT_URL_SEO_SCOREBOARD,
    estimate_workflow_credits,
    validate_prepare_params,
)


def test_validate_url_seo_params():
    out = validate_prepare_params(INTENT_URL_SEO_SCOREBOARD, {"url": "https://example.com", "keyword": "seo"})
    assert out["url"] == "https://example.com"
    assert out["keyword"] == "seo"


def test_validate_keyword_research_params():
    out = validate_prepare_params(INTENT_KEYWORD_RESEARCH, {"seed_keyword": "crm software"})
    assert out["seed_keyword"] == "crm software"
    assert out["include_clustering"] is False


def test_estimate_url_seo_credits():
    est = estimate_workflow_credits(INTENT_URL_SEO_SCOREBOARD, {"url": "https://a.com"})
    assert est["total"] >= 0
    assert "seo_score" in est
