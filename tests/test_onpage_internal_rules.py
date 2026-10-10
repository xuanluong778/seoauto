"""Regression tests for on-page + internal-link upgrades."""

from app.services.internal_link_graph import build_link_graph
from app.services.onpage_internal_rules import (
    build_duplicate_content_issues,
    build_graph_link_issues,
    build_internal_redirect_issue,
    dedupe_technical_issues,
    evaluate_hreflang_page,
    internal_redirect_is_material,
    is_valid_hreflang_code,
)
from app.services.seo_rule_engine import (
    build_page_rule_context,
    evaluate_images_broken_src,
    evaluate_missing_viewport,
    evaluate_title_too_short,
    run_rules,
)
from app.services.structured_parser import parse_structured_html


def test_parser_extracts_viewport_hreflang_and_broken_images():
    html = """
    <html><head>
      <title>Page</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <link rel="alternate" hreflang="en" href="https://ex.com/en">
      <link rel="alternate" hreflang="x-default" href="https://ex.com/">
    </head><body>
      <h1>Hello</h1>
      <img src="" alt="empty">
      <img src="javascript:void(0)" alt="js">
      <img src="/ok.png" alt="fine">
    </body></html>
    """
    parsed = parse_structured_html(html, "https://ex.com/en")
    assert parsed["viewport"].startswith("width=device-width")
    assert len(parsed["hreflang"]) == 2
    assert parsed["images_broken_src"] >= 2
    assert parsed["images_missing_alt"] == 0


def test_parser_counts_missing_alt_not_decorative():
    html = '<html><body><img src="/a.png"><img src="/icon.png" class="icon" width="16" height="16"></body></html>'
    parsed = parse_structured_html(html, "https://ex.com/")
    assert parsed["images_missing_alt"] == 1


