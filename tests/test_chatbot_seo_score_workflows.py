"""Tests for chatbot SEO Score tab workflows."""

from __future__ import annotations

from app.services.chatbot_seo_score_report import (
    build_chatbot_seo_report_from_content,
    build_chatbot_seo_report_from_url,
)
from app.services.chatbot_tab_registry import (
    INTENT_CONTENT_SEO_SCORE,
    INTENT_URL_SEO_SCOREBOARD,
    estimate_workflow_credits,
    init_progress_for_intent,
    validate_prepare_params,
)


def test_url_score_progress_has_crawl():
    steps = init_progress_for_intent(INTENT_URL_SEO_SCOREBOARD)
    assert [s["id"] for s in steps] == ["crawl", "analyze", "complete"]


def test_content_score_progress():
    steps = init_progress_for_intent(INTENT_CONTENT_SEO_SCORE)
    assert [s["id"] for s in steps] == ["analyze", "complete"]


def test_validate_url_score_requires_keyword():
    out = validate_prepare_params(
        INTENT_URL_SEO_SCOREBOARD,
        {"url": "https://example.com", "primary_keyword": "seo tool"},
    )
    assert out["url"] == "https://example.com"
    assert out["keyword"] == "seo tool"


def test_validate_content_score_params():
    out = validate_prepare_params(
        INTENT_CONTENT_SEO_SCORE,
        {"content_html": "<h1>Test</h1><p>Nội dung bài viết đủ dài để phân tích SEO onpage content score.</p>", "primary_keyword": "seo"},
    )
    assert "content_html" in out
    assert out["primary_keyword"] == "seo"


def test_content_score_credits_lower_than_url():
    url_est = estimate_workflow_credits(INTENT_URL_SEO_SCOREBOARD, {"url": "https://a.com", "keyword": "x"})
    content_est = estimate_workflow_credits(INTENT_CONTENT_SEO_SCORE, {"content_html": "x" * 100, "primary_keyword": "x"})
    assert url_est["total"] > 0
    assert content_est["total"] > 0
    assert content_est["total"] <= url_est["total"]


def test_build_content_report_shape():
    checklist = {
        "score": 72,
        "grade_tier": "needs_work",
        "grade_label": "Cần tối ưu",
        "word_count": 900,
        "groups": [{"id": "intent", "label": "Intent", "score": 8, "max_score": 10, "factors": []}],
        "factors": [
            {
                "id": "title_keyword",
                "label": "Tiêu đề có từ khóa",
                "status": "passed",
                "status_label": "Đạt",
                "message": "OK",
                "suggestion": "",
                "score": 3,
                "max_score": 3,
            },
            {
                "id": "helpful_word_count",
                "label": "Độ dài",
                "status": "failed",
                "status_label": "Không đạt",
                "message": "Ngắn",
                "suggestion": "Viết dài hơn",
                "score": 0,
                "max_score": 4,
            },
        ],
        "summary": {"ok": 1, "warn": 0, "fail": 1},
    }
    report = build_chatbot_seo_report_from_content(
        checklist,
        primary_keyword="seo",
        title="Bài seo",
        meta_description="Meta test",
        content_html="<h1>Bài seo</h1><p>Nội dung test keyword seo nhiều lần seo.</p>",
    )
    assert report["total_score"] == 72
    assert report["mode"] == "content"
    assert report["metrics"]["title"] == "Bài seo"
    assert len(report["issues"]["critical"]) == 1


def test_build_url_report_shape():
    raw = {
        "url": "https://example.com",
        "page_snapshot": {"title": "Tiêu đề", "meta_description": "Meta", "h1_count": 1},
        "scores": {"total": 65, "ten_group_total": 65},
        "ten_group_scoreboard": {
            "total_score": 65,
            "groups": [
                {
                    "id": "heading",
                    "label": "Heading",
                    "score": 70,
                    "checks": [
                        {
                            "id": "h1",
                            "title": "H1",
                            "status": "warning",
                            "problem": "Thiếu H1",
                            "fix": "Thêm H1",
                        }
                    ],
                }
            ],
            "secondary_keywords": ["kw1"],
        },
        "breakdown": {},
        "serp": {"serp_intent": "informational"},
        "issues": [],
    }
    report = build_chatbot_seo_report_from_url(raw, keyword="seo", html="")
    assert report["mode"] == "url"
    assert report["total_score"] == 65
    assert report["metrics"]["title"] == "Tiêu đề"
    assert len(report["issues"]["warning"]) >= 1
