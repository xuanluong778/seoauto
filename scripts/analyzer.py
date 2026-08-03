import logging
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from app.schemas import Issue, PageResult, SingleAnalyzeResponse, Summary, TechnicalAnalyzeResponse
from app.seo_pipeline.constants import TECH_CHECKLIST_BY_TYPE
from app.seo_pipeline.crawler_layer import run_technical_crawl
from app.seo_pipeline.formatter import format_issue_list
from app.seo_pipeline.ranking_pipeline import build_page_insights_for_crawl
from app.seo_pipeline.pipeline import run_page_pipeline
from app.seo_pipeline.scoring import compute_audit_scores
from app.services.crawler import (
    LINK_CHECK_TIMEOUT_SECONDS,
    check_internal_link_status,
    fetch_html,
    normalize_url,
    parse_robots_txt,
    parse_sitemap_xml,
)
from app.services.audit_debug import AuditDebugSession
from app.services.parser import parse_page, parse_page_seo_data
from app.services.structured_parser import structured_to_legacy_page_data

_LOG = logging.getLogger(__name__)


def _tech_issue(
    type_: str,
    severity: str,
    message: str,
    *,
    url: str | None = None,
    checklist_group: str | None = None,
    remediation: str | None = None,
    confidence: float | None = None,
    explanation: str | None = None,
    page_type: str | None = None,
) -> dict:
    group = checklist_group or TECH_CHECKLIST_BY_TYPE.get(type_, "General")
    d: dict = {
        "type": type_,
        "severity": severity,
        "message": message,
        "checklist_group": group,
    }
    if url:
        d["url"] = url
    if remediation:
        d["remediation"] = remediation
    if confidence is not None:
        d["confidence"] = round(max(0.0, min(1.0, float(confidence))), 3)
    if explanation:
        d["explanation"] = explanation
    if page_type:
        d["page_type"] = page_type
    return d


MAX_INTERNAL_LINK_CHECKS = 220
# Ít worker hơn để host nhỏ không bị nghẽn / reset khiến hàng loạt HTTP 0.
_INTERNAL_LINK_WORKERS = 8


def _merge_internal_link_checks_with_crawl(pages: list[dict], results: list[dict]) -> list[dict]:
    """Nếu URL đã crawl được 200 + HTML nhưng GET kiểm tra lỗi (HTTP 0), tin crawl — tránh báo sai."""
    ok_urls: set[str] = set()
    for page in pages:
        u = page.get("url")
        if not u or not isinstance(u, str):
            continue
        if int(page.get("status") or 0) != 200:
            continue
        html = page.get("html")
        if not isinstance(html, str) or not html.strip():
            continue
        ok_urls.add(u)

    merged: list[dict] = []
    for r in results:
        u = r.get("url") or ""
        if u in ok_urls and r.get("status") == 0:
            merged.append(
                {
                    **r,
                    "status": 200,
                    "is_broken": False,
                    "chain": r.get("chain") or [u],
                }
            )
            continue
        merged.append(r)
    return merged


def _parallel_check_internal_links(urls: list[str]) -> list[dict]:
    """Kiểm tra HEAD/GET song song — trước đây tuần tự nên site lớn treo rất lâu."""
    if not urls:
        return []
    workers = min(_INTERNAL_LINK_WORKERS, max(1, len(urls)))

    def _one(u: str) -> dict:
        return check_internal_link_status(u, timeout_seconds=LINK_CHECK_TIMEOUT_SECONDS)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, urls))


def _host_key(netloc: str) -> str:
    h = (netloc or "").strip().lower()
    if h.startswith("www."):
        return h[4:]
    return h


