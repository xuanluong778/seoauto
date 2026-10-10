"""Unit tests for GSC priority scoring (hybrid audit)."""

from app.services.gsc_priority import (
    GSC_DISCLAIMER,
    append_gsc_disclaimer_if_needed,
    compute_issue_priority_score,
    compute_priority_components,
    detect_ctr_opportunities,
    gsc_evidence_badge,
    priority_tier_from_score,
)


def test_high_traffic_issue_scores_higher():
    low = compute_issue_priority_score(
        {"type": "missing_meta_description", "severity": "low"},
        page_metrics={"impressions": 0, "clicks": 0},
        has_gsc=True,
    )
    high = compute_issue_priority_score(
        {"type": "broken_internal_link", "severity": "high"},
        page_metrics={"impressions": 5000, "clicks": 120, "position": 8.0},
        has_gsc=True,
    )
    assert high > low


def test_index_issue_without_inspection_is_inferred():
    issue = {"type": "indexability_blocked", "severity": "high"}
    badge = gsc_evidence_badge(issue, inspection=None)
    assert badge == "inferred_warning"
    append_gsc_disclaimer_if_needed(issue, has_inspection=False)
    assert GSC_DISCLAIMER in issue["explanation"]


def test_canonical_mismatch_gsc_confirmed():
    issue = {"type": "canonical_self_mismatch", "severity": "medium"}
    insp = {
        "user_canonical": "https://example.com/a",
        "google_canonical": "https://example.com/b",
        "index_verdict": "PASS",
    }
    assert gsc_evidence_badge(issue, inspection=insp) == "gsc_confirmed"


def test_ctr_opportunity_detection():
    metrics = {
        "https://example.com/page": {
            "page": "https://example.com/page",
            "impressions": 500,
            "clicks": 2,
            "ctr": 0.004,
            "position": 9.0,
        }
    }
    opps = detect_ctr_opportunities(metrics)
    assert len(opps) >= 1
    assert opps[0]["type"] == "ctr_opportunity"


def test_multiplicative_scoring_is_deterministic():
    issue = {"type": "broken_internal_link", "severity": "high", "page_type": "homepage"}
    pm = {"impressions": 1200, "clicks": 40, "position": 7.0}
    a = compute_priority_components(
        issue,
        page_metrics=pm,
        has_gsc=True,
        affected_url_count=3,
        confidence=0.9,
    )
    b = compute_priority_components(
        issue,
        page_metrics=pm,
        has_gsc=True,
        affected_url_count=3,
        confidence=0.9,
    )
    assert a == b
    assert 0 <= a["priority_score"] <= 100
    assert a["priority_tier"] == priority_tier_from_score(a["priority_score"])


def test_more_affected_urls_increase_score():
    base_issue = {"type": "missing_meta_description", "severity": "medium"}
    low = compute_issue_priority_score(base_issue, affected_url_count=1, confidence=0.8)
    high = compute_issue_priority_score(base_issue, affected_url_count=50, confidence=0.8)
    assert high > low


def test_priority_tier_boundaries():
    assert priority_tier_from_score(85) == "P0"
    assert priority_tier_from_score(65) == "P1"
    assert priority_tier_from_score(40) == "P2"
    assert priority_tier_from_score(10) == "P3"
