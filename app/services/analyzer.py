import logging
import os
import re
import time
from collections.abc import Callable
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
from app.services.index_crawl_rules import (
    build_crawled_url_robots_blocked_issues,
    build_sitemap_indexability_issues,
    classify_http_issue_type,
    googlebot_disallow_all_agents,
    internal_link_issue_message,
    internal_link_issue_type,
    keep_evidenced_issues,
    redirect_hops,
    redirect_loop_slice,
    robots_fetch_issue_type,
    sitemap_missing_issue_type,
)
from app.services.onpage_internal_rules import (
    build_duplicate_content_issues,
    build_graph_link_issues,
    build_internal_redirect_issue,
    dedupe_technical_issues,
    evaluate_hreflang_page,
)
from app.services.perf_security_schema_rules import (
    build_perf_security_schema_issues,
    fetch_crux_origin,
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
    evidence: list[dict] | None = None,
    source: str | None = None,
    detected_from: list[str] | None = None,
    error_kind: str | None = None,
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
        d["affected_urls"] = [url]
    if remediation:
        d["remediation"] = remediation
    if confidence is not None:
        d["confidence"] = round(max(0.0, min(1.0, float(confidence))), 3)
    if explanation:
        d["explanation"] = explanation
    if page_type:
        d["page_type"] = page_type
    if evidence:
        d["evidence"] = evidence
    if source:
        d["source"] = source
    if detected_from:
        d["detected_from"] = detected_from
    if error_kind:
        d["error_kind"] = error_kind
    return d


MAX_INTERNAL_LINK_CHECKS = 220
# Ít worker hơn để host nhỏ không bị nghẽn / reset khiến hàng loạt HTTP 0.
_INTERNAL_LINK_WORKERS = 8


def _url_match_key(url: str) -> str:
    """Khóa so khớp URL (slash / encoding) — tránh báo broken khi crawl đã 200."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        from app.services.seo_normalize import normalize_url_safe

        return normalize_url_safe(raw).strip().lower().rstrip("/")
    except Exception:
        return raw.lower().rstrip("/")


def _merge_internal_link_checks_with_crawl(pages: list[dict], results: list[dict]) -> list[dict]:
    """Nếu URL đã crawl được 200 + HTML nhưng GET kiểm tra lỗi (HTTP 0), tin crawl — tránh báo sai."""
    ok_keys: set[str] = set()
    for page in pages:
        u = page.get("url")
        if not u or not isinstance(u, str):
            continue
        if int(page.get("status") or 0) != 200:
            continue
        html = page.get("html")
        if not isinstance(html, str) or not html.strip():
            continue
        key = _url_match_key(u)
        if key:
            ok_keys.add(key)

    merged: list[dict] = []
    for r in results:
        u = r.get("url") or ""
        if _url_match_key(u) in ok_keys and r.get("status") == 0:
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
                    confidence=0.9,
                    evidence=[
                        {"kind": "robots_txt", "url": robots.get("url")},
                        {"kind": "sitemap_line", "value": raw_sm},
                    ],
                    source="robots",
                    detected_from=["robots.txt", "Sitemap:"],
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
                    confidence=0.94,
                    evidence=[
                        {"kind": "robots_txt", "url": robots.get("url")},
                        {"kind": "sitemap_line", "value": raw_sm},
                        {"kind": "sitemap_host", "value": pn.netloc or ""},
                        {"kind": "site_host", "value": site_netloc},
                    ],
                    source="robots",
                    detected_from=["robots.txt", "Sitemap:", "host_mismatch"],
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
                        confidence=0.9 if st else 0.78,
                        evidence=[
                            {"kind": "robots_txt", "url": robots.get("url")},
                            {"kind": "sitemap_url", "url": sm_u},
                            {"kind": "http_status", "value": st},
                            *(
                                [{"kind": "error_kind", "value": chk.get("error_kind")}]
                                if chk.get("error_kind")
                                else []
                            ),
                        ],
                        source="robots",
                        detected_from=["robots.txt", "Sitemap:", "http_status"],
                        error_kind=str(chk.get("error_kind") or "") or None,
                        remediation=(
                            "Sửa URL trong robots.txt cho khớp file sitemap thực tế; kiểm tra firewall/CDN; "
                            "đảm bảo không redirect vòng hoặc 403 cho Googlebot."
                        ),
                    )
                )

    body = str(robots.get("body_preview") or "")
    google_block_agents = googlebot_disallow_all_agents(body)
    if google_block_agents:
        agent_label = ", ".join(google_block_agents[:6])
        issues.append(
            _tech_issue(
                "robots_disallow_all",
                "high",
                "Phát hiện Disallow: / cho User-agent * hoặc Googlebot — có thể chặn toàn bộ site với Google.",
                url=robots.get("url"),
                confidence=0.96,
                evidence=[
                    {"kind": "robots_txt", "url": robots.get("url")},
                    {"kind": "disallow", "value": "/"},
                    {"kind": "user_agent", "value": agent_label},
                ],
                source="robots",
                detected_from=["robots.txt", "User-agent", "Disallow: /"],
                remediation=(
                    "Mở robots.txt, kiểm tra khối User-agent: * và Googlebot. Chỉ dùng Disallow: / khi thực sự muốn "
                    "chặn mọi URL (staging). Production không được để rule này cho Googlebot."
                ),
            )
        )

    broad_query_done = False
    for rule in robots.get("disallow") or []:
        rule_s = (rule or "").strip()
        if not rule_s:
            continue
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
                    confidence=0.55,
                    evidence=[
                        {"kind": "robots_txt", "url": robots.get("url")},
                        {"kind": "disallow", "value": rule_s},
                    ],
                    source="robots",
                    detected_from=["robots.txt", "Disallow"],
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
    deadline_monotonic: float | None = None,
    progress_hook: Callable[[int, str], None] | None = None,
) -> TechnicalAnalyzeResponse:
    try:
        normalized_start = normalize_url(start_url)
    except ValueError:
        normalized_start = ""
    parsed_start = urlparse(normalized_start) if normalized_start else None
    base_scheme = parsed_start.scheme if parsed_start else "https"
    base_netloc = parsed_start.netloc if parsed_start else ""

    debug = AuditDebugSession()

    def _prog(pct: int, msg: str) -> None:
        if progress_hook:
            try:
                progress_hook(int(pct), str(msg))
            except Exception:
                pass

    def _crawl_progress(done: int, total: int) -> None:
        tot = max(1, int(total or 1))
        _prog(5 + min(50, int(50 * done / tot)), f"Đã crawl {done}/{tot} trang…")

    _prog(4, "Đang crawl website…")
    crawled = run_technical_crawl(
        start_url,
        max_pages=max_pages,
        deadline_monotonic=deadline_monotonic,
        on_progress=_crawl_progress,
    )
    crawl_partial = bool(crawled.get("partial_data") or crawled.get("truncated"))
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
                confidence=0.97,
                evidence=[
                    {"kind": "url", "url": normalized_start},
                    {"kind": "scheme", "value": "http"},
                ],
                source="crawl",
                detected_from=["start_url_scheme"],
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
    remain = None if deadline_monotonic is None else (float(deadline_monotonic) - time.monotonic())
    link_cap = MAX_INTERNAL_LINK_CHECKS
    if remain is not None:
        if remain < 8:
            link_cap = 0
        else:
            est = int(remain * _INTERNAL_LINK_WORKERS / max(1.0, float(LINK_CHECK_TIMEOUT_SECONDS)))
            link_cap = max(8, min(MAX_INTERNAL_LINK_CHECKS, est))
    if len(unique_targets) > link_cap:
        technical_issues.append(
            _tech_issue(
                "link_check_truncated",
                "low",
                f"Site có {len(unique_targets)} URL đích nội bộ; chỉ kiểm tra tối đa {link_cap} URL "
                f"(theo thứ tự alphabet) để tránh treo quá lâu.",
                url=normalized_start or start_url,
                confidence=0.99,
                evidence=[
                    {"kind": "internal_target_count", "value": len(unique_targets)},
                    {"kind": "check_cap", "value": link_cap},
                    *([{"kind": "url", "url": normalized_start}] if normalized_start else []),
                ],
                source="crawl",
                detected_from=["internal_link_check", "truncation"],
                remediation="Giảm max_pages khi quét, hoặc tách audit theo section; ưu tiên sửa các URL đích đầu danh sách.",
            )
        )
        unique_targets = unique_targets[:link_cap]

    _prog(58, "Đang kiểm tra liên kết nội bộ…")
    checked_links = _merge_internal_link_checks_with_crawl(
        pages,
        _parallel_check_internal_links(unique_targets),
    )

    broken_links: list[dict] = []
    broken_internal_urls: set[str] = set()
    for result in checked_links:
        if not result["is_broken"]:
            continue
        broken_links.append({"url": result["url"], "status": result["status"], "error_kind": result.get("error_kind")})
        u = str(result.get("url") or "").strip()
        if not u:
            continue
        key = _url_match_key(u)
        if key:
            broken_internal_urls.add(key)
        issue_type, sev = internal_link_issue_type(result)
        status = int(result.get("status") or 0)
        kind = result.get("error_kind") or ""
        chain = list(result.get("chain") or [u])
        loop = redirect_loop_slice(chain)
        if loop:
            technical_issues.append(
                _tech_issue(
                    "redirect_loop",
                    "high",
                    f"Vòng redirect (loop) trên liên kết nội bộ: {' → '.join(loop[:8])}",
                    url=u,
                    confidence=0.95,
                    evidence=[
                        {"kind": "url", "url": u},
                        {"kind": "redirect_chain", "value": chain},
                        {"kind": "redirect_loop", "urls": loop},
                        {"kind": "http_status", "value": status},
                    ],
                    source="crawl",
                    detected_from=["internal_link_check", "redirect_loop"],
                    error_kind="redirect_loop",
                )
            )
            continue
        evidence = [
            {"kind": "url", "url": u},
            {"kind": "http_status", "value": status},
        ]
        if kind:
            evidence.append({"kind": "error_kind", "value": kind})
        if chain:
            evidence.append({"kind": "redirect_chain", "value": chain[:8]})
        technical_issues.append(
            _tech_issue(
                issue_type,
                sev,
                internal_link_issue_message(result),
                url=u,
                confidence=0.88 if status else 0.75,
                evidence=evidence,
                source="crawl",
                detected_from=["internal_link_check", f"http_status:{status}"],
                error_kind=str(kind) if kind else None,
            )
        )

    redirect_chains = []
    for result in checked_links:
        if result.get("is_broken"):
            continue
        chain = list(result.get("chain") or [])
        if redirect_loop_slice(chain):
            continue
        hops = redirect_hops(chain)
        if hops >= 2:
            redirect_chains.append({"url": result["url"], "chain": chain, "hops": hops})
            continue
        redir = build_internal_redirect_issue(result)
        if redir:
            technical_issues.append(redir)
    for chain in redirect_chains:
        full_chain = list(chain["chain"])
        technical_issues.append(
            _tech_issue(
                "redirect_chain",
                "medium",
                f"Chuỗi redirect dài ({chain['hops']} bước) — ảnh hưởng crawl budget: {chain['url']}",
                url=chain["url"],
                confidence=0.88,
                evidence=[
                    {"kind": "url", "url": chain["url"]},
                    {"kind": "redirect_chain", "value": full_chain},
                    {"kind": "redirect_chain_urls", "urls": full_chain},
                    {"kind": "hops", "value": chain["hops"]},
                ],
                source="crawl",
                detected_from=["internal_link_check", "redirect_chain"],
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
                confidence=0.7,
                evidence=[
                    {"kind": "url", "url": start_page_url or normalized_start},
                    {"kind": "favicon_link", "value": False},
                ],
                source="crawl",
                detected_from=["homepage.html", "link[rel=icon]"],
            )
        )
    if start_html and not sig["html_lang"]:
        technical_issues.append(
            _tech_issue(
                "missing_html_lang",
                "medium",
                "Thiếu thuộc tính lang trên thẻ <html> — International / Technical-SEO.txt.",
                url=start_page_url or normalized_start,
                confidence=0.88,
                evidence=[
                    {"kind": "url", "url": start_page_url or normalized_start},
                    {"kind": "html_lang", "value": ""},
                ],
                source="crawl",
                detected_from=["homepage.html", "html[lang]"],
            )
        )

    from app.services.crawl_intelligence import enrich_page_crawl_intelligence

    _intel_domain = (base_domain or base_netloc or "").lower()
    if _intel_domain.startswith("www."):
        _intel_domain = _intel_domain[4:]
    for _pg in pages:
        if _pg.get("crawl_quality_score") is None:
            enrich_page_crawl_intelligence(_pg, domain=_intel_domain, proxy_server=_pg.get("proxy_used"))

    onpage_rows: list[dict] = []
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
            pkey = _url_match_key(purl)
            crawl_st = str(page.get("crawl_status") or "")
            kind = str(page.get("error_kind") or "")
            if not kind and crawl_st == "timeout":
                kind = "timeout"
            elif not kind and crawl_st in ("error", "blocked"):
                kind = "connection_error"
            should_emit_http = pstatus == 0 or (pstatus and pstatus != 200)
            if should_emit_http and pkey not in broken_internal_urls:
                html_len = len(html.strip())
                itype, sev = classify_http_issue_type(pstatus, kind)
                if itype == "crawl_timeout":
                    msg = f"Timeout khi crawl URL: {purl}"
                elif itype == "crawl_connection_error":
                    msg = f"Lỗi kết nối/DNS/SSL khi crawl URL: {purl}"
                elif itype == "redirect_loop":
                    msg = f"Vòng redirect khi crawl URL: {purl}"
                elif itype == "crawl_http_3xx":
                    msg = f"URL trong crawl trả HTTP {pstatus} (3xx): {purl}"
                elif itype == "crawl_http_4xx":
                    msg = f"URL trong crawl trả HTTP {pstatus} (4xx): {purl}"
                elif itype == "crawl_http_5xx":
                    msg = f"URL trong crawl trả HTTP {pstatus} (5xx): {purl}"
                else:
                    msg = (
                        f"URL trong crawl trả HTTP {pstatus}"
                        + (f" (có HTML {html_len} ký tự)" if html_len else " (không lấy được HTML)")
                        + f": {purl}"
                    )
                evidence = [
                    {"kind": "url", "url": purl},
                    {"kind": "http_status", "value": pstatus},
                    {"kind": "html_length", "value": html_len},
                ]
                if kind:
                    evidence.append({"kind": "error_kind", "value": kind})
                if crawl_st:
                    evidence.append({"kind": "crawl_status", "value": crawl_st})
                chain = list(page.get("redirect_history") or page.get("raw_redirect_history") or [])
                if chain:
                    evidence.append({"kind": "redirect_chain", "value": chain[:8]})
                technical_issues.append(
                    _tech_issue(
                        itype,
                        sev,
                        msg,
                        url=purl,
                        confidence=0.93 if pstatus else 0.82,
                        evidence=evidence,
                        source="crawl",
                        detected_from=["crawler.status", "http_status"],
                        error_kind=kind or None,
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
                    confidence=0.62,
                    evidence=[
                        {"kind": "url", "url": purl},
                        {"kind": "crawl_quality_score", "value": cq},
                        {"kind": "crawl_confidence_score", "value": cf},
                        {"kind": "reliability_flags", "value": flags},
                    ],
                    source="crawl",
                    detected_from=["crawl_quality", "skip_seo_analysis"],
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
            evidence = list(issue.get("evidence") or [])
            if not evidence:
                for field in issue.get("detected_from") or []:
                    evidence.append({"kind": "detected_from", "text": str(field)})
            if not any(isinstance(e, dict) and e.get("url") == purl for e in evidence):
                evidence.append({"kind": "url", "url": purl})
            technical_issues.append(
                {
                    "type": issue["type"],
                    "severity": issue["severity"],
                    "message": issue["message"],
                    "url": purl,
                    "affected_urls": list(issue.get("affected_urls") or [purl]),
                    "checklist_group": issue.get("checklist_group")
                    or TECH_CHECKLIST_BY_TYPE.get(issue["type"], "Onpage"),
                    "confidence": issue.get("confidence"),
                    "explanation": issue.get("explanation"),
                    "page_type": pt,
                    "evidence": evidence,
                    "detected_from": issue.get("detected_from"),
                    "source": issue.get("source") or "crawl",
                    "remediation": issue.get("remediation"),
                    "how_to_fix": issue.get("how_to_fix"),
                    "suppressed": issue.get("suppressed", False),
                }
            )
        for hf in evaluate_hreflang_page(purl, parsed, pstatus):
            technical_issues.append(hf)

        page_data = structured_to_legacy_page_data(parsed, pstatus)
        onpage_rows.append(
            {
                "url": purl,
                "status": pstatus,
                "title": page_data.get("title") or "",
                "h1s": parsed.get("h1") or [],
                "meta_description": page_data.get("meta_description") or "",
            }
        )

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
                        confidence=0.5,
                        evidence=[
                            {"kind": "url", "url": purl},
                            {"kind": "rel_next", "value": False},
                        ],
                        source="crawl",
                        detected_from=["pagination", "link[rel=next]"],
                    )
                )

    technical_issues.extend(build_duplicate_content_issues(onpage_rows))

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
    technical_issues.extend(
        build_graph_link_issues(pages, entry_urls=entry_for_graph)
    )
    crux = None
    try:
        origin = ""
        if parsed_start and parsed_start.netloc:
            origin = f"https://{parsed_start.netloc}"
        elif base_netloc:
            origin = f"https://{base_netloc}"
        if origin:
            crux = fetch_crux_origin(origin)
    except Exception as exc:
        _LOG.debug("CrUX skipped: %s", exc)
        crux = None
    technical_issues.extend(
        build_perf_security_schema_issues(pages, start_url=normalized_start or start_url, crux=crux)
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

    robots_fail = robots_fetch_issue_type(robots)
    if robots_fail:
        r_type, r_sev, r_suffix = robots_fail
        technical_issues.append(
            _tech_issue(
                r_type,
                r_sev,
                f"robots.txt {r_suffix} (Robots / Technical-SEO.txt).",
                url=robots.get("url"),
                confidence=0.9 if int(robots.get("status") or 0) else 0.78,
                evidence=[
                    {"kind": "robots_txt", "url": robots.get("url")},
                    {"kind": "http_status", "value": int(robots.get("status") or 0)},
                    *(
                        [{"kind": "error_kind", "value": robots.get("error_kind")}]
                        if robots.get("error_kind")
                        else []
                    ),
                ],
                source="robots",
                detected_from=["robots.txt", "http_status"],
            )
        )
    if sitemap.get("parse_error"):
        technical_issues.append(
            _tech_issue(
                "sitemap_parse_error",
                "high",
                f"Sitemap trả 200 nhưng XML không parse được: {sitemap.get('url') or sitemap.get('last_error', {}).get('url', '')}",
                url=sitemap.get("url") or (sitemap.get("last_error") or {}).get("url"),
                confidence=0.92,
                evidence=[
                    {"kind": "sitemap_url", "url": sitemap.get("url")},
                    {"kind": "parse_error", "value": True},
                    {"kind": "http_status", "value": 200},
                ],
                source="sitemap",
                detected_from=["sitemap.xml", "xml_parse"],
            )
        )
    elif sitemap.get("status", 0) != 200:
        sm_type, sm_message = sitemap_missing_issue_type(sitemap)
        sm_url = sitemap.get("url") or (sitemap.get("last_error") or {}).get("url") or ""
        last_err = sitemap.get("last_error") or {}
        technical_issues.append(
            _tech_issue(
                sm_type,
                "high",
                sm_message,
                url=sm_url or None,
                confidence=0.88 if sm_type == "sitemap_not_found" else 0.85,
                evidence=[
                    *([{"kind": "sitemap_url", "url": sm_url}] if sm_url else []),
                    {"kind": "http_status", "value": int(last_err.get("http_status") or 0)},
                    *(
                        [{"kind": "error_kind", "value": last_err.get("error_kind")}]
                        if last_err.get("error_kind")
                        else []
                    ),
                    *(
                        [{"kind": "domain_scope", "domain": base_netloc or base_domain}]
                        if not sm_url and (base_netloc or base_domain)
                        else []
                    ),
                ],
                source="sitemap",
                detected_from=["sitemap.xml", "http_status"],
            )
        )
    elif not (sitemap.get("urls") or []):
        technical_issues.append(
            _tech_issue(
                "sitemap_empty",
                "medium",
                "Sitemap trả 200 nhưng không có URL <loc> (Sitemap / Technical-SEO.txt).",
                url=sitemap.get("url"),
                confidence=0.9,
                evidence=[
                    {"kind": "sitemap_url", "url": sitemap.get("url")},
                    {"kind": "http_status", "value": 200},
                    {"kind": "loc_count", "value": 0},
                ],
                source="sitemap",
                detected_from=["sitemap.xml", "loc"],
            )
        )

    if (
        robots.get("status", 0) == 200
        and sitemap.get("status", 0) == 200
        and (sitemap.get("urls") or [])
        and not sitemap.get("parse_error")
    ):
        for raw_issue in build_sitemap_indexability_issues(
            sitemap=sitemap,
            pages=pages,
            robots=robots,
            check_url_status=check_internal_link_status,
        ):
            technical_issues.append(
                _tech_issue(
                    raw_issue["type"],
                    raw_issue["severity"],
                    raw_issue["message"],
                    url=raw_issue.get("url"),
                    checklist_group=raw_issue.get("checklist_group"),
                    confidence=raw_issue.get("confidence"),
                    evidence=raw_issue.get("evidence"),
                    source=raw_issue.get("source"),
                    detected_from=raw_issue.get("detected_from"),
                    error_kind=raw_issue.get("error_kind"),
                    remediation=raw_issue.get("remediation"),
                )
            )

    technical_issues.extend(build_crawled_url_robots_blocked_issues(pages=pages, robots=robots))

    seen_redirect_keys = {
        _url_match_key(str(i.get("url") or ""))
        for i in technical_issues
        if i.get("type") in ("redirect_chain", "redirect_loop")
    }
    for page in pages:
        purl = str(page.get("url") or "").strip()
        if not purl:
            continue
        chain = list(page.get("redirect_history") or page.get("raw_redirect_history") or [])
        loop = redirect_loop_slice(chain)
        pkey = _url_match_key(purl)
        if loop and pkey and pkey not in seen_redirect_keys:
            seen_redirect_keys.add(pkey)
            technical_issues.append(
                _tech_issue(
                    "redirect_loop",
                    "high",
                    f"Vòng redirect khi crawl: {' → '.join(loop[:8])}",
                    url=purl,
                    confidence=0.95,
                    evidence=[
                        {"kind": "url", "url": purl},
                        {"kind": "redirect_chain", "value": chain},
                        {"kind": "redirect_loop", "urls": loop},
                    ],
                    source="crawl",
                    detected_from=["crawler.redirect_history", "redirect_loop"],
                    error_kind="redirect_loop",
                )
            )
            continue
        hops = redirect_hops(chain)
        if hops >= 2 and pkey and pkey not in seen_redirect_keys:
            seen_redirect_keys.add(pkey)
            technical_issues.append(
                _tech_issue(
                    "redirect_chain",
                    "medium",
                    f"Chuỗi redirect dài ({hops} bước) khi crawl: {purl}",
                    url=purl,
                    confidence=0.88,
                    evidence=[
                        {"kind": "url", "url": purl},
                        {"kind": "redirect_chain", "value": chain},
                        {"kind": "hops", "value": hops},
                    ],
                    source="crawl",
                    detected_from=["crawler.redirect_history", "redirect_chain"],
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
                    confidence=0.86,
                    evidence=[
                        {"kind": "robots_txt", "url": robots.get("url")},
                        {"kind": "sitemap_url", "url": norm_sm},
                    ],
                    source="robots",
                    detected_from=["robots.txt", "Sitemap:"],
                    remediation=(
                        f"Thêm vào robots.txt: Sitemap: {norm_sm} "
                        "(hoặc URL sitemap index chính xác). Giúp Google/Bing không phụ thuộc chỉ đường dẫn mặc định."
                    ),
                )
            )

    broken_404_only = [b for b in broken_links if b.get("status") == 404]

    issues_out = keep_evidenced_issues(format_issue_list(dedupe_technical_issues(technical_issues)))
    scores = compute_audit_scores(issues_out)

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
    remain_gsc = None if deadline_monotonic is None else (float(deadline_monotonic) - time.monotonic())
    skip_gsc_budget = remain_gsc is not None and remain_gsc < 20
    if use_gsc and user_id and gsc_property and not skip_gsc_budget:
        _prog(82, "Đang lấy dữ liệu Search Console…")
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
            gs = gsc_payload.get("gsc_summary") or {}
            technical_summary_dict["partial_data"] = bool(
                gsc_payload.get("partial_data") or gs.get("partial_data") or gs.get("quota_exceeded")
            )
            technical_summary_dict["scan_mode"] = "hybrid" if gs.get("connected") else "crawl"
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("GSC enrichment failed (audit continues): %s", exc)
            gsc_payload = {
                "gsc_summary": {
                    "enabled": True,
                    "connected": False,
                    "partial_data": True,
                    "quota_exceeded": False,
                    "message": f"Không tích hợp được GSC: {exc}",
                    "errors": [str(exc)],
                },
                "partial_data": True,
                "issues": [dict(i) if hasattr(i, "model_dump") else i for i in issues_out],
            }
            technical_summary_dict["partial_data"] = True
            technical_summary_dict["scan_mode"] = "crawl"
            from app.services.gsc_enrichment import _apply_no_gsc_disclaimers

            _apply_no_gsc_disclaimers(gsc_payload["issues"])
            issues_final = gsc_payload["issues"]
    elif use_gsc and skip_gsc_budget:
        from app.services.gsc_enrichment import _apply_no_gsc_disclaimers

        raw_issues = [dict(i) if hasattr(i, "model_dump") else i for i in issues_out]
        _apply_no_gsc_disclaimers(raw_issues)
        issues_final = raw_issues
        technical_summary_dict["scan_mode"] = "crawl"
        technical_summary_dict["partial_data"] = True
        gsc_payload = {
            "gsc_summary": {
                "enabled": True,
                "connected": False,
                "partial_data": True,
                "message": "Bỏ qua GSC vì hết ngân sách thời gian quét — kết quả crawl vẫn được lưu.",
            },
            "partial_data": True,
            "issues": raw_issues,
        }
    else:
        from app.services.gsc_enrichment import _apply_no_gsc_disclaimers

        raw_issues = [dict(i) if hasattr(i, "model_dump") else i for i in issues_out]
        _apply_no_gsc_disclaimers(raw_issues)
        issues_final = raw_issues
        technical_summary_dict["scan_mode"] = "crawl"
        technical_summary_dict["partial_data"] = bool(crawl_partial)

    if crawl_partial:
        technical_summary_dict["partial_data"] = True

    _prog(92, "Đang tổng hợp báo cáo…")

    gs_out = gsc_payload.get("gsc_summary") or {}
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
        gsc_summary=gs_out or None,
        gsc_enriched_pages=gsc_payload.get("gsc_enriched_pages") or [],
        gsc_confirmed_issues=gsc_payload.get("gsc_confirmed_issues") or [],
        gsc_opportunities=gsc_payload.get("gsc_opportunities") or [],
        url_inspection_results=gsc_payload.get("url_inspection_results") or [],
        confidence_overall=gsc_payload.get("confidence_overall"),
        partial_data=bool(
            technical_summary_dict.get("partial_data")
            or gsc_payload.get("partial_data")
            or gs_out.get("partial_data")
        ),
    )
