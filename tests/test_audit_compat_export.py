"""Backward compatibility: old audits, normalized export, normalize_audit_record."""

import pytest

from app.services.audit_store import normalize_audit_record
from app.services.report_builder import resolve_audit_issues_for_export

pytest.importorskip("fastapi")
from app.routers.report import _group_audit_issues, _technical_audit_issues_csv


def test_normalize_audit_record_legacy_minimal():
    raw = {
        "id": "abc-123",
        "domain": "example.com",
        "issues": [{"type": "missing_title", "severity": "high", "message": "No title"}],
    }
    out = normalize_audit_record(raw)
    assert out is not None
    assert out["audit_id"] == "abc-123"
    assert out["issues"] == raw["issues"]
    assert out["normalized_issues"] == []
    assert out["saas_summary"] is None
    assert out["gsc_intelligence_summary"] == {}
    assert out["passed_checks"] == []
    assert out["disclaimers"] == []
    assert out["gsc_summary"] is None
    assert out["partial_data"] is False


def test_normalize_audit_record_gsc_null_safe():
    raw = {
        "id": "x",
        "gsc_summary": "bad",
        "gsc_intelligence_summary": None,
        "confidence_overall": "n/a",
    }
    out = normalize_audit_record(raw)
    assert out["gsc_summary"] is None
    assert out["gsc_intelligence_summary"] == {}
    assert out["confidence_overall"] is None


def test_resolve_export_prefers_normalized():
    run = {
        "issues": [{"type": "legacy_only", "severity": "low", "message": "old"}],
        "normalized_issues": [
            {
                "id": "missing_title_deadbeefcafe",
                "category": "onpage",
                "title": "Missing title",
                "description": "Page has no title",
                "severity": "high",
                "affected_urls": ["https://example.com/a", "https://example.com/b"],
                "how_to_fix": "Add title tag",
                "confidence": 0.85,
            },
            {
                "id": "passed_check",
                "severity": "passed",
                "title": "OK",
            },
        ],
    }
    rows = resolve_audit_issues_for_export(run)
    assert len(rows) == 1
    assert rows[0]["type"] == "missing_title"
    assert rows[0]["checklist_group"] == "Onpage"
    assert rows[0]["message"] == "Page has no title"
    assert rows[0]["urls"] == ["https://example.com/a", "https://example.com/b"]


def test_resolve_export_fallback_legacy():
    run = {
        "issues": [
            {"type": "robots_missing", "severity": "medium", "message": "No robots", "url": "https://x.com/"},
            {"type": "hidden", "severity": "low", "message": "x", "suppressed": True},
        ],
    }
    rows = resolve_audit_issues_for_export(run)
    assert len(rows) == 1
    assert rows[0]["type"] == "robots_missing"


def test_group_audit_issues_from_normalized():
    run = {
        "normalized_issues": [
            {
                "id": "noindex_abcabcabcabc",
                "category": "gsc_indexing",
                "description": "Blocked",
                "severity": "critical",
                "sample_urls": ["https://example.com/page"],
                "how_to_fix": "Remove noindex",
            }
        ],
        "technical_summary": {"health_score": 55, "weighted_penalty": 12, "issues_by_severity": {"high": 1}},
    }
    grouped = _group_audit_issues(run)
    assert len(grouped) == 1
    assert grouped[0]["severity"] == "critical"
    assert grouped[0]["checklist_group"] == "GSC"
    assert "https://example.com/page" in grouped[0]["urls"]


def test_csv_export_legacy_and_normalized():
    legacy_run = {
        "technical_summary": {"health_score": 80},
        "issues": [{"type": "t1", "severity": "low", "message": "m", "checklist_group": "General"}],
    }
    csv_legacy = _technical_audit_issues_csv(legacy_run)
    assert "t1" in csv_legacy
    assert "Điểm sức khỏe" in csv_legacy

    norm_run = {
        "technical_summary": {"health_score": 70},
        "normalized_issues": [
            {
                "id": "slow_lcp_aabbccddeeff",
                "category": "site_speed",
                "description": "Slow LCP",
                "severity": "high",
                "affected_urls": ["https://example.com/"],
            }
        ],
    }
    csv_norm = _technical_audit_issues_csv(norm_run)
    assert "slow_lcp" in csv_norm
    assert "Speed" in csv_norm or "site_speed" not in csv_norm
