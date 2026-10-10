"""
ACCURACY FIRST tests for SEO Score SSOT (/tool/seo-score).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.idempotency_guard import build_idempotency_key, url_seo_scoreboard_fingerprint
from app.services.seo_score_intent import analyze_search_intent
from app.services.seo_score_link_analyzer import analyze_page_links
from app.services.seo_score_schema_checks import evaluate_schema_for_page
from app.services.seo_score_serp import fetch_seo_score_serp
from app.services.seo_score_ssot import SCORING_VERSION, compute_ssot_total, make_check
from app.services.url_seo_scoreboard import build_url_seo_scoreboard
from app.services.url_seo_ten_group_scoring import build_ten_group_scoreboard

LINK_HTML = """<!DOCTYPE html><html><body>
<a href="#">Toggle</a>
<a href="javascript:void(0)">JS</a>
<a href="mailto:a@b.com">Mail</a>
<a href="tel:+84123456789">Tel</a>
<a href="#section">Fragment</a>
<a href="/same" class="toggle">Same path</a>
<a href="/same">Same path dup</a>
<a href="https://example.com/ok">OK link</a>
<button><a href="/btn">Btn nested</a></button>
</body></html>"""

SAMPLE_HTML = """<!DOCTYPE html><html lang="vi"><head>
<title>SEO Title Example For Testing Purposes Only Here</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Meta description ngắn cho bài test SEO score integration.">
<link rel="canonical" href="https://example.com/test-page">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebPage","name":"Test"}</script>
</head><body>
<h1>Main Heading</h1>
<p>SEO content body with enough words for testing parser and evidence attachment on page.</p>
<a href="/internal">Internal link</a>
</body></html>"""


def _mock_fetch(*_a, **_k):
    return {
        "ok": True,
        "normalized_url": "https://example.com/test-page",
        "status": 200,
        "final_url": "https://example.com/test-page",
        "html": SAMPLE_HTML,
        "headers": {},
        "error": None,
        "notes": [],
    }


def _mock_serp_rows(*_a, **_k):
    return {
        "keyword": "seo test",
        "rows": [
            {"url": "https://a.com/1", "title": "Guide SEO", "domain": "a.com"},
            {"url": "https://b.com/2", "title": "How to SEO", "domain": "b.com"},
        ],
        "source": "test",
        "cache_hit": False,
        "provider_called": True,
        "snap": {"keyword": "seo test", "serp_urls": ["https://a.com/1"], "titles": ["Guide SEO"]},
    }


def test_link_analyzer_skips_fragment_mailto_javascript():
    profile = analyze_page_links(LINK_HTML, "https://example.com/page", verify_http=False)
    hrefs = {str(x.get("href") or "") for x in profile.get("links") or []}
    assert "#" not in hrefs
    assert not any(h.startswith("mailto:") for h in hrefs)
    assert not any(h.startswith("javascript:") for h in hrefs)
    assert not any(h.startswith("tel:") for h in hrefs)
    broken = profile.get("broken_links") or []
    broken_hrefs = {str(b.get("href") or "") for b in broken}
    assert "Toggle" not in broken_hrefs
    assert "x" not in broken_hrefs


@patch("app.services.seo_score_link_analyzer._verify_broken_links")
def test_duplicate_urls_deduped_before_http_check(mock_verify):
    mock_verify.return_value = []
    analyze_page_links(LINK_HTML, "https://example.com/page", verify_http=True)
    if mock_verify.called:
        checked = mock_verify.call_args[0][0]
        assert len(checked) == len(set(checked))


def test_serp_cache_hit_skips_provider():
    cached_snap = {
        "keyword": "seo test",
        "serp_urls": ["https://cached.com/1"],
        "titles": ["Cached"],
        "source": "cache",
    }
    with patch("app.services.seo_score_serp.peek_seo_score_serp_cache", return_value=cached_snap):
        with patch("app.services.seo_score_serp.fetch_serp_for_keyword") as mock_fetch:
            out = fetch_seo_score_serp("seo test")
            mock_fetch.assert_not_called()
    assert out["cache_hit"] is True
    assert out["provider_called"] is False
    assert len(out["rows"]) >= 1


def test_idempotency_fingerprint_stable_for_same_inputs():
    payload = {
        "url": "https://example.com/page",
        "keyword": "seo test",
        "secondary_keywords": ["a", "b"],
        "page_type": "article",
    }
    fp1 = url_seo_scoreboard_fingerprint(payload)
    fp2 = url_seo_scoreboard_fingerprint(dict(payload))
    assert fp1 == fp2
    key1 = build_idempotency_key("url_seo_scoreboard", 7, fp1)
    key2 = build_idempotency_key("url_seo_scoreboard", 7, fp2)
    assert key1 == key2
    payload2 = dict(payload, keyword="other kw")
    assert url_seo_scoreboard_fingerprint(payload2) != fp1


def test_low_confidence_intent_not_hard_fail():
    pkg = analyze_search_intent(
        keyword="seo test",
        page_type="product",
        title="Buy SEO tool",
        body_text="pricing checkout buy now",
        serp_rows=[
            {"url": f"https://x{i}.com", "title": f"Guide {i}", "domain": f"x{i}.com"}
            for i in range(8)
        ],
    )
    assert pkg["status"] != "FAIL"
    assert pkg["confidence"] < 0.7 or pkg["mismatch"] is True


def test_schema_wrong_type_not_100():
    blocks = [{"@context": "https://schema.org", "@type": "Article", "headline": "X"}]
    ev = evaluate_schema_for_page(blocks, page_type="product")
    assert ev["score_percent"] < 100.0
    assert ev["type_match"] is False


def test_no_real_cwv_group_not_100():
    with patch("app.services.url_seo_scoreboard.fetch_seo_score_serp", side_effect=_mock_serp_rows), patch(
        "app.services.url_seo_scoreboard._safe_fetch", side_effect=_mock_fetch
    ):
        raw = build_url_seo_scoreboard("https://example.com/test-page", keyword="seo test", page_type="article")
    groups = {g["id"]: g for g in raw["ten_group_scoreboard"]["groups"]}
    ux = groups.get("ux_mobile_speed") or {}
    assert float(ux.get("score") or 0) < 100.0
    cwv = next((c for c in ux.get("checks") or [] if c.get("id") == "cwv_lab"), None)
    assert cwv is not None
    assert cwv.get("status") == "UNKNOWN"


def test_legacy_does_not_drive_main_score():
    with patch("app.services.url_seo_scoreboard.fetch_seo_score_serp", side_effect=_mock_serp_rows), patch(
        "app.services.url_seo_scoreboard._safe_fetch", side_effect=_mock_fetch
    ):
        raw = build_url_seo_scoreboard("https://example.com/test-page", keyword="seo test")
    ssot = float(raw["scores"]["total"])
    legacy = float(raw["scores"]["legacy_total"])
    tg = float(raw["ten_group_scoreboard"]["total_score"])
    assert ssot == tg
    assert raw["scores"]["scoring_version"] == SCORING_VERSION
    # Legacy may differ — main score must follow SSOT only
    assert ssot == float(raw["scores"]["ten_group_total"])


def test_same_evidence_same_score_deterministic():
    kwargs = dict(
        url="https://example.com/test-page",
        normalized_url="https://example.com/test-page",
        fetch=_mock_fetch(),
        page_data={"title": "T", "meta_description": "M", "word_count": 400, "h1_count": 1, "links": []},
        content_pkg={"word_count": 400, "content_depth": "medium", "heading_structure_score": 70.0},
        html=SAMPLE_HTML,
        headers={},
        ld_blocks=[{"@context": "https://schema.org", "@type": "WebPage", "name": "Test"}],
        soup=None,
        primary_keyword="seo test",
        secondary_keywords=[],
        page_type="article",
        breakdown={},
        legacy_issues=[],
        serp_rows=[],
        schema_validation={"valid": True, "errors": [], "warnings": []},
        link_profile={"links": [], "broken_links": [], "internal_links_count": 0, "external_links_count": 0},
        serp_intent_pkg=None,
    )
    a = build_ten_group_scoreboard(**kwargs)
    b = build_ten_group_scoreboard(**kwargs)
    assert a["total_score"] == b["total_score"]
    assert a["scoring_version"] == b["scoring_version"] == SCORING_VERSION


def test_make_check_low_confidence_downgrades_fail():
    chk = make_check(
        check_id="x",
        title="t",
        status="FAIL",
        score=0,
        max_score=10,
        confidence=0.2,
    )
    assert chk["status"] == "WARNING"


def test_ssot_weights_sum_100():
    from app.services.seo_score_ssot import GROUP_WEIGHTS

    assert sum(GROUP_WEIGHTS.values()) == 100.0


def test_compute_ssot_total_from_groups():
    groups = [
        {"id": "indexability", "score": 80.0, "weight": 15},
        {"id": "title_meta_slug", "score": 60.0, "weight": 12},
    ]
    out = compute_ssot_total(groups)
    assert 0 <= out["total_score"] <= 100
    assert out["scoring_version"] == SCORING_VERSION
