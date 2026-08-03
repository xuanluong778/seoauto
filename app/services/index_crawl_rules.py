"""
Indexability & Crawlability cross-check rules for Technical Analysis.

Site-level checks (sitemap ↔ robots ↔ crawl) with evidence required before emitting issues.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from app.services.crawler import classify_http_status, robots_url_blocked
from app.services.seo_normalize import normalize_url_safe

MAX_SITEMAP_CROSS_CHECKS = 80
MAX_SITEMAP_STATUS_PROBES = 40


def _norm_url_key(url: str) -> str:
    try:
        return normalize_url_safe(url).strip().lower().rstrip("/")
    except Exception:
        return (url or "").strip().lower().rstrip("/")


def _url_variants(url: str) -> set[str]:
    base = _norm_url_key(url)
    if not base:
        return set()
    out = {base}
    if base.endswith("/"):
        out.add(base.rstrip("/"))
    else:
        out.add(base + "/")
    return out


def _pages_lookup(pages_by_url: dict[str, dict]) -> dict[str, dict]:
    """Map normalized URL variants → page record."""
    out: dict[str, dict] = {}
    for raw_url, page in pages_by_url.items():
        for variant in _url_variants(raw_url):
            out.setdefault(variant, page)
    return out


def _has_noindex_signal(indexability: dict[str, Any]) -> tuple[bool, str]:
    meta = str(indexability.get("meta_robots_text") or "").lower()
    xr = str(indexability.get("x_robots_tag") or "").lower()
    if "noindex" in meta or "none" in meta:
        return True, "meta_robots"
    if "noindex" in xr or "none" in xr:
        return True, "x_robots_tag"
    reason = str(indexability.get("indexability_reason") or "").lower()
    if indexability.get("indexable") is False and ("noindex" in reason or "none" in reason):
        return True, "indexability_reason"
    return False, ""


def _canonical_differs_from_page(canonical_resolution: dict[str, Any], page_url: str) -> tuple[bool, str, str]:
    canonical = str(canonical_resolution.get("canonical_url") or "").strip()
    final = str(canonical_resolution.get("final_effective_url") or page_url).strip()
    if not canonical:
        return False, "", ""
    if _norm_url_key(canonical) == _norm_url_key(final):
        return False, "", ""
    return True, canonical, final


def _scheme_mismatch(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    if (pa.hostname or "").lower().replace("www.", "") != (pb.hostname or "").lower().replace("www.", ""):
        return False
    if pa.path.rstrip("/") != pb.path.rstrip("/"):
        return False
    return pa.scheme.lower() != pb.scheme.lower()


def _trailing_slash_mismatch(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    if pa.scheme.lower() != pb.scheme.lower():
        return False
    if (pa.hostname or "").lower() != (pb.hostname or "").lower():
        return False
    return pa.path.rstrip("/") == pb.path.rstrip("/") and pa.path != pb.path


def build_sitemap_indexability_issues(
    *,
    sitemap: dict[str, Any],
    pages: list[dict[str, Any]],
    robots: dict[str, Any],
    check_url_status: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Cross-check sitemap URLs vs crawl indexability, canonical, robots block.
    Returns raw issue dicts ready for _tech_issue() wrapping in analyzer.
    """
    sitemap_urls = [str(u).strip() for u in (sitemap.get("urls") or []) if str(u).strip()]
    if not sitemap_urls:
        return []

    pages_by_url = {str(p.get("url") or ""): p for p in pages if p.get("url")}
    lookup = _pages_lookup(pages_by_url)
    robots_body = str(robots.get("body_preview") or "")
    robots_status = int(robots.get("status") or 0)

    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _emit(issue_type: str, url: str, payload: dict[str, Any]) -> None:
        key = f"{issue_type}|{_norm_url_key(url)}"
        if key in seen:
            return
        seen.add(key)
        issues.append({"type": issue_type, "url": url, **payload})

    checked = 0
    for loc in sitemap_urls:
        if checked >= MAX_SITEMAP_CROSS_CHECKS:
            break
        checked += 1
        variants = _url_variants(loc)
        page = next((lookup[v] for v in variants if v in lookup), None)

        if page:
            idx = dict(page.get("indexability") or {})
            noindex, signal = _has_noindex_signal(idx)
            if noindex:
                evidence = [
                    {"kind": "sitemap_loc", "url": loc},
                    {"kind": "indexability_signal", "value": signal},
                ]
                if idx.get("meta_robots_text"):
                    evidence.append({"kind": "meta_robots", "value": idx["meta_robots_text"]})
                if idx.get("x_robots_tag"):
                    evidence.append({"kind": "x_robots_tag", "value": idx["x_robots_tag"]})
                _emit(
                    "sitemap_contains_noindex",
                    loc,
                    {
                        "severity": "high",
                        "message": f"Sitemap chứa URL noindex — tín hiệu mâu thuẫn: {loc}",
                        "confidence": 0.92,
                        "evidence": evidence,
                        "source": "sitemap",
                        "detected_from": ["sitemap.loc", f"indexability.{signal}"],
                        "checklist_group": "Sitemap",
                    },
                )

            cr = dict(page.get("canonical_resolution") or {})
            differs, canonical, final = _canonical_differs_from_page(cr, loc)
            if differs:
                evidence = [
                    {"kind": "sitemap_loc", "url": loc},
                    {"kind": "canonical_url", "url": canonical},
                    {"kind": "final_effective_url", "url": final},
                ]
                issue_type = "sitemap_contains_canonicalized_url"
                if _scheme_mismatch(canonical, final):
                    issue_type = "sitemap_contains_canonical_scheme_mismatch"
                elif _trailing_slash_mismatch(canonical, final):
                    issue_type = "sitemap_contains_canonical_slash_mismatch"
                _emit(
                    issue_type,
                    loc,
                    {
                        "severity": "medium",
                        "message": (
                            f"Sitemap liệt kê URL nhưng canonical trỏ sang URL khác: {loc} → {canonical}"
                        ),
                        "confidence": 0.88,
                        "evidence": evidence,
                        "source": "sitemap",
                        "detected_from": ["sitemap.loc", "canonical_resolution.canonical_url"],
                        "checklist_group": "Sitemap",
                    },
                )

        blocked = robots_url_blocked(loc, robots_body, robots_status=robots_status)
        if blocked is True:
            evidence = [
                {"kind": "sitemap_loc", "url": loc},
                {"kind": "robots_blocked", "value": True},
                {"kind": "robots_txt", "url": robots.get("url")},
            ]
            _emit(
                "sitemap_contains_robots_blocked",
                loc,
                {
                    "severity": "high",
                    "message": f"URL trong sitemap bị robots.txt chặn (Disallow): {loc}",
                    "confidence": 0.9,
                    "evidence": evidence,
                    "source": "robots",
                    "detected_from": ["sitemap.loc", "robots.txt Disallow"],
                    "checklist_group": "Sitemap",
                },
            )

    # Probe sitemap URLs chưa crawl — phát hiện 3xx/4xx/5xx trong sitemap
    not_crawled = [u for u in sitemap_urls if not any(v in lookup for v in _url_variants(u))]
    probed = 0
    for loc in not_crawled:
        if probed >= MAX_SITEMAP_STATUS_PROBES:
            break
        probed += 1
        result = check_url_status(loc)
        status = int(result.get("status") or 0)
        if status == 200:
            continue
        if status == 0 and not result.get("error_kind"):
            continue
        kind = result.get("error_kind") or classify_http_status(status) or "client_error"
        evidence = [
            {"kind": "sitemap_loc", "url": loc},
            {"kind": "http_status", "value": status},
            {"kind": "error_kind", "value": kind},
        ]
        if result.get("chain"):
            evidence.append({"kind": "redirect_chain", "value": result["chain"][:5]})
        sev = "high" if kind in ("server_error", "client_error", "forbidden") or status >= 400 else "medium"
        _emit(
            "sitemap_url_bad_status",
            loc,
            {
                "severity": sev,
                "message": f"Sitemap chứa URL trả HTTP {status} ({kind}): {loc}",
                "confidence": 0.86 if status else 0.72,
                "evidence": evidence,
                "source": "sitemap",
                "detected_from": ["sitemap.loc", "http_status"],
                "checklist_group": "Sitemap",
                "error_kind": kind,
            },
        )

    return issues


