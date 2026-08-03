"""Tests for chatbot Technical tab workflows."""

from __future__ import annotations

from app.services.chatbot_technical_report import build_chatbot_technical_report
from app.services.chatbot_tab_registry import (
    INTENT_TECHNICAL_DEEP_AUDIT,
    INTENT_TECHNICAL_QUICK_AUDIT,
    INTENT_TECHNICAL_SINGLE_URL,
    estimate_workflow_credits,
    init_progress_for_intent,
    tab_for_intent,
    validate_prepare_params,
)


def test_technical_tab_has_three_workflows():
    from app.services.chatbot_tab_registry import CHATBOT_TABS, TAB_TECHNICAL

    tab = next(t for t in CHATBOT_TABS if t["id"] == TAB_TECHNICAL)
    ids = [w["id"] for w in tab["workflows"]]
    assert ids == [
        INTENT_TECHNICAL_QUICK_AUDIT,
        INTENT_TECHNICAL_DEEP_AUDIT,
        INTENT_TECHNICAL_SINGLE_URL,
    ]


def test_progress_steps_per_workflow():
    assert [s["id"] for s in init_progress_for_intent(INTENT_TECHNICAL_QUICK_AUDIT)] == [
        "crawl",
        "analyze",
        "complete",
    ]
    assert [s["id"] for s in init_progress_for_intent(INTENT_TECHNICAL_DEEP_AUDIT)] == [
        "crawl",
        "analyze",
        "saving",
        "complete",
    ]
    assert [s["id"] for s in init_progress_for_intent(INTENT_TECHNICAL_SINGLE_URL)] == [
        "fetch",
        "analyze",
        "complete",
    ]


def test_tab_for_intent_mapping():
    assert tab_for_intent(INTENT_TECHNICAL_QUICK_AUDIT) == "technical"
    assert tab_for_intent(INTENT_TECHNICAL_DEEP_AUDIT) == "technical"
    assert tab_for_intent(INTENT_TECHNICAL_SINGLE_URL) == "technical"


def test_validate_quick_audit_params():
    out = validate_prepare_params(INTENT_TECHNICAL_QUICK_AUDIT, {"url": "https://example.com"})
    assert out["url"] == "https://example.com"
    assert out["max_pages"] == 10


def test_validate_deep_audit_params():
    out = validate_prepare_params(
        INTENT_TECHNICAL_DEEP_AUDIT,
        {"url": "https://example.com", "max_pages": 80},
    )
    assert out["max_pages"] == 80


def test_validate_single_url_params():
    out = validate_prepare_params(INTENT_TECHNICAL_SINGLE_URL, {"url": "https://example.com/a"})
    assert out["max_pages"] == 1


def test_legacy_technical_audit_maps_to_deep():
    out = validate_prepare_params("technical_audit", {"url": "https://example.com", "max_pages": 30})
    assert out["max_pages"] == 30


def test_credit_tiers():
    quick = estimate_workflow_credits(INTENT_TECHNICAL_QUICK_AUDIT, {"url": "https://a.com"})
    deep = estimate_workflow_credits(INTENT_TECHNICAL_DEEP_AUDIT, {"url": "https://a.com"})
    single = estimate_workflow_credits(INTENT_TECHNICAL_SINGLE_URL, {"url": "https://a.com/page"})
    assert quick["technical"] > 0
    assert deep["technical"] > 0
    assert single["technical"] > 0
    assert single["total"] <= deep["total"]


def test_build_technical_report_shape():
    raw = {
        "domain": "example.com",
        "pages_scanned": 3,
        "technical_summary": {
            "health_score": 72,
            "broken_internal_links": 2,
            "redirect_chains": 1,
        },
        "sitemap": {"status": 200, "urls": ["https://example.com/"]},
        "page_audits": [
            {
                "url": "https://example.com/",
                "status": 200,
                "parsed": {
                    "title": "Home",
                    "meta_description": "Meta test",
                    "canonical": "https://example.com/",
                    "robots_meta": "index,follow",
                    "images_missing_alt": 1,
                    "headings": {"h1": ["Home"], "h2": ["Section"], "h3": []},
                },
                "decision": {"indexable": True, "blocking_reasons": []},
            }
        ],
        "issues": [
            {
                "type": "missing_canonical",
                "severity": "high",
                "message": "Thiếu canonical",
                "remediation": "Thêm thẻ canonical",
            },
            {
                "type": "title_too_long",
                "severity": "medium",
                "message": "Title dài",
            },
        ],
    }
    report = build_chatbot_technical_report(raw, mode="quick", url="https://example.com/")
    assert report["mode"] == "quick"
    assert report["health_score"] >= 0
    assert report["overview"]["http_status"] == "200"
    assert report["overview"]["title"] == "Home"
    assert "issues" in report
    assert isinstance(report["issues"]["critical"], list)
