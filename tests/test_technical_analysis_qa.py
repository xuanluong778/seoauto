"""
QA backend coverage for Technical Analysis upgrade (normalizer, GSC fallbacks, audit compat).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas import TechnicalAnalyzeResponse
from app.services.audit_store import (
    AUDIT_FILE,
    get_audit_for_user,
    normalize_audit_record,
    save_technical_audit,
)
from app.services.report_builder import resolve_audit_issues_for_export
from app.services.technical_output_normalizer import (
    build_category_summaries,
    build_gsc_intelligence_summary,
    build_passed_checks,
    build_saas_api_extensions,
    build_saas_technical_payload,
    build_top_priority_fixes,
    calculate_technical_health_score,
    empty_saas_api_extensions,
    merge_duplicate_issues,
    normalize_crawl_issues,
    normalize_gsc_issues,
)


def _base_crawl_payload(**overrides) -> dict:
    base = {
        "domain": "example.com",
        "pages_scanned": 5,
        "issues": [],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 5,
            "total_technical_issues": 0,
            "health_score": 90,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "https://example.com/robots.txt", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "https://example.com/sitemap.xml", "status": 200, "urls": ["https://example.com/"]},
    }
    base.update(overrides)
    return base


# —— normalize crawl / GSC ——


def test_normalize_crawl_skips_suppressed_and_maps_fields():
    raw = [
        {"type": "missing_title", "severity": "high", "message": "No title", "url": "https://example.com/", "checklist_group": "Onpage"},
        {"type": "hidden", "severity": "low", "suppressed": True},
        "not-a-dict",
    ]
    out = normalize_crawl_issues(raw)
    assert len(out) == 1
    assert out[0]["source"] == "crawl"
    assert out[0]["category"] == "onpage"
    assert out[0]["sample_urls"] == ["https://example.com/"]


def test_normalize_gsc_confirmed_issue():
    out = normalize_gsc_issues(
        gsc_summary={"enabled": True},
        gsc_confirmed_issues=[
            {
                "issue_type": "canonical_self_mismatch",
                "severity": "high",
                "url": "https://example.com/page",
                "index_verdict": "NEUTRAL",
                "message": "Canonical mismatch",
            }
        ],
    )
    assert len(out) == 1
    assert out[0]["source"] == "gsc"
    assert out[0]["category"] == "gsc_indexing"
    assert out[0]["gsc_badge"] == "gsc_confirmed"


def test_normalize_gsc_url_inspection_fail_critical():
    out = normalize_gsc_issues(
        gsc_summary={"enabled": True},
        url_inspection_results=[
            {
                "inspection_url": "https://example.com/blocked",
                "index_verdict": "FAIL",
                "coverage_state": "Not indexed",
                "status": "ok",
            }
        ],
    )
    assert len(out) == 1
    assert out[0]["severity"] == "critical"
    assert "blocked" in (out[0].get("sample_urls") or [""])[0]


def test_normalize_gsc_skips_inspection_errors():
    out = normalize_gsc_issues(
        gsc_summary={"enabled": True},
        url_inspection_results=[{"inspection_url": "https://x.com/", "status": "error"}],
    )
    assert out == []


def test_normalize_gsc_partial_data_inferred_warning():
    out = normalize_gsc_issues(
        gsc_summary={
            "enabled": True,
            "partial_data": True,
            "message": "Quota exceeded for URL Inspection",
            "quota_exceeded": True,
        },
    )
    assert len(out) == 1
    assert out[0]["gsc_badge"] == "inferred_warning"
    assert "quota" in (out[0].get("description") or out[0].get("message") or "").lower()


def test_normalize_gsc_returns_empty_when_disabled():
    assert normalize_gsc_issues(gsc_summary={"enabled": False}) == []
    assert normalize_gsc_issues(gsc_summary=None) == []


# —— merge ——


def test_merge_duplicate_issues_merges_urls_and_upgrades_hybrid():
    crawl = normalize_crawl_issues(
        [
            {
                "type": "canonical_self_mismatch",
                "severity": "medium",
                "url": "https://example.com/a",
                "checklist_group": "Onpage",
            }
        ]
    )
    gsc = normalize_gsc_issues(
        gsc_summary={"enabled": True},
        gsc_confirmed_issues=[
            {
                "issue_type": "canonical_self_mismatch",
                "severity": "high",
                "url": "https://example.com/a",
            },
            {
                "issue_type": "canonical_self_mismatch",
                "severity": "high",
                "url": "https://example.com/b",
            },
        ],
    )
    merged = merge_duplicate_issues(crawl, gsc)
    assert len(merged) >= 1
    row = merged[0]
    assert row["source"] in ("hybrid", "gsc")
    assert row["severity"] in ("high", "critical")
    urls = row.get("affected_urls") or row.get("sample_urls") or []
    assert len(urls) >= 1


# —— health score ——


def test_calculate_technical_health_score_critical_lowers_score():
    issues = normalize_crawl_issues(
        [
            {"type": "gsc_index_verdict_fail", "severity": "critical", "checklist_group": "GSC", "url": "https://x.com/"},
            {"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"},
        ]
    )
    health = calculate_technical_health_score(issues)
    assert 0 <= health["health_score"] <= 100
    assert health["health_score"] < 90
    assert sum(b["weight"] for b in health["breakdown"].values()) == 100.0


def test_calculate_technical_health_score_partial_gsc_discount():
    issues = normalize_crawl_issues([{"type": "missing_title", "severity": "low", "checklist_group": "Onpage"}])
    full = calculate_technical_health_score(issues, gsc_summary={"enabled": True, "partial_data": False})
    partial = calculate_technical_health_score(issues, gsc_summary={"enabled": True, "partial_data": True})
    assert partial["health_score"] <= full["health_score"]
    assert partial["partial_data"] is True


# —— priority fixes ——


def test_build_top_priority_fixes_ranking():
    issues = normalize_crawl_issues(
        [
            {"type": "missing_title", "severity": "low", "message": "low", "checklist_group": "Onpage", "url": "https://a/"},
            {"type": "indexability_blocked", "severity": "critical", "message": "crit", "checklist_group": "GSC", "url": "https://b/"},
            {"type": "robots_unreachable", "severity": "high", "message": "high", "checklist_group": "Robots", "url": "https://c/"},
        ]
    )
    for i in issues:
        i["priority_score"] = {"critical": 95, "high": 70, "low": 10}[str(i["severity"])]
    top = build_top_priority_fixes(issues, limit=3)
    assert len(top) == 3
    scores = [t["priority_score"] for t in top]
    assert scores == sorted(scores, reverse=True)
    assert top[0]["severity"] == "critical"


# —— passed checks & category summaries ——


def test_build_passed_checks_robots_sitemap_when_clean():
    payload = _base_crawl_payload(
        issues=[{"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"}],
    )
    passed = build_passed_checks(payload)
    ids = {p["id"] for p in passed}
    assert "robots_txt" in ids
    assert "sitemap_xml" in ids
    assert all(p["severity"] == "passed" for p in passed)


def test_build_category_summaries_counts_and_worst_severity():
    issues = normalize_crawl_issues(
        [
            {"type": "missing_title", "severity": "high", "checklist_group": "Onpage", "url": "https://a/"},
            {"type": "missing_meta", "severity": "medium", "checklist_group": "Onpage", "url": "https://b/"},
            {"type": "robots_unreachable", "severity": "critical", "checklist_group": "Robots", "url": "https://c/"},
        ]
    )
    passed = build_passed_checks(_base_crawl_payload(issues=[{"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"}]))
    summaries = build_category_summaries(issues, passed)
    by_cat = {s["category"]: s for s in summaries}
    assert by_cat["onpage"]["open_issues"] == 2
    assert by_cat["onpage"]["worst_severity"] == "high"
    assert by_cat["robots"]["worst_severity"] == "critical"
    assert by_cat["robots"]["open_issues"] == 1


# —— GSC fallbacks (missing / quota / permission / token) ——


@pytest.mark.parametrize(
    "gsc_summary,expected_scan_mode,expect_partial",
    [
        (None, "crawl_only", False),
        ({"enabled": False}, "crawl_only", False),
        (
            {
                "enabled": True,
                "connected": False,
                "partial_data": True,
                "errors": ["Google OAuth token expired"],
                "message": "Token expired — reconnect GSC",
            },
            "partial_gsc",
            True,
        ),
        (
            {
                "enabled": True,
                "partial_data": True,
                "quota_exceeded": True,
                "errors": ["Quota exceeded"],
                "message": "Quota exceeded for URL Inspection",
            },
            "partial_gsc",
            True,
        ),
        (
            {
                "enabled": True,
                "partial_data": False,
                "errors": ["Permission denied for property"],
                "message": "Permission denied",
            },
            "hybrid_gsc",
            False,
        ),
    ],
)
def test_build_saas_api_extensions_gsc_fallback_modes(gsc_summary, expected_scan_mode, expect_partial):
    payload = _base_crawl_payload(
        issues=[{"type": "missing_title", "severity": "medium", "message": "x", "checklist_group": "Onpage"}],
        gsc_summary=gsc_summary,
        confidence_overall=0.5 if gsc_summary and gsc_summary.get("enabled") else None,
    )
    ext = build_saas_api_extensions(payload)
    assert ext["saas_summary"]["scan_mode"] == expected_scan_mode
    assert ext["partial_data"] is expect_partial
    assert isinstance(ext["disclaimers"], list)
    if gsc_summary is None or not gsc_summary.get("enabled"):
        assert any("crawl-only" in d.lower() for d in ext["disclaimers"])


def test_build_saas_payload_no_crash_when_gsc_fields_missing():
    payload = _base_crawl_payload(
        issues=[{"type": "missing_title", "severity": "high", "checklist_group": "Onpage"}],
    )
    saas = build_saas_technical_payload(payload)
    assert saas["gsc_intelligence"]["enabled"] is False
    assert saas["partial_data"] is False
    assert isinstance(saas["issues"], list)
    assert isinstance(saas["category_summaries"], list)


def test_build_gsc_intelligence_summary_null_safe():
    gi = build_gsc_intelligence_summary(gsc_summary=None, gsc_opportunities=None, url_inspection_results=None)
    assert gi["enabled"] is False
    assert gi["clicks"] == 0
    assert gi["errors"] == []


def test_empty_saas_extensions_safe_on_normalizer_failure_path():
    ext = empty_saas_api_extensions()
    model = TechnicalAnalyzeResponse.model_validate(
        {
            **_base_crawl_payload(),
            **ext,
        }
    )
    ss = model.saas_summary
    scan_mode = ss.get("scan_mode") if isinstance(ss, dict) else getattr(ss, "scan_mode", None)
    assert scan_mode == "crawl_only"
    assert model.normalized_issues == []


# —— audit cũ ——


def test_old_stored_audit_normalize_and_export():
    legacy = {
        "id": "legacy-001",
        "user_id": 42,
        "at": "2024-01-01T00:00:00+00:00",
        "domain": "legacy.com",
        "source_url": "https://legacy.com",
        "pages_scanned": 2,
        "issues": [
            {"type": "missing_title", "severity": "high", "message": "No title", "url": "https://legacy.com/", "checklist_group": "Onpage"},
        ],
        "technical_summary": {"health_score": 75},
    }
    norm = normalize_audit_record(legacy)
    assert norm["audit_id"] == "legacy-001"
    assert norm["normalized_issues"] == []
    assert norm["saas_summary"] is None
    rows = resolve_audit_issues_for_export(norm)
    assert len(rows) == 1
    assert rows[0]["type"] == "missing_title"


def test_audit_store_read_legacy_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "audits.json")
    legacy = {
        "id": "file-legacy",
        "user_id": 7,
        "at": "2025-06-01T00:00:00+00:00",
        "domain": "filelegacy.com",
        "source_url": "https://filelegacy.com",
        "pages_scanned": 1,
        "issues": [],
        "technical_summary": {},
    }
    (tmp_path / "audits.json").write_text(json.dumps([legacy]), encoding="utf-8")
    loaded = get_audit_for_user("file-legacy", 7)
    assert loaded is not None
    assert loaded["normalized_issues"] == []
    assert loaded["passed_checks"] == []
    assert loaded["audit_id"] == "file-legacy"


def test_audit_store_save_and_read_new_saas_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "audits.json")
    result = build_saas_api_extensions(
        _base_crawl_payload(
            issues=[{"type": "missing_title", "severity": "high", "message": "x", "checklist_group": "Onpage"}],
        )
    )
    result.update(_base_crawl_payload(issues=[{"type": "missing_title", "severity": "high", "message": "x", "checklist_group": "Onpage"}]))
    aid = save_technical_audit(user_id=9, source_url="https://newsaas.com", result=result)
    loaded = get_audit_for_user(aid, 9)
    assert loaded is not None
    assert isinstance(loaded["normalized_issues"], list)
    assert isinstance(loaded["category_summaries"], list)
    assert isinstance(loaded["priority_fixes"], list)
    assert loaded["saas_summary"] is not None


# —— no critical issues audit ——


def test_saas_payload_without_critical_issues():
    payload = _base_crawl_payload(
        issues=[
            {"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"},
            {"type": "missing_meta_description", "severity": "medium", "checklist_group": "Onpage"},
        ],
    )
    ext = build_saas_api_extensions(payload)
    assert ext["saas_summary"]["critical_count"] == 0
    assert ext["saas_summary"]["high_count"] == 0
    assert ext["saas_summary"]["medium_count"] >= 1


# —— many issues ——


def test_saas_payload_many_issues_truncation_in_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.audit_store.AUDIT_FILE", tmp_path / "audits.json")
    many = [
        {"type": f"issue_{i}", "severity": "low", "message": f"m{i}", "checklist_group": "General", "url": f"https://example.com/{i}"}
        for i in range(300)
    ]
    ext = build_saas_api_extensions(_base_crawl_payload(issues=many))
    ext.update(_base_crawl_payload(issues=many))
    aid = save_technical_audit(user_id=1, source_url="https://example.com", result=ext, max_issue_rows=250)
    loaded = get_audit_for_user(aid, 1)
    assert len(loaded["issues"]) <= 250
    assert len(loaded["normalized_issues"]) <= 250
    assert loaded.get("truncated_issues") or loaded.get("normalized_issues_truncated")
