"""Tests for technical_output_normalizer SaaS layer."""

from app.services.technical_output_normalizer import (
    V2_SIDEBAR_GROUPS,
    V2_SOURCES,
    V2_SCORE_WEIGHTS,
    build_passed_checks,
    build_saas_api_extensions,
    build_saas_technical_payload,
    build_technical_dashboard_v2,
    calculate_technical_health_score,
    calculate_technical_health_score_v2,
    empty_saas_api_extensions,
    empty_technical_dashboard_v2,
    merge_duplicate_issues,
    normalize_crawl_issues,
    normalize_gsc_issues,
    _expand_and_dedupe_v2_issues,
    _gsc_has_real_data,
    _map_v2_severity,
    _normalize_v2_source,
    _v2_issue_penalty_units,
    _v2_url_repeat_factor,
    _v2_issue_is_publishable,
)
from app.schemas import TechnicalAnalyzeResponse


def test_normalize_crawl_issues_basic():
    raw = [
        {
            "type": "missing_title",
            "severity": "high",
            "message": "Thiếu title",
            "url": "https://example.com/",
            "checklist_group": "Onpage",
            "remediation": "Thêm title",
        }
    ]
    out = normalize_crawl_issues(raw)
    assert len(out) == 1
    assert out[0]["category"] == "onpage"
    assert out[0]["severity"] == "high"
    assert out[0]["source"] == "crawl"
    assert out[0]["how_to_fix"] == "Thêm title"
    assert "id" in out[0]


def test_crawl_only_saas_payload():
    payload = {
        "domain": "example.com",
        "pages_scanned": 3,
        "issues": [
            {"type": "robots_unreachable", "severity": "high", "message": "No robots", "checklist_group": "Robots"},
        ],
        "technical_summary": {"health_score": 70},
        "robots": {"status": 404},
        "sitemap": {"status": 200, "urls": ["https://example.com/a"]},
    }
    saas = build_saas_technical_payload(payload)
    assert saas["domain"] == "example.com"
    assert saas["health"]["health_score"] >= 0
    assert saas["issue_count"]["total"] >= 1
    assert saas["gsc_intelligence"]["enabled"] is False
    assert saas["partial_data"] is False


def test_gsc_partial_data_flag():
    payload = {
        "domain": "example.com",
        "pages_scanned": 1,
        "issues": [],
        "gsc_summary": {
            "enabled": True,
            "connected": True,
            "partial_data": True,
            "message": "Quota exceeded",
            "errors": ["quota"],
        },
        "url_inspection_results": [],
    }
    saas = build_saas_technical_payload(payload)
    assert saas["partial_data"] is True
    assert saas["gsc_intelligence"]["partial_data"] is True


def test_merge_hybrid_upgrades_source():
    crawl = normalize_crawl_issues(
        [{"type": "canonical_self_mismatch", "severity": "high", "url": "https://x.com/a", "checklist_group": "Onpage"}]
    )
    gsc = normalize_gsc_issues(
        gsc_summary={"enabled": True},
        gsc_confirmed_issues=[
            {
                "issue_type": "canonical_self_mismatch",
                "severity": "high",
                "url": "https://x.com/a",
                "index_verdict": "PASS",
            }
        ],
    )
    merged = merge_duplicate_issues(crawl, gsc)
    assert len(merged) >= 1
    assert merged[0]["source"] in ("hybrid", "gsc", "crawl")


def test_health_score_weights_sum():
    issues = normalize_crawl_issues(
        [
            {"type": "indexability_blocked", "severity": "high", "checklist_group": "GSC"},
            {"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"},
        ]
    )
    health = calculate_technical_health_score(issues)
    assert 0 <= health["health_score"] <= 100
    assert sum(b["weight"] for b in health["breakdown"].values()) == 100.0