def internal_link_issue_type(result: dict[str, Any]) -> tuple[str, str]:
    """Map link check result → (issue_type, severity)."""
    status = int(result.get("status") or 0)
    kind = str(result.get("error_kind") or "")
    # 404/410 — luôn broken_internal_link, không gộp vào DNS/SSL/timeout/403/5xx
    if status in (404, 410):
        return "broken_internal_link", "high"
    mapping: dict[str, tuple[str, str]] = {
        "dns_error": ("internal_link_dns_error", "high"),
        "ssl_error": ("internal_link_ssl_error", "high"),
        "timeout": ("internal_link_timeout", "high"),
        "connection_error": ("internal_link_connection_error", "medium"),
        "forbidden": ("internal_link_forbidden", "high"),
        "unauthorized": ("internal_link_forbidden", "high"),
        "server_error": ("internal_link_server_error", "high"),
        "request_failed": ("internal_link_connection_error", "medium"),
    }
    if kind in mapping:
        return mapping[kind]
    if status >= 500:
        return "internal_link_server_error", "high"
    if status == 403:
        return "internal_link_forbidden", "high"
    if status >= 400:
        return "broken_internal_http_error", "high"
    return "broken_internal_http_error", "high"


def internal_link_issue_message(result: dict[str, Any]) -> str:
    """Human-readable message — phân biệt rõ 404/410 vs lỗi kết nối."""
    u = str(result.get("url") or "")
    status = int(result.get("status") or 0)
    kind = str(result.get("error_kind") or "")
    if status == 404:
        return f"Liên kết nội bộ trả 404 Not Found: {u}"
    if status == 410:
        return f"Liên kết nội bộ trả 410 Gone: {u}"
    if kind == "dns_error":
        return f"Liên kết nội bộ — lỗi DNS (không resolve host): {u}"
    if kind == "ssl_error":
        return f"Liên kết nội bộ — lỗi SSL/TLS: {u}"
    if kind == "timeout":
        return f"Liên kết nội bộ — timeout: {u}"
    if kind in ("forbidden", "unauthorized") or status == 403:
        return f"Liên kết nội bộ — HTTP 403 Forbidden/blocked: {u}"
    if kind == "server_error" or status >= 500:
        return f"Liên kết nội bộ — lỗi server HTTP {status}: {u}"
    if status >= 400:
        return f"Liên kết nội bộ lỗi HTTP {status}: {u}"
    if kind:
        return f"Liên kết nội bộ lỗi ({kind}): {u}"
    return f"Liên kết nội bộ không truy cập được: {u}"


