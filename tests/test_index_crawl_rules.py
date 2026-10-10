"""Tests for Indexability & Crawlability rule upgrades."""

from app.services.crawler import (
    classify_http_status,
    classify_request_error,
    parse_sitemap_xml,
    robots_url_blocked,
)
from app.services.index_crawl_rules import (
    build_sitemap_indexability_issues,
    internal_link_issue_message,
    internal_link_issue_type,
    robots_fetch_issue_type,
    sitemap_missing_issue_type,
)
from app.services.seo_rule_engine import (
    build_page_rule_context,
    evaluate_canonical_points_to_bad_status,
    evaluate_canonical_scheme_mismatch,
    evaluate_meta_robots_noindex,
    evaluate_x_robots_tag_noindex,
    run_rules,
)
from app.services.technical_output_normalizer import (
    _expand_and_dedupe_v2_issues,
    _map_category_to_nav_group,
    _v2_issue_is_publishable,
    normalize_crawl_issues,
)


def test_classify_http_status():
    assert classify_http_status(403) == "forbidden"
    assert classify_http_status(502) == "server_error"
    assert classify_http_status(301) == "redirect"
    assert classify_http_status(200) is None


def test_robots_url_blocked():
    body = "User-agent: *\nDisallow: /private/\n"
    assert robots_url_blocked("https://ex.com/private/page", body) is True
    assert robots_url_blocked("https://ex.com/public/", body) is False


def test_internal_link_issue_type_classification():
    assert internal_link_issue_type({"status": 404, "error_kind": "client_error"})[0] == "broken_internal_link"
    assert internal_link_issue_type({"status": 410, "error_kind": "client_error"})[0] == "broken_internal_link"
    assert internal_link_issue_type({"status": 0, "error_kind": "dns_error"})[0] == "internal_link_dns_error"
    assert internal_link_issue_type({"status": 0, "error_kind": "ssl_error"})[0] == "internal_link_ssl_error"
    assert internal_link_issue_type({"status": 0, "error_kind": "timeout"})[0] == "internal_link_timeout"
    assert internal_link_issue_type({"status": 403, "error_kind": "forbidden"})[0] == "internal_link_forbidden"
    assert internal_link_issue_type({"status": 503, "error_kind": "server_error"})[0] == "internal_link_server_error"


def test_internal_link_404_410_messages_distinct():
    msg404 = internal_link_issue_message({"url": "https://ex.com/a", "status": 404})
    msg410 = internal_link_issue_message({"url": "https://ex.com/b", "status": 410})
    assert "404" in msg404
    assert "410" in msg410
    assert internal_link_issue_message({"url": "https://ex.com/c", "status": 0, "error_kind": "dns_error"}).startswith(
        "Liên kết nội bộ — lỗi DNS"
    )


def test_sitemap_missing_issue_type():
    assert sitemap_missing_issue_type({"last_error": {"http_status": 404}})[0] == "sitemap_not_found"
    assert sitemap_missing_issue_type({"last_error": {"http_status": 503}})[0] == "sitemap_unreachable"
    assert sitemap_missing_issue_type({"last_error": {"http_status": 0}})[0] == "sitemap_unreachable"


def test_robots_fetch_issue_type_dns():
    result = robots_fetch_issue_type({"status": 0, "error_kind": "dns_error", "url": "https://ex.com/robots.txt"})
    assert result == ("robots_dns_error", "high", "lỗi DNS")