def test_build_saas_api_extensions_shape():
    payload = {
        "domain": "example.com",
        "pages_scanned": 2,
        "issues": [{"type": "missing_title", "severity": "high", "message": "x", "checklist_group": "Onpage"}],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 2,
            "total_technical_issues": 1,
            "health_score": 80,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
        "gsc_summary": {"enabled": True, "partial_data": False, "clicks": 10, "impressions": 100},
        "confidence_overall": 0.85,
    }
    ext = build_saas_api_extensions(payload)
    assert "saas_summary" in ext
    assert ext["saas_summary"]["scan_mode"] == "hybrid_gsc"
    assert ext["saas_summary"]["gsc_confidence"] == 85.0
    assert isinstance(ext["normalized_issues"], list)
    assert isinstance(ext["disclaimers"], list)


def test_empty_saas_api_extensions_fallback():
    ext = empty_saas_api_extensions()
    assert ext["saas_summary"]["scan_mode"] == "crawl_only"
    assert ext["normalized_issues"] == []


def test_legacy_audit_json_without_saas_fields():
    """Old stored audit shape must still validate when saas fields omitted."""
    legacy = {
        "domain": "old.com",
        "pages_scanned": 1,
        "issues": [],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 1,
            "total_technical_issues": 0,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    model = TechnicalAnalyzeResponse.model_validate(legacy)
    assert model.domain == "old.com"
    assert model.normalized_issues == []
    assert model.partial_data is False


def test_build_passed_checks_when_clean():
    payload = {
        "issues": [{"type": "missing_favicon", "severity": "low", "checklist_group": "Onpage"}],
        "robots": {"status": 200},
        "sitemap": {"status": 200, "urls": ["https://example.com/"]},
    }
    passed = build_passed_checks(payload)
    ids = {p["id"] for p in passed}
    assert "robots_txt" in ids or "sitemap_xml" in ids


def test_v2_severity_mapping():
    assert _map_v2_severity({"severity": "critical", "issue_type": "robots_disallow_all"}) == "critical"
    assert _map_v2_severity({"severity": "high", "issue_type": "missing_title"}) == "warning"
    assert _map_v2_severity({"severity": "low", "issue_type": "missing_favicon"}) == "opportunity"


def test_v2_issue_dedupe_by_issue_id_and_url():
    norm = normalize_crawl_issues(
        [
            {
                "type": "missing_title",
                "severity": "high",
                "message": "No title",
                "url": "https://example.com/a",
                "checklist_group": "Onpage",
            },
            {
                "type": "missing_title",
                "severity": "high",
                "message": "No title dup",
                "url": "https://example.com/a",
                "checklist_group": "Onpage",
            },
        ]
    )
    merged = merge_duplicate_issues(norm, [])
    v2 = _expand_and_dedupe_v2_issues(merged)
    assert len(v2) == 1
    row = v2[0]
    assert row["issue_id"]
    assert row["title"]
    assert row["category"] == "onpage"
    assert row["severity"] in ("critical", "warning", "opportunity")
    assert row["priority_score"] >= 0
    assert row["confidence"] >= 0
    assert row["source"] == "crawl"
    assert isinstance(row["affected_urls"], list)
    assert isinstance(row["sample_urls"], list)
    assert isinstance(row["evidence"], list)
    assert isinstance(row["impact"], list)
    assert row["status"] in ("failed", "warning", "opportunity")
    assert row["evidence"]
    assert row["affected_urls"]
    assert row["nav_group"] in {
        "indexability",
        "crawlability",
        "onpage",
        "internal_links",
        "performance",
        "structured_data",
        "security_http",
        "ux_mobile",
        "gsc_insights",
    }


def test_v2_skips_issue_without_url_or_evidence():
    """Issue thiếu URL và không phải domain-level → không tạo bản ghi v2."""
    norm = normalize_crawl_issues(
        [{"type": "crawl_data_low_trust", "severity": "low", "checklist_group": "General"}]
    )
    merged = merge_duplicate_issues(norm, [])
    v2 = _expand_and_dedupe_v2_issues(merged, {"domain": "example.com"})
    assert v2 == []


def test_v2_domain_level_issue_without_url():
    """Lỗi cấp domain (robots) được phép không có affected_urls nếu có evidence/domain scope."""
    norm = normalize_crawl_issues(
        [
            {
                "type": "robots_disallow_all",
                "severity": "critical",
                "message": "Robots chặn toàn site",
                "checklist_group": "Robots",
            }
        ]
    )
    v2 = _expand_and_dedupe_v2_issues(merge_duplicate_issues(norm, []), {"domain": "example.com", "source_url": "https://example.com"})
    assert len(v2) == 1
    row = v2[0]
    assert row["affected_urls"] == []
    assert row["evidence"]
    assert any(e.get("kind") == "domain_scope" for e in row["evidence"])
    assert row["nav_group"] == "crawlability"
    assert row["source"] == "robots"


def test_v2_source_normalization():
    issue = {"source": "hybrid", "category": "gsc_indexing", "issue_type": "gsc_index_verdict_fail"}
    assert _normalize_v2_source(issue) == "gsc"
    assert _normalize_v2_source({"source": "crawl", "category": "robots", "issue_type": "robots_unreachable"}) == "robots"
    assert _normalize_v2_source({"source": "unknown", "category": "onpage"}) == "crawl"
    assert _normalize_v2_source({"source": "crawl", "category": "onpage"}) in V2_SOURCES


def test_v2_nav_group_summaries_all_sidebar_groups():
    payload = {
        "domain": "example.com",
        "source_url": "https://example.com",
        "pages_scanned": 1,
        "issues": [
            {
                "type": "missing_title",
                "severity": "high",
                "message": "No title",
                "url": "https://example.com/page",
                "checklist_group": "Onpage",
            }
        ],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 1,
            "total_technical_issues": 1,
            "health_score": 80,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    dash = build_technical_dashboard_v2(build_saas_technical_payload(payload), payload)
    groups = [s["group"] for s in dash["nav_group_summaries"]]
    assert groups == list(V2_SIDEBAR_GROUPS)
    assert dash["nav_group_summaries"][0]["group"] == "overview"
    assert dash["score_explanation"] == [] or isinstance(dash["score_explanation"], list)
    assert all(s["issue_count"] >= 0 for s in dash["nav_group_summaries"])


def test_v2_priority_issues_status_filter():
    payload = {
        "domain": "example.com",
        "pages_scanned": 1,
        "issues": [
            {
                "type": "robots_disallow_all",
                "severity": "critical",
                "message": "Blocked",
                "checklist_group": "Robots",
            },
            {
                "type": "missing_favicon",
                "severity": "low",
                "message": "No favicon",
                "url": "https://example.com/",
                "checklist_group": "Onpage",
            },
        ],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 1,
            "total_technical_issues": 2,
            "health_score": 60,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": ["/"], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    dash = build_technical_dashboard_v2(build_saas_technical_payload(payload), payload)
    for p in dash["priority_issues"]:
        assert p["status"] in ("failed", "warning", "opportunity")
    assert len(dash["priority_issues"]) <= 10


def test_v2_issue_is_publishable_requires_technical_evidence_and_urls():
    """Không publish khi chỉ có mô tả, hoặc chỉ có URL mà không có evidence kỹ thuật."""
    assert not _v2_issue_is_publishable({"evidence": [{"kind": "description", "text": "x"}], "affected_urls": []})
    assert not _v2_issue_is_publishable({"evidence": [], "affected_urls": ["https://example.com/a"]})
    assert not _v2_issue_is_publishable({"evidence": [], "affected_urls": []})
    assert not _v2_issue_is_publishable({"evidence": [{}], "affected_urls": []})
    assert _v2_issue_is_publishable(
        {
            "evidence": [{"kind": "http_status", "value": 404}],
            "affected_urls": ["https://example.com/a"],
        }
    )
    assert _v2_issue_is_publishable(
        {
            "evidence": [{"kind": "domain_scope", "domain": "example.com", "text": "robots"}],
            "affected_urls": [],
        }
    )


def test_build_technical_dashboard_v2_shape():
    payload = {
        "domain": "example.com",
        "source_url": "https://example.com",
        "pages_scanned": 2,
        "issues": [
            {
                "type": "robots_disallow_all",
                "severity": "critical",
                "message": "Blocked",
                "checklist_group": "Robots",
            },
            {
                "type": "missing_favicon",
                "severity": "low",
                "message": "No icon",
                "url": "https://example.com/",
                "checklist_group": "Onpage",
            },
        ],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 2,
            "total_technical_issues": 2,
            "health_score": 60,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": ["/"], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    saas = build_saas_technical_payload(payload)
    dash = build_technical_dashboard_v2(saas, payload)
    assert dash["schema_version"] == 2
    assert dash["summary"]["total"] >= 2
    assert dash["summary"]["critical"] >= 1
    assert isinstance(dash["issues"], list)
    assert isinstance(dash["priority_issues"], list)
    assert isinstance(dash["nav_group_summaries"], list)
    assert len(dash["nav_group_summaries"]) == len(V2_SIDEBAR_GROUPS)
    assert "score_explanation" in dash


def test_build_saas_api_extensions_includes_dashboard_v2():
    payload = {
        "domain": "example.com",
        "pages_scanned": 1,
        "issues": [
            {
                "type": "missing_title",
                "severity": "high",
                "message": "x",
                "url": "https://example.com/a",
                "checklist_group": "Onpage",
            }
        ],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 1,
            "total_technical_issues": 1,
            "health_score": 80,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    ext = build_saas_api_extensions(payload)
    assert "technical_dashboard_v2" in ext
    assert ext["technical_dashboard_v2"]["schema_version"] == 2
    assert isinstance(ext["normalized_issues"], list)


def test_empty_saas_api_extensions_has_dashboard_v2():
    ext = empty_saas_api_extensions()
    assert "technical_dashboard_v2" in ext
    assert ext["technical_dashboard_v2"]["issues"] == []
    assert ext["technical_dashboard_v2"]["score_explanation"] == []
    assert len(ext["technical_dashboard_v2"]["nav_group_summaries"]) == len(V2_SIDEBAR_GROUPS)


def test_technical_analyze_response_accepts_dashboard_v2():
    legacy = {
        "domain": "old.com",
        "pages_scanned": 1,
        "issues": [],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 1,
            "total_technical_issues": 0,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": [], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
        "technical_dashboard_v2": empty_technical_dashboard_v2(),
    }
    model = TechnicalAnalyzeResponse.model_validate(legacy)
    assert model.technical_dashboard_v2.get("schema_version") == 2


def _v2_issue(
    *,
    issue_type: str,
    severity: str = "warning",
    nav_group: str = "onpage",
    url: str | None = None,
    title: str = "",
) -> dict:
    row = {
        "issue_id": f"{issue_type}_abc123",
        "issue_type": issue_type,
        "title": title or issue_type.replace("_", " "),
        "category": "onpage",
        "nav_group": nav_group,
        "severity": severity,
        "priority_score": 50,
        "confidence": 0.8,
        "source": "crawl",
        "affected_urls": [url] if url else [],
        "sample_urls": [url] if url else [],
        "evidence": [{"kind": "description", "text": "test"}],
        "why_it_matters": "x",
        "how_to_fix": "y",
        "impact": ["serp"],
        "status": "warning",
    }
    return row


def test_v2_url_repeat_factor_logarithmic():
    assert _v2_url_repeat_factor(1) == 1.0
    f10 = _v2_url_repeat_factor(10)
    f100 = _v2_url_repeat_factor(100)
    assert f10 < f100
    assert f100 <= 2.0
    assert 10 * _v2_url_repeat_factor(10) < 10 * 10  # sublinear vs linear


def test_v2_minor_issue_dampening_on_secondary_pages():
    major_units, _ = _v2_issue_penalty_units(
        severity="warning",
        issue_type="broken_internal_link",
        url_count=5,
        secondary_url_count=5,
    )
    minor_units, reason = _v2_issue_penalty_units(
        severity="warning",
        issue_type="missing_meta_description",
        url_count=5,
        secondary_url_count=5,
        title="Thiếu meta description",
    )
    assert minor_units < major_units * 0.5
    assert "lỗi nhỏ" in reason
    assert "trang phụ" in reason


def test_calculate_technical_health_score_v2_clean_site():
    result = calculate_technical_health_score_v2([])
    assert result["technical_health_score"] == 100.0
    assert result["weighted_penalties"] == 0.0
    assert len(result["score_explanation"]) == len(V2_SCORE_WEIGHTS)


def test_calculate_technical_health_score_v2_critical_penalty():
    issues = [
        _v2_issue(issue_type="robots_disallow_all", severity="critical", nav_group="crawlability"),
    ]
    result = calculate_technical_health_score_v2(issues)
    assert result["technical_health_score"] <= 82.0
    crawl = next(e for e in result["score_explanation"] if e["bucket"] == "crawlability")
    assert crawl["penalty_points"] > 0
    assert crawl["contributors"][0]["severity"] == "critical"


def test_calculate_technical_health_score_v2_gsc_only_when_real():
    gsc_issue = _v2_issue(
        issue_type="gsc_index_verdict_fail",
        severity="critical",
        nav_group="gsc_insights",
    )
    without = calculate_technical_health_score_v2([gsc_issue], raw_payload={"gsc_summary": {"enabled": False}})
    assert without["gsc_included"] is False
    assert without["technical_health_score"] == 100.0

    with_gsc = calculate_technical_health_score_v2(
        [gsc_issue],
        raw_payload={
            "gsc_summary": {
                "enabled": True,
                "connected": True,
                "impressions": 100,
                "clicks": 5,
            }
        },
    )
    assert with_gsc["gsc_included"] is True
    assert with_gsc["technical_health_score"] < 100.0
    idx = next(e for e in with_gsc["score_explanation"] if e["bucket"] == "indexability")
    assert idx["penalty_points"] > 0


def test_build_technical_dashboard_v2_uses_v2_scoring():
    payload = {
        "domain": "example.com",
        "source_url": "https://example.com",
        "pages_scanned": 3,
        "issues": [
            {
                "type": "robots_disallow_all",
                "severity": "critical",
                "message": "Blocked",
                "checklist_group": "Robots",
            },
            {
                "type": "missing_meta_description",
                "severity": "medium",
                "message": "No meta",
                "url": "https://example.com/blog/post-1",
                "checklist_group": "Onpage",
            },
            {
                "type": "missing_meta_description",
                "severity": "medium",
                "message": "No meta",
                "url": "https://example.com/blog/post-2",
                "checklist_group": "Onpage",
            },
        ],
        "technical_summary": {
            "broken_internal_links": 0,
            "broken_internal_404": 0,
            "redirect_chains": 0,
            "internal_pages": 3,
            "total_technical_issues": 3,
            "health_score": 60,
        },
        "broken_internal_links": [],
        "redirect_chains": [],
        "internal_link_structure": [],
        "robots": {"url": "", "status": 200, "disallow": ["/"], "sitemaps": []},
        "sitemap": {"url": "", "status": 200, "urls": []},
    }
    dash = build_technical_dashboard_v2(build_saas_technical_payload(payload), payload)
    assert "technical_health_score" in dash
    assert dash["technical_health_score"] == dash["health_score"]
    assert dash["technical_health_score"] < 100.0
    assert isinstance(dash["score_explanation"], list)
    assert len(dash["score_explanation"]) == len(V2_SCORE_WEIGHTS)
    assert dash["scoring"]["formula"] == "100 - weighted_penalties"
    onpage = next(e for e in dash["score_explanation"] if e["bucket"] == "onpage")
    assert onpage["penalty_points"] < 5.0  # minor issues on secondary pages stay light


def test_gsc_has_real_data():
    assert not _gsc_has_real_data({"gsc_summary": {"enabled": False}})
    assert not _gsc_has_real_data({"gsc_summary": {"enabled": True, "connected": True}})
    assert _gsc_has_real_data(
        {"gsc_summary": {"enabled": True, "connected": True, "impressions": 10}}
    )
