"""Index Control — real website URL indexability checks."""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.services.canonical_utils import resolve_canonical_signals
from app.services.crawler import LINK_CHECK_HEADERS, normalize_url, parse_robots_txt, parse_sitemap_xml
from app.services.indexability import _has_noindex_none, _header_ci, _meta_robots_directives
from app.services.url_safety import assert_public_http_url

FETCH_TIMEOUT_SECONDS = 8.0
MAX_URLS_PER_REQUEST = 50
URL_TYPE_WEBSITE = "website"

_MAIN_ISSUES = (
    "No issue",
    "Meta noindex",
    "X-Robots noindex",
    "Blocked by robots.txt",
    "Canonical points elsewhere",
    "Not found in sitemap",
    "HTTP error",
)


@dataclass
class _DomainCache:
    robots: dict[str, Any] | None = None
    robot_parser: RobotFileParser | None = None
    sitemap_urls: set[str] | None = None
    sitemap_readable: bool = False


def normalize_domain(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = (urlparse(value).hostname or "").lower()
    value = value.split(":")[0].strip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def _host_matches_domain(hostname: str, domain: str) -> bool:
    host = (hostname or "").lower().split(":")[0]
    dom = normalize_domain(domain)
    if not host or not dom:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host == dom or host.endswith("." + dom)


def validate_check_url(url: str, *, domain: str) -> tuple[str | None, str | None]:
    """Return (normalized_url, error_message)."""
    raw = (url or "").strip()
    if not raw:
        return None, "URL trống."
    try:
        safe = assert_public_http_url(raw, label="URL")
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return None, str(detail)

    try:
        normalized = normalize_url(safe)
    except ValueError:
        return None, "URL không hợp lệ."

    parsed = urlparse(normalized)
    if not _host_matches_domain(parsed.hostname or "", domain):
        return None, f"URL không thuộc domain {domain}."

    return normalized, None


def _check_status_tri(value: str) -> str:
    return value if value in ("pass", "warning", "fail") else "warning"


def _empty_checks(*, http: str = "warning") -> dict[str, str]:
    return {
        "http_status": _check_status_tri(http),
        "meta_noindex": "pass",
        "x_robots_noindex": "pass",
        "canonical": "warning",
        "robots_txt": "warning",
        "sitemap": "warning",
    }


def _error_item(
    url: str,
    *,
    main_issue: str,
    suggestion: str,
    severity: str = "critical",
    status_code: int = 0,
    checks: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "final_url": url,
        "url_type": URL_TYPE_WEBSITE,
        "status_code": status_code,
        "indexability": "error",
        "main_issue": main_issue,
        "severity": severity,
        "checks": checks or _empty_checks(http="fail"),
        "suggestion": suggestion,
    }


def _origin(domain: str) -> str:
    dom = normalize_domain(domain)
    return f"https://{dom}" if dom else ""


def _load_robots(domain: str, cache: _DomainCache) -> None:
    if cache.robots is not None:
        return
    origin = _origin(domain)
    parsed = parse_robots_txt(origin)
    cache.robots = parsed
    cache.robot_parser = RobotFileParser()
    body = parsed.get("body_preview") or ""
    if parsed.get("status") == 200 and body:
        cache.robot_parser.parse(body.splitlines())
    else:
        cache.robot_parser.parse([])


def _robots_blocks(url: str, domain: str, cache: _DomainCache) -> tuple[bool | None, str]:
    """Return (blocked, check_status). blocked=None when unknown."""
    _load_robots(domain, cache)
    rp = cache.robot_parser
    if not rp or cache.robots.get("status") != 200:
        return None, "warning"
    try:
        allowed = rp.can_fetch("*", url)
    except Exception:
        return None, "warning"
    return (not allowed), ("fail" if not allowed else "pass")


def _load_sitemap_urls(domain: str, cache: _DomainCache) -> None:
    if cache.sitemap_urls is not None:
        return
    origin = _origin(domain)
    _load_robots(domain, cache)
    sitemaps = list(cache.robots.get("sitemaps") or []) if cache.robots else []
    parsed = parse_sitemap_xml(origin, sitemaps or None)
    urls: set[str] = set()
    if parsed.get("status") == 200:
        cache.sitemap_readable = True
        for loc in parsed.get("urls") or []:
            try:
                urls.add(normalize_url(str(loc).strip()))
            except ValueError:
                continue
    cache.sitemap_urls = urls


def _sitemap_check(url: str, domain: str, cache: _DomainCache) -> tuple[str, bool | None]:
    """Return (check_status, in_sitemap). in_sitemap None if unreadable."""
    _load_sitemap_urls(domain, cache)
    if not cache.sitemap_readable:
        return "warning", None
    assert cache.sitemap_urls is not None
    try:
        normalized = normalize_url(url)
    except ValueError:
        return "warning", None
    if normalized in cache.sitemap_urls:
        return "pass", True
    # Trailing slash variants
    alt = normalized.rstrip("/") if normalized.endswith("/") else normalized + "/"
    if alt in cache.sitemap_urls:
        return "pass", True
    return "warning", False


def _http_status_check(code: int) -> str:
    if code == 200:
        return "pass"
    if 300 <= code < 400:
        return "warning"
    return "fail"


def _build_conclusion(
    *,
    status_code: int,
    meta_noindex: bool,
    xrobots_noindex: bool,
    robots_blocked: bool | None,
    canonical_mismatch: bool,
    canonical_missing: bool,
    sitemap_in: bool | None,
    fetch_error: bool,
) -> tuple[str, str, str, str]:
    if fetch_error or status_code == 0:
        return (
            "error",
            "HTTP error",
            "critical",
            "Không truy cập được URL — kiểm tra DNS, SSL, firewall hoặc URL sai.",
        )
    if status_code >= 400:
        return (
            "blocked",
            "HTTP error",
            "high" if status_code < 500 else "critical",
            f"HTTP {status_code} — sửa lỗi phản hồi hoặc redirect trước khi yêu cầu index.",
        )
    if meta_noindex:
        return (
            "blocked",
            "Meta noindex",
            "high",
            "Gỡ thẻ meta robots noindex/none hoặc googlebot noindex trên trang production.",
        )
    if xrobots_noindex:
        return (
            "blocked",
            "X-Robots noindex",
            "high",
            "Gỡ header X-Robots-Tag: noindex hoặc none ở server/CDN.",
        )
    if robots_blocked is True:
        return (
            "blocked",
            "Blocked by robots.txt",
            "high",
            "Sửa robots.txt — bỏ Disallow chặn đường dẫn này cho User-agent *.",
        )
    if canonical_mismatch:
        return (
            "warning",
            "Canonical points elsewhere",
            "medium",
            "Canonical trỏ URL khác — Google có thể index URL canonical thay vì URL này.",
        )
    if sitemap_in is False:
        return (
            "warning",
            "Not found in sitemap",
            "medium",
            "Thêm URL vào sitemap.xml và gửi lại Search Console / IndexNow.",
        )
    if canonical_missing:
        return (
            "warning",
            "No issue",
            "low",
            "Trang có thể index — nên bổ sung thẻ canonical rõ ràng.",
        )
    if status_code != 200:
        return (
            "warning",
            "No issue",
            "low",
            f"HTTP {status_code} — theo dõi redirect chain và đảm bảo URL đích trả 200.",
        )
    return (
        "indexable",
        "No issue",
        "low",
        "URL đủ điều kiện index cơ bản — theo dõi coverage trên Google Search Console.",
    )


def check_website_url(url: str, *, domain: str, cache: _DomainCache) -> dict[str, Any]:
    normalized, err = validate_check_url(url, domain=domain)
    if err or not normalized:
        return _error_item(
            url.strip() or url,
            main_issue="HTTP error",
            suggestion=err or "URL không hợp lệ.",
            severity="high",
        )

    try:
        response = requests.get(
            normalized,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers=dict(LINK_CHECK_HEADERS),
            allow_redirects=True,
        )
        status_code = int(response.status_code)
        final_url = str(response.url or normalized)
        try:
            final_url = normalize_url(final_url)
        except ValueError:
            pass
        chain = [str(u) for u in ([resp.url for resp in response.history] + [response.url])]
        redirected = len(response.history) > 0 or normalized.rstrip("/") != final_url.rstrip("/")
        html = response.text or ""
        headers = {k: v for k, v in response.headers.items()}
    except requests.exceptions.Timeout:
        return _error_item(
            normalized,
            main_issue="HTTP error",
            suggestion="Timeout — host phản hồi chậm, thử lại hoặc kiểm tra server.",
            severity="high",
        )
    except requests.exceptions.RequestException:
        return _error_item(
            normalized,
            main_issue="HTTP error",
            suggestion="Lỗi kết nối — kiểm tra URL, SSL hoặc chặn bot/WAF.",
            severity="high",
        )
    except Exception:
        return _error_item(
            normalized,
            main_issue="HTTP error",
            suggestion="Lỗi không xác định khi fetch URL.",
            severity="critical",
        )

    meta_txt = _meta_robots_directives(html)
    meta_noindex = _has_noindex_none(meta_txt)
    xr = _header_ci(headers, "x-robots-tag")
    xrobots_noindex = _has_noindex_none(xr)

    canon = resolve_canonical_signals(html, final_url)
    canonical_url = canon.get("canonical_url")
    canonical_mismatch = bool(canon.get("canonical_mismatch"))
    canonical_missing = not canonical_url

    robots_blocked, robots_check = _robots_blocks(final_url, domain, cache)
    sitemap_check, sitemap_in = _sitemap_check(final_url, domain, cache)

    if canonical_missing:
        canonical_check = "warning"
    elif canonical_mismatch:
        canonical_check = "fail"
    else:
        canonical_check = "pass"

    indexability, main_issue, severity, suggestion = _build_conclusion(
        status_code=status_code,
        meta_noindex=meta_noindex,
        xrobots_noindex=xrobots_noindex,
        robots_blocked=robots_blocked,
        canonical_mismatch=canonical_mismatch,
        canonical_missing=canonical_missing,
        sitemap_in=sitemap_in,
        fetch_error=False,
    )

    title_m = re.search(r"<title[^>]*>([^<]{0,240})</title>", html, re.I)
    page_title = re.sub(r"\s+", " ", (title_m.group(1) if title_m else "")).strip()[:240]

    return {
        "url": normalized,
        "final_url": final_url,
        "url_type": URL_TYPE_WEBSITE,
        "status_code": status_code,
        "indexability": indexability,
        "main_issue": main_issue,
        "severity": severity,
        "page_title": page_title or None,
        "checks": {
            "http_status": _http_status_check(status_code),
            "meta_noindex": "fail" if meta_noindex else "pass",
            "x_robots_noindex": "fail" if xrobots_noindex else "pass",
            "canonical": _check_status_tri(canonical_check),
            "robots_txt": _check_status_tri(robots_check),
            "sitemap": _check_status_tri(sitemap_check),
        },
        "suggestion": suggestion,
        "meta_robots": meta_txt or None,
        "x_robots_tag": xr or None,
        "canonical_url": canonical_url,
        "redirected": redirected,
        "redirect_chain": chain if redirected else [],
        "robots_blocked": robots_blocked,
        "sitemap_in": sitemap_in,
    }


def check_website_urls(*, domain: str, urls: list[str]) -> dict[str, Any]:
    dom = normalize_domain(domain)
    if not dom:
        return {
            "ok": False,
            "error": "invalid_domain",
            "message": "Domain không hợp lệ.",
            "items": [],
        }

    clean = [u.strip() for u in urls if u and u.strip()]
    if not clean:
        return {
            "ok": False,
            "error": "empty_urls",
            "message": "Nhập ít nhất một URL.",
            "items": [],
        }

    if len(clean) > MAX_URLS_PER_REQUEST:
        clean = clean[:MAX_URLS_PER_REQUEST]

    origin = f"https://{dom}"
    cache = _DomainCache()
    items: list[dict[str, Any]] = []

    for raw in clean:
        try:
            items.append(check_website_url(raw, domain=dom, cache=cache))
        except Exception:
            items.append(
                _error_item(
                    raw,
                    main_issue="HTTP error",
                    suggestion="Lỗi xử lý URL — thử lại sau.",
                    severity="critical",
                )
            )

    return {
        "ok": True,
        "url_type": URL_TYPE_WEBSITE,
        "domain": dom,
        "count": len(items),
        "items": items,
        "demo": False,
    }