def _analyze_robots_txt_detailed(
    robots: dict,
    site_netloc: str,
    site_scheme: str,
) -> list[dict]:
    """Phân tích chi tiết robots.txt: sitemap sai domain, rule Disallow rộng, v.v."""
    issues: list[dict] = []
    if robots.get("status") != 200 or not site_netloc:
        return issues
    sk = _host_key(site_netloc)
    raw_sitemaps = [s.strip() for s in (robots.get("sitemaps") or []) if (s or "").strip()]

    for raw_sm in raw_sitemaps:
        sm_u = _normalize_sitemap_url(raw_sm, site_scheme, site_netloc)
        if not sm_u:
            issues.append(
                _tech_issue(
                    "robots_sitemap_invalid_url",
                    "medium",
                    f"Dòng Sitemap trong robots.txt không phải URL hợp lệ: «{raw_sm}».",
                    url=robots.get("url"),
                    remediation=(
                        "Đặt URL tuyệt đối dạng https://ten-mien-cua-ban.com/sitemap_index.xml. "
                        "Không để khoảng trắng thừa; chỉ một URL mỗi dòng Sitemap:."
                    ),
                )
            )
            continue
        pn = urlparse(sm_u)
        sm_host_key = _host_key(pn.netloc)
        if sm_host_key != sk:
            issues.append(
                _tech_issue(
                    "robots_sitemap_wrong_host",
                    "high",
                    f"Sitemap trong robots.txt thuộc domain khác với site đang quét: «{raw_sm}» "
                    f"(host sitemap: {pn.netloc or '—'}, host site: {site_netloc}). "
                    "Ví dụ: site thegioidigi.com nhưng Sitemap: trỏ tới gtvseo.com — sai cấu hình, Google có thể lập chỉ mục/thu thập không đồng bộ.",
                    url=robots.get("url"),
                    remediation=(
                        f"1) Mở {robots.get('url')} và sửa dòng Sitemap thành URL sitemap đúng domain "
                        f"(ví dụ: https://{site_netloc}/sitemap_index.xml hoặc /sitemap.xml tùy hệ thống).\n"
                        "2) Kiểm tra URL sitemap trả HTTP 200 và là XML hợp lệ.\n"
                        "3) Trong Google Search Console (property đúng domain), gửi lại sitemap mới; gỡ sitemap cũ sai domain nếu có."
                    ),
                )
            )
        else:
            chk = check_internal_link_status(sm_u)
            st = int(chk.get("status") or 0)
            if chk.get("is_broken") or st not in (200, 304):
                issues.append(
                    _tech_issue(
                        "robots_sitemap_unreachable",
                        "high",
                        f"Sitemap đã khai báo nhưng không truy cập được (HTTP {st}): {sm_u}.",
                        url=sm_u,
                        remediation=(
                            "Sửa URL trong robots.txt cho khớp file sitemap thực tế; kiểm tra firewall/CDN; "
                            "đảm bảo không redirect vòng hoặc 403 cho Googlebot."
                        ),
                    )
                )

    broad_query_done = False
    for rule in robots.get("disallow") or []:
        rule_s = (rule or "").strip()
        if not rule_s:
            continue
        if rule_s == "/":
            issues.append(
                _tech_issue(
                    "robots_disallow_all",
                    "high",
                    "Phát hiện Disallow: / — nếu áp dụng cho User-agent: * có thể chặn toàn bộ site với bot đó.",
                    url=robots.get("url"),
                    remediation=(
                        "Mở robots.txt, kiểm tra từng khối User-agent. Chỉ dùng Disallow: / khi thực sự muốn chặn mọi URL; "
                        "với Googlebot thông thường không được để rule này (trừ môi trường staging có chủ đích)."
                    ),
                )
            )
        if not broad_query_done and (
            "*?" in rule_s or rule_s in ("*/?", "/*?*", "*?") or "/?" in rule_s and "*" in rule_s
        ):
            broad_query_done = True
            issues.append(
                _tech_issue(
                    "robots_disallow_broad_querystring",
                    "low",
                    f"Rule Disallow «{rule_s}» có thể chặn hàng loạt URL có query string (?), gồm URL hợp lệ (lọc, tham số sản phẩm, v.v.).",
                    url=robots.get("url"),
                    remediation=(
                        "Rà trong GSC → Settings / Coverage các URL 'Excluded' do robots. "
                        "Thu hẹp rule: chỉ disallow path cụ thể (vd. /filter/, /wp-admin/) thay vì mọi URL có dấu ?. "
                        "Tránh broad *? nếu không chắc chắn."
                    ),
                )
            )

    return issues