def test_meta_robots_noindex_rule():
    ctx = build_page_rule_context(
        url="https://ex.com/page",
        status=200,
        parsed={"robots_meta": "noindex, nofollow"},
        page_type="article",
        crawl_record={
            "indexability": {
                "indexable": False,
                "meta_robots_text": "noindex, nofollow",
                "indexability_confidence": 0.95,
            },
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    ctx["final_indexability_resolved"] = False
    issue = evaluate_meta_robots_noindex(ctx)
    assert issue is not None
    assert issue["rule_id"] == "meta_robots_noindex"
    assert issue["confidence"] >= 0.9
    assert "meta_robots" in issue["detected_from"][0]


def test_x_robots_tag_noindex_rule():
    ctx = build_page_rule_context(
        url="https://ex.com/page",
        status=200,
        parsed={},
        page_type="article",
        crawl_record={
            "indexability": {
                "indexable": False,
                "x_robots_tag": "noindex",
                "indexability_confidence": 0.94,
            },
            "response_headers": {"x-robots-tag": "noindex"},
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    issue = evaluate_x_robots_tag_noindex(ctx)
    assert issue is not None
    assert issue["rule_id"] == "x_robots_tag_noindex"


def test_canonical_points_to_bad_status_rule():
    ctx = build_page_rule_context(
        url="https://ex.com/a",
        status=200,
        parsed={"canonical": "https://ex.com/b"},
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {
                "canonical_url": "https://ex.com/b",
                "final_effective_url": "https://ex.com/a",
            },
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    ctx["canonical_target_analysis"] = {"fetched": True, "target_status": 404, "target_indexable": False}
    issue = evaluate_canonical_points_to_bad_status(ctx)
    assert issue is not None
    assert issue["rule_id"] == "canonical_points_to_bad_status"


def test_canonical_scheme_mismatch_rule():
    ctx = build_page_rule_context(
        url="https://ex.com/page",
        status=200,
        parsed={},
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {
                "canonical_url": "http://ex.com/page",
                "final_effective_url": "https://ex.com/page",
            },
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    issue = evaluate_canonical_scheme_mismatch(ctx)
    assert issue is not None
    assert issue["rule_id"] == "canonical_scheme_mismatch"


def test_sitemap_contains_noindex_with_evidence():
    pages = [
        {
            "url": "https://ex.com/noindex-page",
            "indexability": {
                "indexable": False,
                "meta_robots_text": "noindex, follow",
                "indexability_confidence": 0.93,
            },
            "canonical_resolution": {"canonical_url": "https://ex.com/noindex-page", "final_effective_url": "https://ex.com/noindex-page"},
        }
    ]
    sitemap = {"status": 200, "urls": ["https://ex.com/noindex-page"]}
    robots = {"status": 200, "body_preview": "User-agent: *\nAllow: /\n", "url": "https://ex.com/robots.txt"}
    issues = build_sitemap_indexability_issues(
        sitemap=sitemap,
        pages=pages,
        robots=robots,
        check_url_status=lambda u: {"url": u, "status": 200, "is_broken": False},
    )
    assert len(issues) == 1
    assert issues[0]["type"] == "sitemap_contains_noindex"
    assert issues[0]["evidence"]
    assert issues[0]["confidence"] >= 0.9


def test_sitemap_contains_robots_blocked():
    pages = []
    sitemap = {"status": 200, "urls": ["https://ex.com/private/x"]}
    robots = {
        "status": 200,
        "body_preview": "User-agent: *\nDisallow: /private/\n",
        "url": "https://ex.com/robots.txt",
    }
    issues = build_sitemap_indexability_issues(
        sitemap=sitemap,
        pages=pages,
        robots=robots,
        check_url_status=lambda u: {"url": u, "status": 403, "is_broken": True, "error_kind": "forbidden"},
    )
    types = {i["type"] for i in issues}
    assert "sitemap_contains_robots_blocked" in types


def test_no_issue_without_evidence_sitemap_empty_cross():
    issues = build_sitemap_indexability_issues(
        sitemap={"status": 200, "urls": []},
        pages=[],
        robots={"status": 200, "body_preview": ""},
        check_url_status=lambda u: {"url": u, "status": 200},
    )
    assert issues == []


def test_nav_group_mapping_indexability():
    issue = {"category": "gsc_indexing", "issue_type": "meta_robots_noindex", "source": "crawl"}
    assert _map_category_to_nav_group(issue) == "indexability"
    issue2 = {"category": "website", "issue_type": "internal_link_dns_error", "source": "crawl"}
    assert _map_category_to_nav_group(issue2) == "crawlability"


def test_v2_dedupe_issue_id_and_url():
    raw_issues = [
        {
            "type": "sitemap_contains_noindex",
            "severity": "high",
            "message": "x",
            "url": "https://ex.com/a",
            "confidence": 0.9,
            "evidence": [{"kind": "sitemap_loc", "url": "https://ex.com/a"}],
            "checklist_group": "Sitemap",
        },
        {
            "type": "sitemap_contains_noindex",
            "severity": "high",
            "message": "x duplicate",
            "url": "https://ex.com/a",
            "confidence": 0.9,
            "evidence": [{"kind": "sitemap_loc", "url": "https://ex.com/a"}],
            "checklist_group": "Sitemap",
        },
    ]
    norm = normalize_crawl_issues(raw_issues)
    v2 = _expand_and_dedupe_v2_issues(norm, {"domain": "ex.com"})
    assert len(v2) == 1
    assert v2[0]["nav_group"] == "indexability"
    assert v2[0]["evidence"]


def test_run_rules_noindex_not_double_indexability_blocked():
    ctx = build_page_rule_context(
        url="https://ex.com/product",
        status=200,
        parsed={"robots_meta": "noindex"},
        page_type="product",
        crawl_record={
            "indexability": {
                "indexable": False,
                "meta_robots_text": "noindex",
                "indexability_confidence": 0.95,
            },
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    ctx["final_indexability_resolved"] = False
    issues = run_rules(ctx)
    ids = {i["rule_id"] for i in issues}
    assert "meta_robots_noindex" in ids
    assert "indexability_blocked" not in ids


def _assert_v2_issue_contract(row: dict) -> None:
    assert row.get("affected_urls")
    assert row.get("sample_urls")
    assert row.get("evidence")
    assert row.get("source")
    assert row.get("confidence", 0) > 0
    assert _v2_issue_is_publishable(row)


def test_v2_issue_contract_broken_internal_404():
    raw = [
        {
            "type": "broken_internal_link",
            "severity": "high",
            "message": "404",
            "url": "https://ex.com/missing",
            "confidence": 0.88,
            "evidence": [{"kind": "url", "url": "https://ex.com/missing"}, {"kind": "http_status", "value": 404}],
            "source": "crawl",
            "checklist_group": "GSC",
        }
    ]
    v2 = _expand_and_dedupe_v2_issues(normalize_crawl_issues(raw), {"domain": "ex.com"})
    assert len(v2) == 1
    _assert_v2_issue_contract(v2[0])
    assert v2[0]["nav_group"] == "internal_links"
    assert v2[0]["issue_type"] == "broken_internal_link"


def test_v2_issue_contract_redirect_chain_full_evidence():
    chain = [
        "https://ex.com/a",
        "https://ex.com/b",
        "https://ex.com/c",
        "https://ex.com/d",
        "https://ex.com/e",
    ]
    raw = [
        {
            "type": "redirect_chain",
            "severity": "medium",
            "message": "redirect",
            "url": "https://ex.com/a",
            "confidence": 0.85,
            "evidence": [
                {"kind": "url", "url": "https://ex.com/a"},
                {"kind": "redirect_chain", "value": chain},
                {"kind": "redirect_chain_urls", "urls": chain},
                {"kind": "hops", "value": 4},
            ],
            "source": "crawl",
            "checklist_group": "GSC",
        }
    ]
    v2 = _expand_and_dedupe_v2_issues(normalize_crawl_issues(raw), {"domain": "ex.com"})
    assert len(v2) == 1
    _assert_v2_issue_contract(v2[0])
    chain_ev = next(e for e in v2[0]["evidence"] if e.get("kind") == "redirect_chain")
    assert len(chain_ev["value"]) == 5


def test_v2_issue_contract_sitemap_not_found():
    raw = [
        {
            "type": "sitemap_not_found",
            "severity": "high",
            "message": "No sitemap",
            "url": "https://ex.com/sitemap.xml",
            "confidence": 0.88,
            "evidence": [
                {"kind": "sitemap_url", "url": "https://ex.com/sitemap.xml"},
                {"kind": "http_status", "value": 404},
            ],
            "source": "sitemap",
            "checklist_group": "Sitemap",
        }
    ]
    v2 = _expand_and_dedupe_v2_issues(normalize_crawl_issues(raw), {"domain": "ex.com"})
    assert len(v2) == 1
    _assert_v2_issue_contract(v2[0])
    assert v2[0]["nav_group"] == "indexability"
    assert v2[0]["source"] == "sitemap"


def test_v2_skips_issue_without_evidence_or_urls():
    raw = [
        {
            "type": "broken_internal_link",
            "severity": "high",
            "message": "no proof",
            "checklist_group": "GSC",
        }
    ]
    v2 = _expand_and_dedupe_v2_issues(normalize_crawl_issues(raw), {"domain": "ex.com"})
    assert v2 == []


def test_parse_robots_groups_keeps_agents_separate():
    from app.services.index_crawl_rules import parse_robots_agent_groups

    body = (
        "User-agent: AhrefsBot\n"
        "Disallow: /\n"
        "\n"
        "User-agent: *\n"
        "Disallow: /wp-admin/\n"
        "Allow: /wp-admin/admin-ajax.php\n"
    )
    groups = parse_robots_agent_groups(body)
    assert len(groups) == 2
    ahrefs = next(g for g in groups if "AhrefsBot" in g["agents"])
    star = next(g for g in groups if "*" in g["agents"])
    assert "/" in ahrefs["disallow"]
    assert "/" not in star["disallow"]


def test_googlebot_disallow_all_ignores_third_party_bots():
    from app.services.index_crawl_rules import googlebot_disallow_all_agents

    body = (
        "User-agent: AhrefsBot\nDisallow: /\n\n"
        "User-agent: GPTBot\nDisallow: /\n\n"
        "User-agent: *\nDisallow: /wp-admin/\n"
    )
    assert googlebot_disallow_all_agents(body) == []


def test_googlebot_disallow_all_flags_star_and_googlebot():
    from app.services.index_crawl_rules import googlebot_disallow_all_agents

    assert googlebot_disallow_all_agents("User-agent: *\nDisallow: /\n") == ["*"]
    agents = googlebot_disallow_all_agents("User-agent: Googlebot\nDisallow: /\n")
    assert any(a.lower() == "googlebot" for a in agents)


def test_analyze_robots_disallow_all_not_fired_for_ahrefs_only():
    from app.services.analyzer import _analyze_robots_txt_detailed

    robots = {
        "url": "https://ex.com/robots.txt",
        "status": 200,
        "sitemaps": [],
        "disallow": ["/", "/wp-admin/"],
        "body_preview": "User-agent: AhrefsBot\nDisallow: /\n\nUser-agent: *\nDisallow: /wp-admin/\n",
    }
    issues = _analyze_robots_txt_detailed(robots, "ex.com", "https")
    assert not any(i.get("type") == "robots_disallow_all" for i in issues)


def test_analyze_robots_disallow_all_has_evidence_when_star_blocked():
    from app.services.analyzer import _analyze_robots_txt_detailed

    robots = {
        "url": "https://ex.com/robots.txt",
        "status": 200,
        "sitemaps": [],
        "disallow": ["/"],
        "body_preview": "User-agent: *\nDisallow: /\n",
    }
    issues = _analyze_robots_txt_detailed(robots, "ex.com", "https")
    hit = [i for i in issues if i.get("type") == "robots_disallow_all"]
    assert len(hit) == 1
    assert hit[0].get("evidence")
    assert any(e.get("kind") == "user_agent" for e in hit[0]["evidence"])


def test_merge_link_check_trusts_crawled_slash_variant():
    from app.services.analyzer import _merge_internal_link_checks_with_crawl

    pages = [{"url": "https://ex.com/about/", "status": 200, "html": "<html>ok</html>"}]
    results = [{"url": "https://ex.com/about", "status": 0, "is_broken": True, "chain": [], "error_kind": "timeout"}]
    merged = _merge_internal_link_checks_with_crawl(pages, results)
    assert merged[0]["is_broken"] is False
    assert merged[0]["status"] == 200


def test_issues_to_legacy_copies_detected_from_as_evidence():
    from app.services.seo_rule_engine import issues_to_legacy_api_issues

    legacy = issues_to_legacy_api_issues(
        [
            {
                "rule_id": "missing_title",
                "issue": "Thiếu title",
                "severity": "high",
                "confidence": 0.9,
                "why_it_matters": "SERP",
                "detected_from": ["parsed.title"],
                "how_to_fix": ["Thêm title"],
            }
        ],
        "article",
    )
    assert legacy[0]["type"] == "missing_title"
    assert legacy[0]["evidence"]
    assert legacy[0]["evidence"][0]["kind"] == "detected_from"


def test_classify_http_issue_type_splits_status_classes():
    from app.services.index_crawl_rules import classify_http_issue_type

    assert classify_http_issue_type(301) == ("crawl_http_3xx", "medium")
    assert classify_http_issue_type(404) == ("crawl_http_4xx", "high")
    assert classify_http_issue_type(503) == ("crawl_http_5xx", "high")
    assert classify_http_issue_type(0, "timeout") == ("crawl_timeout", "high")
    assert classify_http_issue_type(0, "dns_error") == ("crawl_connection_error", "high")
    assert classify_http_issue_type(0, "ssl_error") == ("crawl_connection_error", "high")
    assert classify_http_issue_type(0, "redirect_loop") == ("redirect_loop", "high")


def test_redirect_loop_slice_and_hops():
    from app.services.index_crawl_rules import redirect_hops, redirect_loop_slice

    loop = ["https://ex.com/a", "https://ex.com/b", "https://ex.com/a"]
    assert redirect_loop_slice(loop) == loop
    assert redirect_loop_slice(["https://ex.com/a", "https://ex.com/b"]) is None
    assert redirect_hops(["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"]) == 2
    assert redirect_hops(["https://ex.com/a"]) == 0


def test_internal_link_redirect_loop_type():
    itype, sev = internal_link_issue_type(
        {
            "url": "https://ex.com/a",
            "status": 301,
            "error_kind": "redirect_loop",
            "is_broken": True,
        }
    )
    assert itype == "redirect_loop"
    assert sev == "high"
    assert "loop" in internal_link_issue_message(
        {"url": "https://ex.com/a", "status": 301, "error_kind": "redirect_loop"}
    ).lower()


def test_keep_evidenced_issues_drops_without_proof():
    from app.seo_pipeline.formatter import format_issue_list
    from app.services.index_crawl_rules import keep_evidenced_issues

    dropped = keep_evidenced_issues(
        format_issue_list(
            [
                {
                    "type": "crawl_http_4xx",
                    "severity": "high",
                    "message": "no proof",
                    "confidence": 0.9,
                }
            ]
        )
    )
    assert dropped == []

    kept = keep_evidenced_issues(
        format_issue_list(
            [
                {
                    "type": "crawl_http_4xx",
                    "severity": "high",
                    "message": "404",
                    "url": "https://ex.com/missing",
                    "confidence": 0.9,
                    "evidence": [
                        {"kind": "url", "url": "https://ex.com/missing"},
                        {"kind": "http_status", "value": 404},
                    ],
                }
            ]
        )
    )
    assert len(kept) == 1
    row = kept[0]
    assert row["severity"]
    assert float(row["confidence"]) > 0
    assert row["evidence"]
    assert row["affected_urls"] == ["https://ex.com/missing"]
    assert row.get("remediation") or row.get("suggested_fix")


def test_build_crawled_url_robots_blocked_has_contract():
    from app.services.index_crawl_rules import build_crawled_url_robots_blocked_issues

    pages = [{"url": "https://ex.com/private/x", "status": 200}]
    robots = {
        "status": 200,
        "body_preview": "User-agent: *\nDisallow: /private/\n",
        "url": "https://ex.com/robots.txt",
    }
    issues = build_crawled_url_robots_blocked_issues(pages=pages, robots=robots)
    assert len(issues) == 1
    assert issues[0]["type"] == "crawled_url_robots_blocked"
    assert issues[0]["severity"] == "high"
    assert issues[0]["confidence"] >= 0.9
    assert issues[0]["evidence"]
    assert issues[0]["affected_urls"] == ["https://ex.com/private/x"]
    assert issues[0]["remediation"]
    public = build_crawled_url_robots_blocked_issues(
        pages=[{"url": "https://ex.com/ok", "status": 200}],
        robots=robots,
    )
    assert public == []


def test_indexability_signal_conflict_requires_meta_vs_header():
    from app.services.seo_rule_engine import evaluate_indexability_signal_conflict

    ctx = build_page_rule_context(
        url="https://ex.com/page",
        status=200,
        parsed={"robots_meta": "index,follow"},
        page_type="article",
        crawl_record={
            "indexability": {
                "indexable": True,
                "meta_robots_text": "index,follow",
                "x_robots_tag": "",
                "indexability_confidence": 0.4,
            },
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    ctx["final_indexability_resolved"] = True
    assert evaluate_indexability_signal_conflict(ctx) is None

    ctx["indexability"]["x_robots_tag"] = "noindex"
    hit = evaluate_indexability_signal_conflict(ctx)
    assert hit is not None
    assert hit["rule_id"] == "indexability_signal_conflict"
    assert hit["evidence"]
    assert hit["affected_urls"] == ["https://ex.com/page"]


def test_canonical_missing_and_bad_status_carry_evidence():
    from app.services.seo_rule_engine import evaluate_canonical_missing_high_value

    ctx = build_page_rule_context(
        url="https://ex.com/article",
        status=200,
        parsed={"canonical": ""},
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {"canonical_url": "", "final_effective_url": "https://ex.com/article"},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    miss = evaluate_canonical_missing_high_value(ctx)
    assert miss is not None
    assert miss["evidence"]
    assert miss["url"] == "https://ex.com/article"

    ctx2 = build_page_rule_context(
        url="https://ex.com/a",
        status=200,
        parsed={"canonical": "https://ex.com/b"},
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {
                "canonical_url": "https://ex.com/b",
                "final_effective_url": "https://ex.com/a",
            },
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    ctx2["canonical_target_analysis"] = {"fetched": True, "target_status": 404, "target_indexable": False}
    bad = evaluate_canonical_points_to_bad_status(ctx2)
    assert bad is not None
    assert any(e.get("kind") == "http_status" and e.get("value") == 404 for e in bad["evidence"])
    assert bad["affected_urls"] == ["https://ex.com/a"]


def test_soft_404_requires_pattern_and_thin_content():
    from app.services.seo_rule_engine import evaluate_soft_404_heuristic

    ctx = build_page_rule_context(
        url="https://ex.com/gone",
        status=200,
        parsed={"title": "Page not found", "word_count": 20, "visible_text": "404 not found"},
        page_type="other",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    hit = evaluate_soft_404_heuristic(ctx)
    assert hit is not None
    assert any(e.get("kind") == "soft_404_pattern" for e in hit["evidence"])

    ctx["parsed"]["title"] = "About us"
    ctx["parsed"]["visible_text"] = "Hello world product catalog"
    assert evaluate_soft_404_heuristic(ctx) is None


def test_noindex_rules_include_contract_fields():
    ctx = build_page_rule_context(
        url="https://ex.com/page",
        status=200,
        parsed={"robots_meta": "noindex"},
        page_type="article",
        crawl_record={
            "indexability": {
                "indexable": False,
                "meta_robots_text": "noindex",
                "indexability_confidence": 0.95,
            },
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    issue = evaluate_meta_robots_noindex(ctx)
    assert issue["severity"]
    assert issue["confidence"] > 0
    assert issue["evidence"]
    assert issue["affected_urls"]
    assert issue["how_to_fix"]


def test_crawl_http_3xx_not_critical_in_v2():
    from app.services.technical_output_normalizer import _map_v2_severity

    assert _map_v2_severity({"issue_type": "crawl_http_3xx", "severity": "medium"}) == "warning"
    assert _map_v2_severity({"issue_type": "crawl_http_4xx", "severity": "high"}) == "critical"
    assert _map_v2_severity({"issue_type": "crawl_timeout", "severity": "high"}) == "critical"


def test_nav_group_robots_blocked_is_crawlability():
    issue = {"category": "robots", "issue_type": "crawled_url_robots_blocked", "source": "robots"}
    assert _map_category_to_nav_group(issue) == "crawlability"


def test_classify_too_many_redirects_as_loop():
    import requests

    from app.services.crawler import classify_request_error

    assert classify_request_error(requests.exceptions.TooManyRedirects("loop")) == "redirect_loop"


def test_v2_skips_issue_without_technical_evidence():
    raw = [
        {
            "type": "crawl_http_4xx",
            "severity": "high",
            "message": "guess",
            "checklist_group": "GSC",
        }
    ]
    v2 = _expand_and_dedupe_v2_issues(normalize_crawl_issues(raw), {"domain": "ex.com"})
    assert v2 == []