def test_title_too_short_and_viewport_rules():
    ctx = build_page_rule_context(
        url="https://ex.com/p",
        status=200,
        parsed={"title": "Hi", "viewport": "", "word_count": 400, "h1_count": 1, "meta_description": "d" * 40},
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    short = evaluate_title_too_short(ctx)
    assert short is not None
    assert short["evidence"]
    assert short["affected_urls"] == ["https://ex.com/p"]
    vp = evaluate_missing_viewport(ctx)
    assert vp is not None
    assert vp["rule_id"] == "missing_viewport"


def test_images_broken_src_rule_needs_count():
    ctx = build_page_rule_context(
        url="https://ex.com/p",
        status=200,
        parsed={
            "title": "A title here",
            "images_broken_src": 2,
            "images_broken_samples": [""],
            "h1_count": 1,
            "word_count": 400,
        },
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    hit = evaluate_images_broken_src(ctx)
    assert hit is not None
    assert any(e.get("kind") == "images_broken_src" for e in hit["evidence"])


def test_duplicate_title_h1_meta_clusters():
    rows = [
        {
            "url": "https://ex.com/a",
            "status": 200,
            "title": "Same Title Here",
            "h1s": ["Same H1 Here"],
            "meta_description": "shared meta description text",
        },
        {
            "url": "https://ex.com/b",
            "status": 200,
            "title": "Same Title Here",
            "h1s": ["Same H1 Here"],
            "meta_description": "shared meta description text",
        },
        {
            "url": "https://ex.com/c",
            "status": 200,
            "title": "Unique",
            "h1s": ["Other"],
            "meta_description": "different meta description unique",
        },
    ]
    issues = build_duplicate_content_issues(rows)
    types = {i["type"] for i in issues}
    assert "duplicate_title" in types
    assert "duplicate_h1" in types
    assert "duplicate_meta_description" in types
    title = next(i for i in issues if i["type"] == "duplicate_title")
    assert set(title["affected_urls"]) == {"https://ex.com/a", "https://ex.com/b"}
    assert title["evidence"]
    assert title["remediation"]


def test_no_duplicate_issue_for_single_url():
    rows = [
        {
            "url": "https://ex.com/a",
            "status": 200,
            "title": "Only",
            "h1s": ["Only H1"],
            "meta_description": "only this meta",
        }
    ]
    assert build_duplicate_content_issues(rows) == []


def test_hreflang_invalid_and_missing_self():
    parsed = {
        "hreflang": [
            {"hreflang": "english", "href": "https://ex.com/en"},
            {"hreflang": "vi", "href": "https://ex.com/vi"},
        ]
    }
    issues = evaluate_hreflang_page("https://ex.com/fr", parsed, 200)
    types = {i["type"] for i in issues}
    assert "hreflang_invalid_code" in types
    assert "hreflang_missing_self" in types
    assert is_valid_hreflang_code("en-US")
    assert is_valid_hreflang_code("x-default")
    assert not is_valid_hreflang_code("english")


def test_hreflang_silent_when_no_tags():
    assert evaluate_hreflang_page("https://ex.com/", {"hreflang": []}, 200) == []


def test_internal_redirect_material_vs_slash_only():
    assert internal_redirect_is_material(
        "https://ex.com/old",
        ["https://ex.com/old", "https://ex.com/new"],
    )
    assert not internal_redirect_is_material(
        "https://ex.com/about",
        ["https://ex.com/about", "https://ex.com/about/"],
    )
    issue = build_internal_redirect_issue(
        {
            "url": "https://ex.com/old",
            "status": 200,
            "chain": ["https://ex.com/old", "https://ex.com/new"],
            "is_broken": False,
        }
    )
    assert issue is not None
    assert issue["type"] == "internal_link_redirect"
    assert issue["evidence"]


def test_orphan_requires_enough_pages_and_edges():
    pages = [
        {"url": "https://ex.com/", "status": 200, "html": '<a href="/a">a</a>', "internal_links": ["https://ex.com/a"]},
        {"url": "https://ex.com/a", "status": 200, "html": "<p>a</p>", "internal_links": []},
        {"url": "https://ex.com/orphan", "status": 200, "html": "<p>o</p>", "internal_links": []},
    ]
    issues = build_graph_link_issues(pages, entry_urls=["https://ex.com/"])
    types = {i["type"] for i in issues}
    assert "orphan_page" in types
    orphan = next(i for i in issues if i["type"] == "orphan_page")
    assert "orphan" in orphan["url"]
    assert orphan["evidence"]
    assert any(e.get("kind") == "in_degree" for e in orphan["evidence"])


def test_orphan_not_emitted_with_two_pages():
    pages = [
        {"url": "https://ex.com/", "status": 200, "html": "", "internal_links": []},
        {"url": "https://ex.com/a", "status": 200, "html": "", "internal_links": []},
    ]
    assert build_graph_link_issues(pages, entry_urls=["https://ex.com/"]) == []


def test_crawl_depth_deep_gated():
    pages = []
    pages.append(
        {
            "url": "https://ex.com/",
            "status": 200,
            "html": '<a href="/p1">',
            "internal_links": ["https://ex.com/p1"],
        }
    )
    for i in range(1, 9):
        nxt = f"https://ex.com/p{i}"
        nxt2 = f"https://ex.com/p{i + 1}"
        links = [nxt2] if i < 8 else []
        html = f'<a href="/p{i + 1}">x</a>' if i < 8 else "<p>end</p>"
        pages.append({"url": nxt, "status": 200, "html": html, "internal_links": links})
    graph = build_link_graph(pages, entry_urls=["https://ex.com/"])
    assert graph["crawl_depth"].get("https://ex.com/p8") == 8
    issues = build_graph_link_issues(pages, entry_urls=["https://ex.com/"], min_pages_depth=8, deep_depth=4)
    deep = [i for i in issues if i["type"] == "crawl_depth_deep"]
    assert deep
    assert all(int(next(e["value"] for e in i["evidence"] if e["kind"] == "crawl_depth")) >= 4 for i in deep)


def test_dedupe_drops_weaker_redirect_and_alias_canonical():
    issues = [
        {
            "type": "internal_link_redirect",
            "severity": "medium",
            "confidence": 0.8,
            "url": "https://ex.com/a",
            "affected_urls": ["https://ex.com/a"],
            "evidence": [{"kind": "hops", "value": 1}],
            "remediation": "fix",
        },
        {
            "type": "redirect_loop",
            "severity": "high",
            "confidence": 0.95,
            "url": "https://ex.com/a",
            "affected_urls": ["https://ex.com/a"],
            "evidence": [{"kind": "redirect_loop", "urls": ["https://ex.com/a"]}],
            "remediation": "fix",
        },
        {
            "type": "missing_canonical",
            "severity": "medium",
            "confidence": 0.7,
            "url": "https://ex.com/b",
            "affected_urls": ["https://ex.com/b"],
            "evidence": [{"kind": "canonical_url", "value": ""}],
            "remediation": "add canonical",
        },
        {
            "type": "canonical_missing_high_value",
            "severity": "low",
            "confidence": 0.62,
            "url": "https://ex.com/b",
            "affected_urls": ["https://ex.com/b"],
            "evidence": [{"kind": "canonical_url", "value": ""}],
            "remediation": "add canonical",
        },
        {
            "type": "broken_internal_link",
            "severity": "high",
            "confidence": 0.9,
            "url": "https://ex.com/missing",
            "affected_urls": ["https://ex.com/missing"],
            "evidence": [{"kind": "http_status", "value": 404}],
            "remediation": "fix",
        },
        {
            "type": "crawl_http_4xx",
            "severity": "high",
            "confidence": 0.93,
            "url": "https://ex.com/missing",
            "affected_urls": ["https://ex.com/missing"],
            "evidence": [{"kind": "http_status", "value": 404}],
            "remediation": "fix",
        },
    ]
    out = dedupe_technical_issues(issues)
    types_a = {i["type"] for i in out if i.get("url") == "https://ex.com/a"}
    assert types_a == {"redirect_loop"}
    types_b = {i["type"] for i in out if i.get("url") == "https://ex.com/b"}
    assert types_b == {"canonical_missing_high_value"}
    types_m = {i["type"] for i in out if i.get("url") == "https://ex.com/missing"}
    assert types_m == {"broken_internal_link"}


def test_dedupe_same_type_url_keeps_higher_confidence():
    issues = [
        {
            "type": "missing_title",
            "severity": "high",
            "confidence": 0.5,
            "url": "https://ex.com/x",
            "evidence": [{"kind": "title", "value": ""}],
            "remediation": "add",
        },
        {
            "type": "missing_title",
            "severity": "high",
            "confidence": 0.97,
            "url": "https://ex.com/x",
            "evidence": [{"kind": "title", "value": ""}],
            "remediation": "add",
        },
    ]
    out = dedupe_technical_issues(issues)
    assert len(out) == 1
    assert out[0]["confidence"] == 0.97


def test_run_rules_missing_title_has_contract():
    ctx = build_page_rule_context(
        url="https://ex.com/p",
        status=200,
        parsed={
            "title": "",
            "h1_count": 1,
            "word_count": 400,
            "meta_description": "desc",
            "viewport": "width=device-width",
        },
        page_type="article",
        crawl_record={
            "indexability": {"indexable": True, "indexability_confidence": 0.9},
            "canonical_resolution": {"canonical_url": "https://ex.com/p"},
            "seo_signals": {},
            "raw_vs_rendered": {"identical": True},
        },
    )
    issues = run_rules(ctx)
    title = next(i for i in issues if i["rule_id"] == "missing_title")
    assert title["url"] == "https://ex.com/p"
    assert title["evidence"]
    assert title["how_to_fix"]
