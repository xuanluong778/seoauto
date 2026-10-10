"""Regression tests for performance, security, schema, mobile, and GSC hybrid."""

from app.services.gsc_client import GscPermissionError, GscQuotaError
from app.services.gsc_enrichment import enrich_technical_audit_with_gsc
from app.services.gsc_priority import gsc_evidence_badge
from app.services.perf_security_schema_rules import (
    build_cwv_issues_from_metrics,
    build_perf_security_schema_issues,
    fetch_crux_origin,
    parse_crux_record,
)
from app.services.schema_validator import extract_jsonld_from_html, validate_schemas
from app.services.technical_output_normalizer import _map_category_to_nav_group, _map_v2_severity


def _page(url: str, html: str, **extra):
    row = {"url": url, "status": 200, "html": html}
    row.update(extra)
    return row


def test_cwv_emits_only_with_numeric_p75():
    poor = build_cwv_issues_from_metrics(url="https://ex.com/", lcp_ms=4500, inp_ms=None, cls=None)
    assert any(i["type"] == "cwv_lcp_poor" for i in poor)
    assert poor[0]["severity"] == "high"
    assert poor[0]["evidence"]
    assert poor[0]["remediation"]

    good = build_cwv_issues_from_metrics(url="https://ex.com/", lcp_ms=1800, inp_ms=120, cls=0.05)
    assert good == []

    none = build_cwv_issues_from_metrics(url="https://ex.com/")
    assert none == []


def test_cwv_not_invented_from_html_without_metrics():
    html = "<html><head><title>Slow looking page</title></head><body><img src='/hero.jpg'></body></html>"
    issues = build_perf_security_schema_issues([_page("https://ex.com/", html)])
    assert not any(i["type"].startswith("cwv_") for i in issues)


def test_parse_crux_record_p75():
    parsed = parse_crux_record(
        {
            "record": {
                "key": {"origin": "https://ex.com", "formFactor": "PHONE"},
                "metrics": {
                    "largest_contentful_paint": {"percentiles": {"p75": 4200}},
                    "interaction_to_next_paint": {"percentiles": {"p75": 80}},
                    "cumulative_layout_shift": {"percentiles": {"p75": 0.2}},
                },
            }
        }
    )
    assert parsed["lcp_ms"] == 4200
    assert parsed["inp_ms"] == 80
    assert parsed["cls"] == 0.2
    issues = build_perf_security_schema_issues([], start_url="https://ex.com/", crux=parsed)
    types = {i["type"] for i in issues}
    assert "cwv_lcp_poor" in types
    assert "cwv_inp_poor" not in types
    assert "cwv_cls_poor" in types


def test_fetch_crux_origin_fail_open(monkeypatch):
    monkeypatch.setenv("CRUX_API_KEY", "unit-test-key")
    monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)

    class Resp:
        status_code = 404

        def json(self):
            return {"error": "not found"}

    monkeypatch.setattr(
        "app.services.perf_security_schema_rules.requests.post",
        lambda *a, **k: Resp(),
    )
    assert fetch_crux_origin("https://example.com") is None

    monkeypatch.delenv("CRUX_API_KEY", raising=False)
    assert fetch_crux_origin("https://example.com") is None


def test_mixed_content_and_http_internal_links():
    html = """
    <html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    </head><body>
      <img src="http://ex.com/a.jpg">
      <script src="http://cdn.ex.com/app.js"></script>
      <a href="http://ex.com/old">old</a>
      <a href="https://ex.com/ok">ok</a>
    </body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/", html)])
    types = {i["type"] for i in issues}
    assert "mixed_content" in types
    assert "http_internal_links" in types
    mixed = next(i for i in issues if i["type"] == "mixed_content")
    assert mixed["severity"] == "high"
    assert mixed["source"] == "crawl"
    assert mixed["affected_urls"]


def test_schema_org_http_not_mixed_content():
    html = """
    <html><head><meta charset="utf-8">
    <link rel="schema" href="http://schema.org/">
    </head><body>ok</body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/", html)])
    assert not any(i["type"] == "mixed_content" for i in issues)


def test_jsonld_parse_error_and_missing_required_field():
    bad = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">{not json</script>
    </head><body></body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/p", bad)])
    assert any(i["type"] == "jsonld_parse_error" for i in issues)

    incomplete = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"Article"}</script>
    </head><body></body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/a", incomplete)])
    assert any(i["type"] == "schema_missing_required_field" for i in issues)


def test_no_schema_issue_when_jsonld_absent_or_valid():
    none = "<html><head><meta charset='utf-8'></head><body>Hi</body></html>"
    issues = build_perf_security_schema_issues([_page("https://ex.com/", none)])
    assert not any(i["type"].startswith("schema_") or i["type"].startswith("jsonld_") for i in issues)

    valid = """
    <html><head><meta charset="utf-8">
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Article","headline":"Hello","author":"A"}
    </script></head><body></body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/", valid)])
    assert not any(i["type"].startswith("schema_") or i["type"] == "jsonld_parse_error" for i in issues)


def test_extract_jsonld_flatten_graph():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme"}]}
    </script>
    """
    nodes, errs = extract_jsonld_from_html(html)
    assert errs == []
    assert any(n.get("@type") == "Organization" for n in nodes)
    result = validate_schemas(nodes)
    assert result["valid"] is True


def test_charset_and_viewport_no_scale():
    html = """
    <html><head>
      <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, maximum-scale=1">
    </head><body>x</body></html>
    """
    issues = build_perf_security_schema_issues([_page("https://ex.com/", html)])
    types = {i["type"] for i in issues}
    assert "missing_charset" in types
    assert "viewport_no_scale" in types


