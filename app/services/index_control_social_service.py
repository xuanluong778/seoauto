"""Index Control — Social / Entity URL checks (entity SEO, not full technical SEO)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from app.services.crawler import LINK_CHECK_HEADERS, normalize_url, parse_robots_txt
from app.services.index_control_service import normalize_domain
from app.services.indexability import _header_ci
from app.services.url_safety import assert_public_http_url

FETCH_TIMEOUT_SECONDS = 10.0
MAX_URLS_PER_REQUEST = 50
URL_TYPE_SOCIAL = "social_entity"

ENTITY_DISCLAIMER = (
    "Kiểm tra khả năng crawl và trạng thái entity công khai — "
    "không cam kết URL social sẽ được Google index."
)

_LOGIN_WALL_RE = re.compile(
    r"(sign[\s-]?in|log[\s-]?in|login required|đăng nhập|join linkedin|"
    r"you must log in|log into facebook|log in to facebook|create an account|"
    r"content isn['\u2019]t available|this content isn['\u2019]t available|"
    r"page isn['\u2019]t available|sorry, this page|private profile|"
    r"account suspended|login to continue|members only|see more on facebook|"
    r"view profile on linkedin|sign up for linkedin)",
    re.I,
)

_OG_META_RE = re.compile(
    r'<meta\s+(?:property|name)=["\'](?:og:|twitter:)[^"\']+["\']\s+content=["\'][^"\']{3,}',
    re.I,
)

_SOCIAL_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("facebook.com", "Facebook"),
    ("fb.com", "Facebook"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("linkedin.com", "LinkedIn"),
    ("pinterest.com", "Pinterest"),
    ("pin.it", "Pinterest"),
    ("medium.com", "Medium"),
    ("instagram.com", "Instagram"),
    ("twitter.com", "X (Twitter)"),
    ("x.com", "X (Twitter)"),
    ("tiktok.com", "TikTok"),
    ("threads.net", "Threads"),
)


@dataclass
class _SocialCache:
    robots: dict[str, dict[str, Any]] = field(default_factory=dict)
    parsers: dict[str, RobotFileParser] = field(default_factory=dict)


def _tri(value: str) -> str:
    return value if value in ("pass", "warning", "fail") else "warning"


def detect_social_platform(hostname: str) -> str | None:
    host = (hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for suffix, label in _SOCIAL_PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return label
    return None


def validate_social_url(url: str) -> tuple[str | None, str | None]:
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
    return f"https://{host}" if host else ""


def _load_platform_robots(url: str, hostname: str, cache: _SocialCache) -> bool | None:
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
        return None
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return None


def _detect_login_wall(html: str, status_code: int) -> bool:
    if status_code in (401, 403):
        return True
    text = (html or "")[:12000]
    if not text:
        return status_code == 200
    title_m = re.search(r"<title[^>]*>([^<]{0,240})</title>", text, re.I)
    if title_m and _LOGIN_WALL_RE.search(title_m.group(1)):
        return True
    if len(text) < 600 and _LOGIN_WALL_RE.search(text):
        return True
    if _LOGIN_WALL_RE.search(text[:2500]) and not _OG_META_RE.search(text):
        return True
    return False


def _has_public_signals(html: str) -> bool:
    text = html or ""
    if len(text) > 1500:
        return True
    return bool(_OG_META_RE.search(text))


def _entity_labels(entity_status: str) -> tuple[str, str]:
    if entity_status == "good":
        return "Tốt", "ok"
    if entity_status == "warning":
        return "Cảnh báo", "warn"
    return "Lỗi", "err"


def _build_entity_suggestion(
    *,
    entity_status: str,
    login_wall: bool,
    status_code: int,
    crawl_allowed: bool | None,
    platform: str | None,
    fetch_error: bool,
) -> str:
    tips: list[str] = []
    if fetch_error or status_code >= 400:
        tips.append("Kiểm tra URL entity còn tồn tại và đúng định dạng public.")
    if login_wall or status_code in (401, 403):
        tips.append("Đảm bảo profile ở chế độ public — tránh yêu cầu đăng nhập để xem.")
    if crawl_allowed is False:
        tips.append("Nền tảng có thể hạn chế crawl bot — tập trung vào liên kết thương hiệu và sameAs.")
    tips.append("Đồng bộ tên thương hiệu, mô tả, logo và website trên profile.")
    tips.append("Thêm link website chính vào profile entity.")
    tips.append("Thêm social URL vào schema sameAs trên website.")
    tips.append("Tạo trang giới thiệu thương hiệu trên site chính có liên kết tới profile.")
    tips.append("Kiểm tra lại sau khi cập nhật profile.")
    if platform:
        tips.insert(0, f"Nền tảng: {platform}.")
    if entity_status == "good":
        tips.insert(1 if platform else 0, "Entity công khai ổn — duy trì thông tin nhất quán.")
    return " ".join(tips[:6]) + " " + ENTITY_DISCLAIMER


def _build_entity_conclusion(
    *,
    status_code: int,
    login_wall: bool,
    crawl_allowed: bool | None,
    fetch_error: bool,
    has_public_signals: bool,
) -> tuple[str, str, str, str]:
    """Return entity_status, main_issue, indexability, severity."""
    if fetch_error or status_code == 0:
        return "error", "URL không truy cập được", "error", "high"
    if status_code in (404, 410):
        return "error", "URL không tồn tại", "blocked", "high"
    if status_code >= 500:
        return "error", "HTTP error", "error", "critical"
    if status_code in (401, 403) or login_wall:
        return "warning", "Login wall / private", "warning", "medium"
    if crawl_allowed is False:
        return "warning", "Crawl limited", "warning", "medium"
    if status_code != 200 and 300 <= status_code < 400:
        return "warning", "Redirect", "warning", "low"
    if status_code != 200:
        return "warning", f"HTTP {status_code}", "warning", "medium"
    if not has_public_signals:
        return "warning", "Limited public signals", "warning", "low"
    return "good", "Public entity", "indexable", "low"


def check_social_url(url: str, *, cache: _SocialCache) -> dict[str, Any]:
    normalized, err = validate_social_url(url)
    if err or not normalized:
        return _error_social_item(url, message=err or "URL không hợp lệ.")

    parsed = urlparse(normalized)
    hostname = parsed.hostname or ""
    platform = detect_social_platform(hostname)

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
        return _error_social_item(normalized, message="Timeout — không truy cập được URL entity.")
    except requests.exceptions.RequestException:
        return _error_social_item(normalized, message="Lỗi kết nối — kiểm tra URL hoặc thử lại.")
    except Exception:
        return _error_social_item(normalized, message="Lỗi không xác định khi fetch URL.")

    final_host = urlparse(final_url).hostname or hostname
    login_wall = _detect_login_wall(html, status_code)
    crawl_allowed = _load_platform_robots(final_url, final_host, cache)
    has_public = _has_public_signals(html)
    xr = _header_ci(headers, "x-robots-tag")
    xrobots_block = bool(xr and re.search(r"noindex|none|noarchive", xr, re.I))

    entity_status, main_issue, indexability, severity = _build_entity_conclusion(
        status_code=status_code,
        login_wall=login_wall,
        crawl_allowed=crawl_allowed,
        fetch_error=fetch_error,
        has_public_signals=has_public,
    )
    if xrobots_block and entity_status == "good":
        entity_status, main_issue, indexability, severity = (
            "warning",
            "Crawl signals limited",
            "warning",
            "low",
        )

    entity_label, status_class = _entity_labels(entity_status)

    alive_tri = "pass" if status_code == 200 and not fetch_error else (
        "warning" if 300 <= status_code < 400 else "fail"
    )
    if status_code >= 400 or fetch_error:
        alive_tri = "fail"

    if login_wall or status_code in (401, 403):
        crawl_tri = "fail"
    elif crawl_allowed is False:
        crawl_tri = "warning"
    elif crawl_allowed is None:
        crawl_tri = "warning"
    elif status_code == 200 and has_public:
        crawl_tri = "pass"
    else:
        crawl_tri = "warning"

    login_tri = "fail" if login_wall else "pass"
    basic_tri = crawl_tri if entity_status != "error" else "fail"

    suggestion = _build_entity_suggestion(
        entity_status=entity_status,
        login_wall=login_wall,
        status_code=status_code,
        crawl_allowed=crawl_allowed,
        platform=platform,
        fetch_error=fetch_error,
    )

    return {
        "url": normalized,
        "final_url": final_url,
        "url_type": URL_TYPE_SOCIAL,
        "platform": platform,
        "status_code": status_code,
        "status": entity_label,
        "status_class": status_class,
        "entity_status": entity_status,
        "entity_status_label": entity_label,
        "indexability": indexability,
        "main_issue": main_issue,
        "primary_error": main_issue if main_issue not in ("Public entity",) else "—",
        "severity": severity,
        "checks": {
            "alive": _tri(alive_tri),
            "crawl": _tri(crawl_tri),
            "login_wall": _tri(login_tri),
            "basic_status": _tri(basic_tri),
        },
        "hint": suggestion,
        "suggestion": suggestion,
        "disclaimer": ENTITY_DISCLAIMER,
        "alive": alive_tri == "pass",
        "publicly_crawlable": crawl_tri == "pass",
        "login_wall": login_wall,
        "redirected": redirected,
        "redirect_chain": chain if redirected else [],
        "x_robots_tag": xr or None,
        "robots_crawl_allowed": crawl_allowed,
    }


def _error_social_item(url: str, *, message: str) -> dict[str, Any]:
    suggestion = _build_entity_suggestion(
        entity_status="error",
        login_wall=False,
        status_code=0,
        crawl_allowed=None,
        platform=None,
        fetch_error=True,
    )
    return {
        "url": url,
        "final_url": url,
        "url_type": URL_TYPE_SOCIAL,
        "status_code": 0,
        "status": "Lỗi",
        "status_class": "err",
        "entity_status": "error",
        "entity_status_label": "Lỗi",
        "indexability": "error",
        "main_issue": "URL không truy cập được",
        "primary_error": message,
        "severity": "high",
        "checks": {
            "alive": "fail",
            "crawl": "fail",
            "login_wall": "warning",
            "basic_status": "fail",
        },
        "hint": suggestion,
        "suggestion": suggestion,
        "disclaimer": ENTITY_DISCLAIMER,
        "alive": False,
        "publicly_crawlable": False,
        "login_wall": False,
    }


def check_social_urls(*, urls: list[str]) -> dict[str, Any]:
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

    cache = _SocialCache()
    items: list[dict[str, Any]] = []
    for raw in clean:
        try:
            items.append(check_social_url(raw, cache=cache))
        except Exception:
            items.append(_error_social_item(raw, message="Lỗi xử lý URL — thử lại sau."))

    first_host = ""
    if items:
        try:
            first_host = normalize_domain(urlparse(items[0].get("url") or "").hostname or "")
        except Exception:
            pass

    return {
        "ok": True,
        "url_type": URL_TYPE_SOCIAL,
        "domain": first_host or None,
        "count": len(items),
        "items": items,
        "demo": False,
        "disclaimer": ENTITY_DISCLAIMER,
    }
