"""Content AI SEO brief."""

import pytest

from app.services.content_ai_brief import generate_content_brief


def test_missing_keyword_raises():
    with pytest.raises(ValueError, match="từ khóa"):
        generate_content_brief(primary_keyword="")


def test_generates_brief_with_keyword():
    out = generate_content_brief(
        primary_keyword="dịch vụ seo tại hà nội",
        secondary_keywords="seo on-page, audit",
        target_word_count=1200,
    )
    assert out["search_intent"]
    assert out["content_type"]
    assert out["outline"]
    assert isinstance(out["faq_questions"], list)
    assert out["brief_mode"] == "rule_based"


def test_internal_link_plan_only_from_candidates():
    invented = generate_content_brief(
        primary_keyword="seo test",
        internal_link_candidates=None,
    )
    assert invented["internal_link_plan"] == []

    with_links = generate_content_brief(
        primary_keyword="seo test",
        internal_link_candidates=[
            {"url": "https://example.com/blog/a", "title": "Bài A", "anchor_text": "SEO on-page"},
            {"url": "https://example.com/service/b", "anchor_text": "dịch vụ B"},
        ],
    )
    plan = with_links["internal_link_plan"]
    assert len(plan) == 2
    urls = {p["url"] for p in plan}
    assert "https://example.com/blog/a" in urls
    assert "https://example.com/service/b" in urls
    assert all(p.get("source") == "internal_link_candidates" for p in plan)
    assert not any("fake-internal" in u for u in urls)


def test_competitor_failure_does_not_crash():
    out = generate_content_brief(
        primary_keyword="seo test keyword",
        competitor_url="https://invalid.example.invalid/page",
    )
    assert out["outline"]
    assert any("đối thủ" in w.lower() or "crawl" in w.lower() for w in out["warnings"]) or out[
        "competitor_headings_used"
    ] == 0