def test_hsts_only_when_headers_present():
    html = "<html><head><meta charset='utf-8'></head><body></body></html>"
    no_hdr = build_perf_security_schema_issues([_page("https://ex.com/", html)])
    assert not any(i["type"] == "missing_hsts" for i in no_hdr)

    missing = build_perf_security_schema_issues(
        [_page("https://ex.com/", html, response_headers={"content-type": "text/html"})]
    )
    assert any(i["type"] == "missing_hsts" for i in missing)

    present = build_perf_security_schema_issues(
        [
            _page(
                "https://ex.com/",
                html,
                response_headers={"Strict-Transport-Security": "max-age=31536000"},
            )
        ]
    )
    assert not any(i["type"] == "missing_hsts" for i in present)


def test_nav_groups_perf_security_schema_mobile():
    assert _map_category_to_nav_group({"issue_type": "cwv_lcp_poor", "source": "crux"}) == "performance"
    assert _map_category_to_nav_group({"issue_type": "mixed_content", "source": "hybrid"}) == "security_http"
    assert _map_category_to_nav_group({"issue_type": "jsonld_parse_error", "source": "crawl"}) == "structured_data"
    assert _map_category_to_nav_group({"issue_type": "viewport_no_scale", "source": "crawl"}) == "ux_mobile"
    assert _map_v2_severity({"issue_type": "cwv_lcp_poor", "severity": "high"}) == "warning"
    assert _map_v2_severity({"issue_type": "crawl_http_3xx", "severity": "medium"}) == "warning"


def test_gsc_confirms_http_and_noindex():
    assert (
        gsc_evidence_badge(
            {"type": "crawl_http_4xx"},
            inspection={"page_fetch_state": "NOT_FOUND"},
        )
        == "gsc_confirmed"
    )
    assert (
        gsc_evidence_badge(
            {"type": "meta_robots_noindex"},
            inspection={"indexing_state": "BLOCKED_BY_META_TAG"},
        )
        == "gsc_confirmed"
    )
    assert (
        gsc_evidence_badge(
            {"type": "crawled_url_robots_blocked"},
            inspection={"robots_txt_state": "DISALLOWED"},
        )
        == "gsc_confirmed"
    )


def test_gsc_quota_and_permission_do_not_raise(monkeypatch):
    issues = [
        {
            "type": "missing_title",
            "severity": "high",
            "message": "x",
            "url": "https://ex.com/",
            "source": "crawl",
        }
    ]

    class QuotaClient:
        def fetch_page_performance(self, **kwargs):
            raise GscQuotaError("unit quota")

        def inspect_url(self, **kwargs):
            raise AssertionError("inspect should stop after analytics quota is optional")

    monkeypatch.setattr("app.services.gsc_enrichment.GscClient.for_user", lambda uid: QuotaClient())
    out = enrich_technical_audit_with_gsc(
        user_id=1,
        gsc_property="https://ex.com/",
        start_url="https://ex.com/",
        pages=[{"url": "https://ex.com/", "status": 200}],
        sitemap={},
        issues=list(issues),
        page_audits=[],
        url_inspection_limit=0,
    )
    assert out["partial_data"] is True
    assert out["gsc_summary"]["quota_exceeded"] is True
    assert out["issues"]

    class PermClient:
        def fetch_page_performance(self, **kwargs):
            raise GscPermissionError("unit perm")

    monkeypatch.setattr("app.services.gsc_enrichment.GscClient.for_user", lambda uid: PermClient())
    perm = enrich_technical_audit_with_gsc(
        user_id=1,
        gsc_property="https://ex.com/",
        start_url="https://ex.com/",
        pages=[{"url": "https://ex.com/", "status": 200}],
        sitemap={},
        issues=list(issues),
        page_audits=[],
        url_inspection_limit=0,
    )
    assert perm["partial_data"] is True
    assert perm["gsc_summary"]["connected"] is False
    assert perm["gsc_summary"]["enabled"] is True


def test_gsc_confirmed_sets_hybrid_source(monkeypatch):
    issues = [
        {
            "type": "crawl_http_4xx",
            "severity": "high",
            "message": "404",
            "url": "https://ex.com/gone",
            "source": "crawl",
        }
    ]

    class Client:
        def fetch_page_performance(self, **kwargs):
            return [
                {
                    "page": "https://ex.com/gone",
                    "impressions": 200,
                    "clicks": 4,
                    "ctr": 0.02,
                    "position": 7.0,
                }
            ]

        def inspect_url(self, **kwargs):
            return {
                "inspection_url": kwargs["inspection_url"],
                "status": "ok",
                "page_fetch_state": "NOT_FOUND",
                "index_verdict": "FAIL",
                "coverage_state": "Not found (404)",
            }

    monkeypatch.setattr("app.services.gsc_enrichment.GscClient.for_user", lambda uid: Client())
    out = enrich_technical_audit_with_gsc(
        user_id=1,
        gsc_property="https://ex.com/",
        start_url="https://ex.com/",
        pages=[{"url": "https://ex.com/gone", "status": 404}],
        sitemap={},
        issues=issues,
        page_audits=[],
        url_inspection_limit=5,
    )
    issue = out["issues"][0]
    assert issue["gsc_badge"] == "gsc_confirmed"
    assert issue["source"] == "hybrid"
    assert issue["priority_score"] is not None
    assert out["gsc_summary"]["connected"] is True
    assert out["partial_data"] is False
