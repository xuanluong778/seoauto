"""Tests for 10-group URL SEO scoring."""

from __future__ import annotations

from app.schemas.url_scoreboard import UrlSeoScoreboardRequest, UrlSeoScoreboardResponse
from app.services.url_seo_ten_group_scoring import (
    GROUP_LABELS,
    GROUP_WEIGHTS,
    analyze_page_links,
    build_ten_group_scoreboard,
    ensure_ten_groups_complete,
)


def test_group_weights_sum_to_100():
    assert abs(sum(GROUP_WEIGHTS.values()) - 100.0) < 0.01
    assert GROUP_WEIGHTS["links"] == 8.0
    assert GROUP_LABELS["links"] == "Internal / External Link"


def _build_board(html: str, **kwargs):
    defaults = {
        "url": "https://example.com/dich-vu-seo",
        "normalized_url": "https://example.com/dich-vu-seo",
        "fetch": {"ok": True, "status": 200, "final_url": "https://example.com/dich-vu-seo"},
        "page_data": {
            "title": "Dịch vụ SEO website chuyên nghiệp tại Việt Nam",
            "meta_description": "Dịch vụ SEO website giúp doanh nghiệp tăng traffic organic.",
            "canonical": "https://example.com/dich-vu-seo",
            "h1_count": 1,
            "h2_count": 2,
            "word_count": 120,
            "images_total": 1,
            "images_missing_alt": 0,
        },
        "content_pkg": {"word_count": 120, "content_depth": "thin", "heading_structure_score": 0.7},
        "html": html,
        "headers": {},
        "ld_blocks": [{"@type": "WebPage"}],
        "soup": None,
        "primary_keyword": "dịch vụ seo website",
        "secondary_keywords": ["seo onpage", "audit technical"],
        "page_type": "landing",
        "breakdown": {"intent": {"page_intent": {"intent": "commercial"}}, "structure": {}},
        "legacy_issues": [],
        "serp_intent_pkg": {"serp_intent": "commercial"},
    }
    defaults.update(kwargs)
    return build_ten_group_scoreboard(**defaults)


def test_analyze_page_links_with_internal_and_external():
    html = """<html><body>
    <a href="/blog">Blog nội bộ</a>
    <a href="https://example.com/about">About</a>
    <a href="https://google.com" rel="nofollow">Google</a>
    </body></html>"""
    profile = analyze_page_links(html, "https://example.com/page")
    assert profile["internal_links_count"] >= 2
    assert profile["external_links_count"] >= 1
    assert profile["partial_data"] is False
    assert profile["nofollow_count"] >= 1
    assert profile["anchor_texts"]


def test_analyze_page_links_few_links():
    html = """<html><body><a href="/only-one">One</a></body></html>"""
    profile = analyze_page_links(html, "https://example.com/page")
    assert profile["internal_links_count"] == 1
    assert profile["external_links_count"] == 0
    assert profile["partial_data"] is False
    assert profile["link_opportunities"]


def test_analyze_page_links_no_html_partial():
    profile = analyze_page_links("", "https://example.com/page")
    assert profile["partial_data"] is True
    assert profile["warning"] == "Chưa đủ dữ liệu để đánh giá link"
    assert profile["internal_links_count"] == 0


def test_ensure_ten_groups_complete_always_includes_links():
    groups = ensure_ten_groups_complete([])
    assert len(groups) == 10
    links = next(g for g in groups if g["id"] == "links")
    assert links["label"] == "Internal / External Link"
    assert links["weight"] == 8.0
    assert links["partial_data"] is True


