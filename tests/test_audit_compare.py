"""Compare two technical audits — score delta and issue diff."""

from __future__ import annotations

from app.services.audit_compare import compare_technical_audits, issue_identity


def _issue(issue_type: str, url: str, **extra) -> dict:
    return {"issue_type": issue_type, "affected_urls": [url], "title": issue_type, **extra}


def test_issue_identity_dedupes_by_type_and_url():
    a = _issue("broken_internal_link", "https://example.com/a")
    b = _issue("broken_internal_link", "https://example.com/a")
    c = _issue("broken_internal_link", "https://example.com/b")
    assert issue_identity(a) == issue_identity(b)
    assert issue_identity(a) != issue_identity(c)


def test_compare_fixed_new_remaining():
    base = {
        "id": "base-1",
        "at": "2026-01-01T00:00:00Z",
        "domain": "example.com",
        "technical_dashboard_v2": {
            "technical_health_score": 70,
            "issues": [
                _issue("missing_title", "https://example.com/old", priority_tier="P2"),
                _issue("broken_link", "https://example.com/x"),
            ],
        },
    }
    target = {
        "id": "target-1",
        "at": "2026-02-01T00:00:00Z",
        "domain": "example.com",
        "technical_dashboard_v2": {
            "technical_health_score": 82,
            "issues": [
                _issue("broken_link", "https://example.com/x"),
                _issue("slow_lcp", "https://example.com/new", priority_tier="P1"),
            ],
        },
    }
    out = compare_technical_audits(base, target)
    assert out["score_before"] == 70.0
    assert out["score_after"] == 82.0
    assert out["score_delta"] == 12.0
    assert out["counts"]["fixed"] == 1
    assert out["counts"]["new"] == 1
    assert out["counts"]["remaining"] == 1
    assert out["fixed"][0]["issue_type"] == "missing_title"
    assert out["new"][0]["issue_type"] == "slow_lcp"
    assert out["remaining"][0]["issue_type"] == "broken_link"