def _normalize_sitemap_url(raw: str, scheme: str, netloc: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("//"):
        return f"{scheme}:{raw}"
    if "://" not in raw:
        return urlunparse((scheme, netloc, raw if raw.startswith("/") else f"/{raw}", "", "", ""))
    try:
        return normalize_url(raw)
    except ValueError:
        return None


def _homepage_extra_signals(html: str) -> dict:
    soup = BeautifulSoup(html if isinstance(html, str) else "", "html.parser")
    icon = soup.find("link", href=True, rel=lambda r: r is not None and "icon" in str(r).lower())
    html_el = soup.find("html")
    has_next = bool(
        soup.find("link", rel=lambda r: r is not None and "next" in str(r).lower())
    )
    return {
        "has_favicon": bool(icon and (icon.get("href") or "").strip()),
        "html_lang": ((html_el.get("lang") or "").strip() if html_el else ""),
        "has_rel_next": has_next,
    }


def analyze_url(raw_url: str) -> SingleAnalyzeResponse:
    normalized_url = normalize_url(raw_url)
    parsed = urlparse(normalized_url)

    html = fetch_html(normalized_url)
    page_data = parse_page(html)

    issues = []
    if not page_data["title"]:
        issues.append(
            Issue(
                type="missing_title",
                severity="high",
                message="Page is missing a title tag.",
                url=normalized_url,
            )
        )
    if not page_data["meta_description"]:
        issues.append(
            Issue(
                type="missing_meta_description",
                severity="medium",
                message="Page is missing a meta description.",
                url=normalized_url,
            )
        )
    if page_data["h1_count"] > 1:
        issues.append(
            Issue(
                type="multiple_h1",
                severity="low",
                message="Page has multiple H1 tags.",
                url=normalized_url,
            )
        )

    summary = Summary(
        total_issues=len(issues),
        high=sum(1 for issue in issues if issue.severity == "high"),
        medium=sum(1 for issue in issues if issue.severity == "medium"),
        low=sum(1 for issue in issues if issue.severity == "low"),
    )

    return SingleAnalyzeResponse(
        url=normalized_url,
        domain=parsed.netloc,
        pages_scanned=1,
        summary=summary,
        issues=issues,
        pages=[
            PageResult(
                url=normalized_url,
                title=page_data["title"],
                h1_count=page_data["h1_count"],
            )
        ],
    )


def _build_page_issues(page_data: dict) -> list[dict]:
    issues: list[dict] = []

    status = int(page_data.get("status", 0) or 0)
    title = page_data["title"]
    meta_description = page_data["meta_description"]
    canonical = page_data["canonical"]
    h1_count = page_data["h1_count"]
    word_count = page_data["word_count"]
    images_missing_alt = page_data["images_missing_alt"]

    if status != 200:
        issues.append(
            {
                "type": "http_status_error",
                "severity": "high",
                "message": f"Page returned non-200 status: {status}.",
            }
        )
        return issues

    if not title:
        issues.append(
            {
                "type": "missing_title",
                "severity": "high",
                "message": "Page is missing a title tag.",
            }
        )
    elif len(title) > 60:
        issues.append(
            {
                "type": "title_too_long",
                "severity": "medium",
                "message": "Title is longer than 60 characters.",
            }
        )

    if not meta_description:
        issues.append(
            {
                "type": "missing_meta_description",
                "severity": "high",
                "message": "Page is missing a meta description.",
            }
        )

    if not canonical:
        issues.append(
            {
                "type": "missing_canonical",
                "severity": "medium",
                "message": "Page is missing a canonical URL.",
            }
        )

    if h1_count > 1:
        issues.append(
            {
                "type": "multiple_h1",
                "severity": "medium",
                "message": "Page has more than one H1 tag.",
            }
        )
    elif h1_count == 0:
        issues.append(
            {
                "type": "missing_h1",
                "severity": "high",
                "message": "Page has no H1 tag.",
            }
        )

    if word_count < 300:
        issues.append(
            {
                "type": "thin_content",
                "severity": "medium",
                "message": "Page has thin content (under 300 words).",
            }
        )

    if images_missing_alt > 0:
        issues.append(
            {
                "type": "images_missing_alt",
                "severity": "low",
                "message": f"{images_missing_alt} image(s) missing alt text.",
            }
        )

    return issues


def analyze_crawled_pages(crawled_pages: list[dict]) -> dict:
    analyzed_pages: list[dict] = []
    summary = {
        "total_pages": 0,
        "total_issues": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }

    for page in crawled_pages:
        raw_url = str(page.get("url", "")).strip()
        if not raw_url:
            continue

        raw_status = page.get("status", 0)
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            status = 0

        try:
            normalized_url = normalize_url(raw_url)
        except ValueError:
            normalized_url = raw_url

        html = page.get("html")
        page_data = parse_page_seo_data(html if isinstance(html, str) else "")
        page_data["status"] = status
        page_issues = _build_page_issues(page_data)

        analyzed_pages.append(
            {
                "url": normalized_url,
                "status": status,
                "title": page_data["title"],
                "meta_description": page_data["meta_description"],
                "canonical": page_data["canonical"],
                "h1_count": page_data["h1_count"],
                "word_count": page_data["word_count"],
                "images_total": page_data["images_total"],
                "images_missing_alt": page_data["images_missing_alt"],
                "issues": page_issues,
            }
        )

        summary["total_pages"] += 1
        summary["total_issues"] += len(page_issues)
        summary["high"] += sum(1 for issue in page_issues if issue["severity"] == "high")
        summary["medium"] += sum(1 for issue in page_issues if issue["severity"] == "medium")
        summary["low"] += sum(1 for issue in page_issues if issue["severity"] == "low")

    return {
        "pages": analyzed_pages,
        "summary": summary,
    }


def analyze_technical_seo(
    start_url: str,
    max_pages: int = 50,
    *,
    user_keywords: list[str] | None = None,
    gsc_queries: list[dict] | None = None,
    project_id: int | None = None,
    enable_keyword_intelligence: bool | None = None,
    user_id: int | None = None,
    use_gsc: bool = False,
    gsc_property: str | None = None,
    gsc_date_range: str = "28d",
    gsc_start_date: str | None = None,
    gsc_end_date: str | None = None,
    url_inspection_limit: int = 10,
) -> TechnicalAnalyzeResponse:
    try:
        normalized_start = normalize_url(start_url)
    except ValueError:
        normalized_start = ""
    parsed_start = urlparse(normalized_start) if normalized_start else None
    base_scheme = parsed_start.scheme if parsed_start else "https"
    base_netloc = parsed_start.netloc if parsed_start else ""

    debug = AuditDebugSession()
    crawled = run_technical_crawl(start_url, max_pages=max_pages)
    pages = crawled["pages"]
    edges = crawled["edges"]
    base_domain = crawled["domain"]
    if not base_netloc and base_domain:
        base_netloc = base_domain

    technical_issues: list[dict] = []

    if parsed_start and parsed_start.scheme.lower() == "http":
        technical_issues.append(
            _tech_issue(
                "https_not_used",
                "high",
                "Trang bắt đầu dùng HTTP. Nên dùng HTTPS và redirect 301 (mục HTTPS / Technical-SEO.txt).",
                url=normalized_start,
                remediation=(
                    f"Bạn đã nhập URL dạng HTTP: {normalized_start}. Hệ thống kiểm tra đúng theo URL đó (không đoán redirect trình duyệt). "
                    f"Ví dụ thực tế — PowerShell: curl.exe -I \"{normalized_start}\" "
                    f"— cần thấy Location: https://… (301/308). Nếu vẫn 200 trên HTTP thì chưa ép SSL. "
                    "WordPress: Settings → General đặt cả hai địa chỉ là https://… "
                    "Hosting (cPanel/Plesk): bật chứng chỉ Let's Encrypt + «Force HTTPS Redirect». "
                    "Nginx ví dụ: return 301 https://$host$request_uri; — Apache: Redirect 301 / https://www.tenmien.com/. "
                    "Sau khi sửa, nhập lại URL audit bằng https://… để checklist đánh giá đúng property."
                ),
            )
        )

    unique_targets = sorted({edge["to"] for edge in edges})
    if len(unique_targets) > MAX_INTERNAL_LINK_CHECKS:
        technical_issues.append(
            _tech_issue(
                "link_check_truncated",
                "low",
                f"Site có {len(unique_targets)} URL đích nội bộ; chỉ kiểm tra tối đa {MAX_INTERNAL_LINK_CHECKS} URL "
                f"(theo thứ tự alphabet) để tránh treo quá lâu.",
                remediation="Giảm max_pages khi quét, hoặc tách audit theo section; ưu tiên sửa các URL đích đầu danh sách.",
            )
        )
        unique_targets = unique_targets[:MAX_INTERNAL_LINK_CHECKS]

    checked_links = _merge_internal_link_checks_with_crawl(
        pages,
        _parallel_check_internal_links(unique_targets),
    )

    broken_links: list[dict] = []
    for result in checked_links:
        if not result["is_broken"]:
            continue
        broken_links.append({"url": result["url"], "status": result["status"]})
    broken_internal_urls: set[str] = set()
    for b in broken_links:
        u = str(b.get("url") or "").strip()
        if not u:
            continue
        try:
            broken_internal_urls.add(normalize_url(u))
        except ValueError:
            broken_internal_urls.add(u)
        if result["status"] == 404:
            technical_issues.append(
                _tech_issue(
                    "broken_internal_link",
                    "high",
                    f"Liên kết nội bộ trả 404: {result['url']}",
                    url=result["url"],
                )
            )
        else:
            technical_issues.append(
                _tech_issue(
                    "broken_internal_http_error",
                    "high",
                    f"Liên kết nội bộ lỗi HTTP {result['status']}: {result['url']}",
                    url=result["url"],
                )
            )

    redirect_chains = [
        {"url": result["url"], "chain": result["chain"], "hops": len(result["chain"]) - 1}
        for result in checked_links
        if not result["is_broken"] and len(result["chain"]) >= 3
    ]
    for chain in redirect_chains:
        technical_issues.append(
            _tech_issue(
                "redirect_chain",
                "medium",
                f"Chuỗi redirect dài ({chain['hops']} bước) — ảnh hưởng crawl: {chain['url']}",
                url=chain["url"],
            )
        )

    start_page_url = pages[0]["url"] if pages else normalized_start
    start_html = ""
    for p in pages:
        if p["url"] == normalized_start or p["url"] == start_page_url:
            start_html = p.get("html") or ""
            break
    if not start_html and pages:
        start_html = pages[0].get("html") or ""

    sig = _homepage_extra_signals(start_html)
    if start_html and not sig["has_favicon"]:
        technical_issues.append(
            _tech_issue(
                "missing_favicon",
                "low",
                "Thiếu favicon (link rel=icon) trên trang chính — Technical-SEO.txt mục favicon.",
                url=start_page_url or normalized_start,
            )
        )
    if start_html and not sig["html_lang"]:
        technical_issues.append(
            _tech_issue(
                "missing_html_lang",
                "medium",
                "Thiếu thuộc tính lang trên thẻ <html> — International / Technical-SEO.txt.",
                url=start_page_url or normalized_start,
            )
        )

    from app.services.crawl_intelligence import enrich_page_crawl_intelligence

    _intel_domain = (base_domain or base_netloc or "").lower()
    if _intel_domain.startswith("www."):
        _intel_domain = _intel_domain[4:]
    for _pg in pages:
        if _pg.get("crawl_quality_score") is None:
            enrich_page_crawl_intelligence(_pg, domain=_intel_domain, proxy_server=_pg.get("proxy_used"))

    title_by_normalized: dict[str, list[str]] = defaultdict(list)
    staged_pipeline_rows: list[dict] = []

    kw_intel_on = enable_keyword_intelligence
    if kw_intel_on is None:
        kw_intel_on = os.getenv("KEYWORD_INTEL_DEFAULT", "0").lower() in ("1", "true", "yes")
    kw_bundle: dict | None = None
    kw_signals = None
    url_serp_overlay: dict = {}
    if kw_intel_on:
        from app.services.keyword_intelligence import build_keyword_intelligence_bundle
        from app.services.serp_intelligence import build_url_serp_audit_overlay

        kw_bundle = build_keyword_intelligence_bundle(
            pages,
            start_url,
            user_keywords=user_keywords,
            gsc_queries=gsc_queries,
        )
        url_serp_overlay = build_url_serp_audit_overlay(kw_bundle, pages)

    for page in pages:
        purl = page["url"]
        pstatus = int(page.get("status") or 0)
        html = page.get("html") if isinstance(page.get("html"), str) else ""
        if pstatus != 200 or not html.strip():
            if pstatus and pstatus != 200 and html == "":
                # Đã báo qua broken_internal_link / broken_internal_http_error → tránh trùng noise.
                try:
                    pkey = normalize_url(purl)
                except ValueError:
                    pkey = purl
                if pkey not in broken_internal_urls:
                    technical_issues.append(
                        _tech_issue(
                            "crawl_page_non_200",
                            "medium" if pstatus in (301, 302, 303, 307, 308) else "high",
                            f"URL trong crawl trả HTTP {pstatus} (không lấy được HTML): {purl}",
                            url=purl,
                        )
                    )
            continue

        if page.get("skip_seo_analysis"):
            cq = page.get("crawl_quality_score")
            cf = page.get("crawl_confidence_score")
            flags = page.get("reliability_flags") or []
            explain = page.get("crawl_quality_explain") or []
            explain_txt = "; ".join(
                f"{e.get('signal')}:{e.get('detail', '')[:120]}" for e in explain[:6] if isinstance(e, dict)
            )
            technical_issues.append(
                _tech_issue(
                    "crawl_data_low_trust",
                    "low",
                    f"Dữ liệu crawl độ tin cậy thấp (quality={cq}, confidence={cf}); bỏ qua SEO pipeline cho URL để giảm false positive.",
                    url=purl,
                    remediation="Kiểm tra chặn bot, proxy, render JS; thử crawl lại hoặc tăng chất lượng proxy/residential.",
                    explanation=(f"Flags: {flags}. " + explain_txt)[:1200],
                )
            )
            staged_pipeline_rows.append({"url": purl, "status": pstatus, "html": html, "bundle": None})
            continue

        _crawl_dbg_keys = (
            "raw_html",
            "raw_http_status",
            "raw_redirect_history",
            "raw_response_headers",
            "raw_vs_rendered",
            "canonical_resolution",
            "indexability",
            "seo_signals",
            "js_seo_risk_score",
            "js_seo_risk_level",
            "cloaking_risk",
            "cloaking_reason",
            "crawl_quality_score",
            "quality_level",
            "reliability_flags",
            "crawl_confidence_score",
            "data_trust",
            "skip_seo_analysis",
            "crawl_quality_explain",
            "proxy_used",
        )
        _crawl_record = {k: page[k] for k in _crawl_dbg_keys if k in page}
        if page.get("html") and "rendered_html" not in _crawl_record:
            _crawl_record["rendered_html"] = page["html"]

        serp_slot = url_serp_overlay.get(purl) or url_serp_overlay.get(purl.rstrip("/"))
        if serp_slot:
            sis = list(serp_slot.get("synthetic_issues") or [])
            if sis:
                _crawl_record["serp_synthetic_issues"] = sis

        bundle = run_page_pipeline(
            url=purl,
            status=pstatus,
            html=html,
            debug=debug,
            response_headers=page.get("response_headers"),
            crawl_record=_crawl_record or None,
        )
        staged_pipeline_rows.append(
            {"url": purl, "status": pstatus, "html": html, "bundle": bundle}
        )
        parsed = bundle.parsed
        pt = bundle.page_type
        for issue in bundle.issues:
            technical_issues.append(
                {
                    "type": issue["type"],
                    "severity": issue["severity"],
                    "message": issue["message"],
                    "url": purl,
                    "checklist_group": issue.get("checklist_group")
                    or TECH_CHECKLIST_BY_TYPE.get(issue["type"], "Onpage"),
                    "confidence": issue.get("confidence"),
                    "explanation": issue.get("explanation"),
                    "page_type": pt,
                }
            )

        page_data = structured_to_legacy_page_data(parsed, pstatus)
        t_norm = (page_data["title"] or "").strip().lower()
        if t_norm:
            title_by_normalized[t_norm].append(purl)

        path_lower = urlparse(purl).path.lower()
        if re.search(r"/page/\d+/?$", path_lower):
            psig = _homepage_extra_signals(html)
            if not psig["has_rel_next"]:
                technical_issues.append(
                    _tech_issue(
                        "pagination_missing_rel_next",
                        "low",
                        "Trang phân trang có thể thiếu rel=next trong <head> (Technical-SEO.txt).",
                        url=purl,
                    )
                )

    for _, urls in title_by_normalized.items():
        if len(urls) <= 1:
            continue
        technical_issues.append(
            _tech_issue(
                "duplicate_title",
                "medium",
                f"Trùng thẻ Title trên {len(urls)} URL: " + "; ".join(urls[:5])
                + ("…" if len(urls) > 5 else ""),
                url=urls[0],
            )
        )

    entry_for_graph = [normalized_start] if normalized_start else None

    if kw_intel_on and kw_bundle is not None:
        kw_signals = kw_bundle.get("url_signals") or None

    page_audits, ranking_priorities, site_graph_summary = build_page_insights_for_crawl(
        pages,
        staged_pipeline_rows,
        entry_urls=entry_for_graph,
        keyword_signals_by_url=kw_signals,
        serp_overlay_by_url=url_serp_overlay or None,
    )

    if kw_bundle is not None:
        from app.services.keyword_intelligence import attach_cluster_opportunities, persist_keyword_intel

        rank_map = {
            str(r.get("url") or ""): float((r.get("ranking") or {}).get("ranking_score") or 0.0)
            for r in page_audits
            if r.get("url")
        }
        wc_map = {
            str(p.get("url") or ""): len(re.findall(r"\w+", str(p.get("html") or "")))
            for p in pages
            if p.get("url")
        }
        kw_bundle = attach_cluster_opportunities(
            kw_bundle, ranking_by_url=rank_map, url_word_counts=wc_map
        )
        if project_id is not None:
            try:
                from app.db import SessionLocal

                db = SessionLocal()
                try:
                    persist_keyword_intel(db, project_id, kw_bundle)
                finally:
                    db.close()
            except Exception as exc:
                _LOG.warning("keyword_intel persist skipped: %s", exc)

    page_urls = {page["url"] for page in pages}
    inlinks = {url: 0 for url in page_urls}
    outlinks = {url: 0 for url in page_urls}
    for edge in edges:
        source = edge["from"]
        target = edge["to"]
        if source in outlinks:
            outlinks[source] += 1
        if target in inlinks:
            inlinks[target] += 1

    first_url = pages[0]["url"] if pages else ""
    internal_structure = [
        {
            "url": url,
            "inlinks": inlinks.get(url, 0),
            "outlinks": outlinks.get(url, 0),
            "is_orphan_like": inlinks.get(url, 0) == 0 and url != first_url,
        }
        for url in sorted(page_urls)
    ]

    robots = parse_robots_txt(start_url)
    if robots.get("status") == 200 and base_netloc:
        technical_issues.extend(_analyze_robots_txt_detailed(robots, base_netloc, base_scheme))
    sitemap = parse_sitemap_xml(start_url, robots_sitemaps=robots.get("sitemaps", []))

    if robots.get("status", 0) != 200:
        technical_issues.append(
            _tech_issue(
                "robots_unreachable",
                "high",
                "robots.txt không tồn tại hoặc không truy cập được (Robots / Technical-SEO.txt).",
            )
        )
    if sitemap.get("status", 0) != 200:
        technical_issues.append(
            _tech_issue(
                "sitemap_unreachable",
                "high",
                "sitemap.xml / sitemap_index không tồn tại hoặc không đọc được (Sitemap / Technical-SEO.txt).",
            )
        )
    elif not (sitemap.get("urls") or []):
        technical_issues.append(
            _tech_issue(
                "sitemap_empty",
                "medium",
                "Sitemap trả 200 nhưng không có URL <loc> (Sitemap / Technical-SEO.txt).",
                url=sitemap.get("url"),
            )
        )

    if (
        robots.get("status", 0) == 200
        and sitemap.get("status", 0) == 200
        and (sitemap.get("urls") or [])
    ):
        sm_url = sitemap.get("url") or ""
        norm_sm = _normalize_sitemap_url(sm_url, base_scheme, base_netloc)
        robots_sm_norm = {
            u
            for raw in (robots.get("sitemaps") or [])
            if (u := _normalize_sitemap_url(raw, base_scheme, base_netloc))
        }
        if norm_sm and norm_sm not in robots_sm_norm and not robots_sm_norm:
            technical_issues.append(
                _tech_issue(
                    "robots_missing_sitemap_line",
                    "medium",
                    "Chưa khai báo Sitemap: trong robots.txt dù crawler đã tìm được sitemap (Technical-SEO.txt — sitemap trong robots).",
                    url=robots.get("url"),
                    remediation=(
                        f"Thêm vào robots.txt: Sitemap: {norm_sm} "
                        "(hoặc URL sitemap index chính xác). Giúp Google/Bing không phụ thuộc chỉ đường dẫn mặc định."
                    ),
                )
            )

    broken_404_only = [b for b in broken_links if b.get("status") == 404]

    scores = compute_audit_scores(technical_issues)
    issues_out = format_issue_list(technical_issues)

    topical_rows = list((site_graph_summary or {}).get("topical_authority") or [])

    technical_summary_dict = {
        "start_url_scheme": (parsed_start.scheme.lower() if parsed_start else None),
        "start_url_normalized": normalized_start or None,
        "broken_internal_links": len(broken_links),
        "broken_internal_404": len(broken_404_only),
        "redirect_chains": len(redirect_chains),
        "internal_pages": len(page_urls),
        "total_technical_issues": len(issues_out),
        "health_score": scores.health_score,
        "weighted_penalty": scores.weighted_penalty,
        "issues_by_severity": scores.by_severity,
    }

    from app.services.seo_intelligence_core import build_seo_intelligence_core_v3

    seo_core = build_seo_intelligence_core_v3(
        page_audits=page_audits,
        technical_summary=technical_summary_dict,
        site_graph_summary=site_graph_summary or {},
        keyword_intelligence=kw_bundle,
        topical_authority=topical_rows,
        pages=pages,
        gsc_queries=gsc_queries,
        url_serp_overlay=url_serp_overlay,
        start_url=start_url,
    )

    # Hybrid GSC layer (optional) — never fails the whole audit
    gsc_payload: dict = {}
    issues_final = issues_out
    if use_gsc and user_id and gsc_property:
        try:
            from app.services.gsc_enrichment import enrich_technical_audit_with_gsc

            gsc_payload = enrich_technical_audit_with_gsc(
                user_id=user_id,
                gsc_property=gsc_property,
                gsc_date_range=gsc_date_range,
                gsc_start_date=gsc_start_date,
                gsc_end_date=gsc_end_date,
                url_inspection_limit=url_inspection_limit,
                start_url=start_url,
                pages=pages,
                sitemap=(
                    sitemap
                    if isinstance(sitemap, dict)
                    else (sitemap.model_dump() if hasattr(sitemap, "model_dump") else {})
                ),
                issues=[dict(i) if hasattr(i, "model_dump") else i for i in issues_out],
                page_audits=page_audits,
            )
            issues_final = gsc_payload.get("issues") or issues_out
            if gsc_payload.get("confidence_overall") is not None:
                technical_summary_dict["gsc_confidence"] = gsc_payload["confidence_overall"]
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("GSC enrichment failed (audit continues): %s", exc)
            gsc_payload = {
                "gsc_summary": {
                    "enabled": True,
                    "connected": False,
                    "partial_data": True,
                    "message": f"Không tích hợp được GSC: {exc}",
                    "errors": [str(exc)],
                },
            }
            from app.services.gsc_enrichment import _apply_no_gsc_disclaimers

            _apply_no_gsc_disclaimers(
                [dict(i) if hasattr(i, "model_dump") else i for i in issues_out]
            )
    else:
        from app.services.gsc_enrichment import _apply_no_gsc_disclaimers

        raw_issues = [dict(i) if hasattr(i, "model_dump") else i for i in issues_out]
        _apply_no_gsc_disclaimers(raw_issues)
        issues_final = raw_issues

    return TechnicalAnalyzeResponse(
        domain=base_domain,
        pages_scanned=len(pages),
        technical_summary=technical_summary_dict,
        broken_internal_links=broken_links,
        redirect_chains=redirect_chains,
        internal_link_structure=internal_structure,
        robots=robots,
        sitemap=sitemap,
        issues=issues_final,
        page_audits=page_audits,
        ranking_priorities=ranking_priorities,
        site_graph_summary=site_graph_summary,
        keyword_intelligence=kw_bundle,
        topical_authority=topical_rows,
        seo_intelligence_core=seo_core,
        gsc_summary=gsc_payload.get("gsc_summary"),
        gsc_enriched_pages=gsc_payload.get("gsc_enriched_pages") or [],
        gsc_confirmed_issues=gsc_payload.get("gsc_confirmed_issues") or [],
        gsc_opportunities=gsc_payload.get("gsc_opportunities") or [],
        url_inspection_results=gsc_payload.get("url_inspection_results") or [],
        confidence_overall=gsc_payload.get("confidence_overall"),
    )