def test_total_score_matches_links_contribution():
    html = """<!DOCTYPE html><html lang="vi"><head>
    <title>Dịch vụ SEO website chuyên nghiệp tại Việt Nam</title>
    <meta name="description" content="Dịch vụ SEO website giúp doanh nghiệp tăng traffic organic với chiến lược onpage và content chất lượng cao, tối ưu chuyển đổi.">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="https://example.com/dich-vu-seo">
    </head><body>
    <h1>Dịch vụ SEO website</h1>
    <h2>Lợi ích</h2><h2>Quy trình</h2>
    <p>Dịch vụ SEO website bao gồm audit technical, content và link building cho doanh nghiệp.</p>
    <img src="/a.jpg" alt="seo"><a href="/blog">Blog</a><a href="https://google.com">Ref</a>
  </body></html>"""
    out = _build_board(
        html,
        content_pkg={"word_count": 900, "content_depth": "adequate", "heading_structure_score": 0.7},
        page_data={
            "title": "Dịch vụ SEO website chuyên nghiệp tại Việt Nam",
            "meta_description": "Dịch vụ SEO website giúp doanh nghiệp tăng traffic organic.",
            "canonical": "https://example.com/dich-vu-seo",
            "h1_count": 1,
            "h2_count": 2,
            "word_count": 900,
            "images_total": 1,
            "images_missing_alt": 0,
        },
    )
    links = next(g for g in out["groups"] if g["id"] == "links")
    assert links["label"] == "Internal / External Link"
    assert links.get("link_data")
    assert links["link_data"]["internal_links_count"] >= 1
    weighted_sum = round(sum(float(g.get("weighted_points") or 0) for g in out["groups"]), 1)
    assert abs(weighted_sum - out["total_score"]) <= 0.1
    assert out["group_scores"]["links"] == links["score"]
    assert links["weighted_points"] == round(links["score"] * GROUP_WEIGHTS["links"] / 100.0, 2)


def test_ten_group_scoreboard_shape():
    html = """<!DOCTYPE html><html lang="vi"><head>
    <title>Dịch vụ SEO website chuyên nghiệp tại Việt Nam</title>
    <meta name="description" content="Dịch vụ SEO website giúp doanh nghiệp tăng traffic organic với chiến lược onpage và content chất lượng cao, tối ưu chuyển đổi.">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="https://example.com/dich-vu-seo">
    </head><body>
    <h1>Dịch vụ SEO website</h1>
    <h2>Lợi ích</h2><h2>Quy trình</h2>
    <p>Dịch vụ SEO website bao gồm audit technical, content và link building cho doanh nghiệp.</p>
    <img src="/a.jpg" alt="seo"><a href="/blog">Blog</a><a href="https://google.com">Ref</a>
  </body></html>"""
    out = _build_board(html)
    assert 0 <= out["total_score"] <= 100
    assert len(out["groups"]) == 10
    assert out["group_scores"]["indexability"] is not None
    assert isinstance(out["strengths"], list)
    assert isinstance(out["weaknesses"], list)
    assert isinstance(out["priority_fixes"], list)
    assert isinstance(out["ai_suggestions"], list)
    for g in out["groups"]:
        assert g["checks"]
        if g["id"] == "links":
            assert g["label"] == "Internal / External Link"
            assert g["weight"] == 8.0
            assert "link_data" in g
        for c in g["checks"]:
            assert c["status"] in ("passed", "warning", "failed")
            assert "fix" in c


def test_request_schema_accepts_new_fields():
    m = UrlSeoScoreboardRequest.model_validate(
        {
            "url": "https://example.com",
            "keyword": "seo",
            "secondary_keywords": ["onpage", "technical"],
            "page_type": "article",
        }
    )
    assert m.page_type == "article"
    assert len(m.secondary_keywords or []) == 2


def test_response_schema_accepts_ten_group():
    minimal = {
        "url": "https://x.com",
        "normalized_url": "https://x.com",
        "fetch": {},
        "scores": {"total": 50.0, "components": {}},
        "breakdown": {},
        "issues": [],
        "serp": None,
        "opportunity": None,
        "weights": {},
        "pillar_definitions": {},
        "page_snapshot": {},
        "fifteen_pillar_assessment": {},
        "serp_top10_crawl": {},
        "optimization_report": {},
        "ten_group_scoreboard": {"total_score": 55, "groups": []},
        "generated_at": "2026-01-01T00:00:00+00:00",
    }
    UrlSeoScoreboardResponse.model_validate(minimal)