def sitemap_missing_issue_type(sitemap: dict[str, Any]) -> tuple[str, str]:
    """sitemap_not_found (404) hoặc sitemap_unreachable (các lỗi khác)."""
    last_err = sitemap.get("last_error") or {}
    http_st = int(last_err.get("http_status") or 0)
    if http_st == 404:
        return (
            "sitemap_not_found",
            "Không tìm thấy sitemap.xml / sitemap_index (HTTP 404 — Sitemap / Technical-SEO.txt).",
        )
    return (
        "sitemap_unreachable",
        "sitemap.xml / sitemap_index không tồn tại hoặc không truy cập được (Sitemap / Technical-SEO.txt).",
    )


def robots_fetch_issue_type(robots: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (issue_type, severity, message_suffix) for robots.txt fetch failures."""
    status = int(robots.get("status") or 0)
    if status == 200:
        return None
    kind = str(robots.get("error_kind") or "")
    if kind == "dns_error":
        return "robots_dns_error", "high", "lỗi DNS"
    if kind == "ssl_error":
        return "robots_ssl_error", "high", "lỗi SSL/TLS"
    if kind == "timeout":
        return "robots_timeout", "high", "timeout"
    if status == 403:
        return "robots_forbidden", "high", "HTTP 403 Forbidden"
    if status >= 500:
        return "robots_server_error", "high", f"HTTP {status}"
    return "robots_unreachable", "high", "không truy cập được"
