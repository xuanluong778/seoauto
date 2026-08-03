"""Index Control — real Web 2.0 URL checks (Medium, Blogger, WordPress.com, Tumblr, …)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.services.canonical_utils import resolve_canonical_signals
from app.services.crawler import LINK_CHECK_HEADERS, normalize_url, parse_robots_txt
from app.services.index_control_service import normalize_domain
from app.services.indexability import _has_noindex_none, _header_ci, _meta_robots_directives
from app.services.url_safety import assert_public_http_url

FETCH_TIMEOUT_SECONDS = 10.0
MAX_URLS_PER_REQUEST = 50
URL_TYPE_WEB20 = "web20"

_LOGIN_WALL_RE = re.compile(
    r"(sign[\s-]?in|log[\s-]?in|login required|đăng nhập|private post|draft|"
    r"members only|subscribe to read|this page is unavailable)",
    re.I,
)

_KNOWN_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("medium.com", "Medium"),
    ("wordpress.com", "WordPress.com"),
    ("blogspot.com", "Blogger"),
    ("tumblr.com", "Tumblr"),
    ("wixsite.com", "Wix"),
    ("substack.com", "Substack"),
    ("ghost.io", "Ghost"),
    ("sites.google.com", "Google Sites"),
)


@dataclass
class _PlatformCache:
    robots: dict[str, dict[str, Any]] = field(default_factory=dict)
    parsers: dict[str, RobotFileParser] = field(default_factory=dict)


def _tri(value: str) -> str:
    return value if value in ("pass", "warning", "fail") else "warning"


def _http_tri(code: int) -> str:
    if code == 200:
        return "pass"
    if 300 <= code < 400:
        return "warning"
    if code == 0:
        return "fail"
    return "fail"


def detect_platform(hostname: str) -> str | None:
    host = (hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for suffix, label in _KNOWN_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return label
    return None


def validate_web20_url(url: str) -> tuple[str | None, str | None]:
    raw = (url or "").strip()
    if not raw:
        return None, "URL trống."
    try:
        safe = assert_public_http_url(raw, label="URL")
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        return None, str(detail)
    try:
        return normalize_url(safe), None
    except ValueError:
        return None, "URL không hợp lệ."


def _platform_origin(hostname: str) -> str:
    host = (hostname or "").lower().split(":")[0]
    if not host:
        return ""
    return f"https://{host}"


def _load_platform_robots(url: str, hostname: str, cache: _PlatformCache) -> tuple[bool | None, str]:
    """Return (blocked, check_tri). blocked=None when unknown."""
    if hostname in cache.robots:
        parsed = cache.robots[hostname]
        rp = cache.parsers.get(hostname)
    else:
        origin = _platform_origin(hostname)
        parsed = parse_robots_txt(origin)
        cache.robots[hostname] = parsed
        rp = RobotFileParser()
        body = parsed.get("body_preview") or ""
        if parsed.get("status") == 200 and body:
            rp.parse(body.splitlines())
        else:
            rp.parse([])
        cache.parsers[hostname] = rp

    if parsed.get("status") != 200:
        return None, "warning"
    try:
        allowed = rp.can_fetch("*", url)
    except Exception:
        return None, "warning"
    if not allowed:
        return True, "fail"
    return False, "pass"


def _looks_like_login_wall(html: str, status_code: int) -> bool:
    if status_code != 200:
        return False
    text = (html or "")[:8000]
    if len(text) < 400 and _LOGIN_WALL_RE.search(text):
        return True
    title_m = re.search(r"<title[^>]*>([^<]{0,200})</title>", text, re.I)
    if title_m and _LOGIN_WALL_RE.search(title_m.group(1)):
        return True
    return False


def _alive_label(status_code: int, fetch_error: bool) -> tuple[str, str, str]:
    """Return (status_label, status_class, alive_tri)."""
    if fetch_error or status_code == 0:
        return "Dead", "err", "fail"
    if status_code == 200:
        return "Live", "ok", "pass"
    if 300 <= status_code < 400:
        return "Redirect", "warn", "warning"
    if status_code >= 400:
        return "Dead", "err", "fail"
    return "Unknown", "warn", "warning"


def _build_web20_suggestion(
    *,
    status_code: int,
    meta_noindex: bool,
    xrobots_noindex: bool,
    canonical_mismatch: bool,
    login_wall: bool,
    robots_blocked: bool | None,
    fetch_error: bool,
    platform: str | None,
) -> str:
    tips: list[str] = []
    if fetch_error or status_code >= 400:
        tips.append("Kiểm tra bài viết đã public chưa và URL còn tồn tại.")
    if login_wall or status_code == 403:
        tips.append("Kiểm tra quyền riêng tư của bài viết — đặt public hoặc unlisted nếu cần index.")
    if meta_noindex or xrobots_noindex:
        tips.append("Nền tảng hoặc cài đặt bài viết đang chặn index — bật cho phép index nếu có tùy chọn.")
    if canonical_mismatch:
        tips.append("Canonical trỏ URL khác — xác nhận URL bạn muốn Google ưu tiên.")
    if robots_blocked:
        tips.append("robots.txt nền tảng hạn chế crawl — thử custom domain nếu có.")
    tips.append("Thêm liên kết từ website chính hoặc profile về URL này.")
    tips.append("Kiểm tra lại sau 24–72 giờ.")
    if platform:
        tips.insert(0, f"Nền tảng: {platform}.")
    return " ".join(tips[:5])


def _build_web20_conclusion(
    *,
    status_code: int,
    meta_noindex: bool,
    xrobots_noindex: bool,
    canonical_mismatch: bool,
    login_wall: bool,
    robots_blocked: bool | None,
    fetch_error: bool,
) -> tuple[str, str, str]:
    if fetch_error or status_code == 0:
        return "error", "HTTP error", "critical"
    if status_code >= 400:
        return "blocked", "HTTP error", "high" if status_code < 500 else "critical"
    if meta_noindex or xrobots_noindex:
        return "blocked", "Meta noindex", "high"
    if login_wall:
        return "warning", "Login or private", "medium"
    if canonical_mismatch:
        return "warning", "Canonical points elsewhere", "medium"
    if robots_blocked is True:
        return "warning", "Crawl limited", "medium"
    if status_code != 200:
        return "warning", "Redirect", "low"
    return "indexable", "No issue", "low"


def _status_from_indexability(indexability: str, alive_status: str) -> tuple[str, str]:
    if alive_status in ("Dead",):
        return alive_status, "err"
    if indexability == "indexable":
        return "Live", "ok"
    if indexability == "warning":
        return "Limited", "warn"
    if indexability == "blocked":
        return "Blocked", "err"
    return "Dead", "err"


def check_web20_url(url: str, *, cache: _PlatformCache) -> dict[str, Any]:
    normalized, err = validate_web20_url(url)
    if err or not normalized:
        return {
            "url": (url or "").strip(),
            "final_url": (url or "").strip(),
            "url_type": URL_TYPE_WEB20,
            "status_code": 0,
            "status": "Dead",
            "status_class": "err",
            "indexability": "error",
            "main_issue": "HTTP error",
            "primary_error": err or "URL không hợp lệ.",
            "severity": "high",
            "checks": {
                "http": "fail",
                "noindex": "pass",
                "canonical": "warning",
                "crawl": "fail",
                "http_status": "fail",
                "meta_noindex": "pass",
                "alive": "fail",
            },
            "hint": err or "URL không hợp lệ.",
            "suggestion": err or "URL không hợp lệ.",
            "action": "Doctor",
            "alive": False,
        }

    parsed = urlparse(normalized)
    hostname = parsed.hostname or ""
    platform = detect_platform(hostname)

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
        fetch_error = False
    except requests.exceptions.Timeout:
        status_code, html, headers, final_url, chain, redirected = 0, "", {}, normalized, [], False
        fetch_error = True
    except requests.exceptions.RequestException:
        status_code, html, headers, final_url, chain, redirected = 0, "", {}, normalized, [], False
        fetch_error = True
    except Exception:
        status_code, html, headers, final_url, chain, redirected = 0, "", {}, normalized, [], False
        fetch_error = True

    final_host = urlparse(final_url).hostname or hostname
    meta_txt = _meta_robots_directives(html) if html else ""
    meta_noindex = _has_noindex_none(meta_txt) if html else False
    xr = _header_ci(headers, "x-robots-tag")
    xrobots_noindex = _has_noindex_none(xr)

    canon = resolve_canonical_signals(html, final_url) if html else {"canonical_url": None, "canonical_mismatch": False}
    canonical_url = canon.get("canonical_url")
    canonical_mismatch = bool(canon.get("canonical_mismatch"))
    canonical_missing = not canonical_url

    robots_blocked, robots_tri = _load_platform_robots(final_url, final_host, cache)
    login_wall = _looks_like_login_wall(html, status_code)

    http_tri = _http_tri(status_code)
    noindex_tri = "fail" if (meta_noindex or xrobots_noindex) else ("warning" if not html else "pass")
    if canonical_mismatch:
        canon_tri = "fail"
    elif canonical_missing:
        canon_tri = "warning"
    else:
        canon_tri = "pass"

    if fetch_error or status_code >= 400:
        crawl_tri = "fail"
    elif robots_blocked is True:
        crawl_tri = "fail"
    elif login_wall:
        crawl_tri = "warning"
    elif robots_blocked is None and not html:
        crawl_tri = "warning"
    else:
        crawl_tri = "pass"

    alive_label, alive_class, alive_tri = _alive_label(status_code, fetch_error)
    indexability, main_issue, severity = _build_web20_conclusion(
        status_code=status_code,
        meta_noindex=meta_noindex,
        xrobots_noindex=xrobots_noindex,
        canonical_mismatch=canonical_mismatch,
        login_wall=login_wall,
        robots_blocked=robots_blocked,
        fetch_error=fetch_error,
    )
    status_label, status_class = _status_from_indexability(indexability, alive_label)
    suggestion = _build_web20_suggestion(
        status_code=status_code,
        meta_noindex=meta_noindex,
        xrobots_noindex=xrobots_noindex,
        canonical_mismatch=canonical_mismatch,
        login_wall=login_wall,
        robots_blocked=robots_blocked,
        fetch_error=fetch_error,
        platform=platform,
    )

    action = "Doctor" if indexability != "indexable" else "Xem GSC"

    return {
        "url": normalized,
        "final_url": final_url,
        "url_type": URL_TYPE_WEB20,
        "platform": platform,
        "status_code": status_code,
        "status": status_label,
        "status_class": status_class,
        "indexability": indexability,
        "main_issue": main_issue,
        "primary_error": main_issue if main_issue != "No issue" else "—",
        "severity": severity,
        "checks": {
            "http": _tri(http_tri),
            "noindex": _tri(noindex_tri),
            "canonical": _tri(canon_tri),
            "crawl": _tri(crawl_tri),
            "http_status": _tri(http_tri),
            "meta_noindex": _tri(noindex_tri),
            "alive": _tri(alive_tri),
        },
        "hint": suggestion,
        "suggestion": suggestion,
        "action": action,
        "alive": alive_tri == "pass",
        "meta_robots": meta_txt or None,
        "x_robots_tag": xr or None,
        "canonical_url": canonical_url,
        "redirected": redirected,
        "redirect_chain": chain if redirected else [],
        "robots_blocked": robots_blocked,
        "login_wall": login_wall,
    }


def _error_web20_item(url: str, *, message: str) -> dict[str, Any]:
    return {
        "url": url,
        "final_url": url,
        "url_type": URL_TYPE_WEB20,
        "status_code": 0,
        "status": "Dead",
        "status_class": "err",
        "indexability": "error",
        "main_issue": "HTTP error",
        "primary_error": message,
        "severity": "critical",
        "checks": {
            "http": "fail",
            "noindex": "pass",
            "canonical": "warning",
            "crawl": "fail",
            "http_status": "fail",
            "meta_noindex": "pass",
            "alive": "fail",
        },
        "hint": message,
        "suggestion": message,
        "action": "Doctor",
        "alive": False,
    }


def check_web20_urls(*, urls: list[str]) -> dict[str, Any]:
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

    cache = _PlatformCache()
    items: list[dict[str, Any]] = []
    for raw in clean:
        try:
            items.append(check_web20_url(raw, cache=cache))
        except Exception:
            items.append(_error_web20_item(raw, message="Lỗi xử lý URL — thử lại sau."))

    first_host = ""
    if items:
        try:
            first_host = normalize_domain(urlparse(items[0].get("url") or "").hostname or "")
        except Exception:
            pass

    return {
        "ok": True,
        "url_type": URL_TYPE_WEB20,
        "domain": first_host or None,
        "count": len(items),
        "items": items,
        "demo": False,
    }
