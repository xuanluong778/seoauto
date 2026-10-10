"""
Link analyzer for SEO Score — accuracy-first, minimal false positives.

Only real <a href> navigational links; broken status requires HTTP evidence.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.services.crawler import LINK_CHECK_HEADERS
from app.services.url_safety import safe_requests_get

_SKIP_HREF_PREFIXES = ("javascript:", "mailto:", "tel:", "data:", "blob:", "about:")
_TOGGLE_CLASS_RE = (
    "toggle",
    "accordion",
    "collapse",
    "dropdown",
    "menu-toggle",
    "navbar-toggler",
    "hamburger",
    "btn-close",
    "close",
)
_LINK_PARTIAL_WARNING = "Chưa đủ dữ liệu để đánh giá link"


def _page_host_key(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _rel_tokens(rel_val: Any) -> set[str]:
    if rel_val is None:
        return set()
    if isinstance(rel_val, list):
        raw = " ".join(str(x) for x in rel_val)
    else:
        raw = str(rel_val)
    return {t.strip().lower() for t in raw.split() if t.strip()}


def _is_skippable_href(href_raw: str) -> bool:
    href = str(href_raw or "").strip()
    if not href:
        return True
    low = href.lower()
    if low.startswith(_SKIP_HREF_PREFIXES):
        return True
    if low == "#":
        return True
    base, frag = urldefrag(href)
    if not base.strip() and frag:
        return True
    return False


def _is_non_nav_control(anchor: Tag) -> bool:
    """Skip buttons, toggles, and JS-only controls mis-tagged as links."""
    if anchor.name != "a":
        return True
    role = str(anchor.get("role") or "").strip().lower()
    if role in ("button", "tab", "menuitem"):
        return True
    if anchor.get("aria-expanded") is not None or anchor.get("data-toggle") or anchor.get("data-bs-toggle"):
        return True
    classes = " ".join(str(c) for c in (anchor.get("class") or [])).lower()
    if any(tok in classes for tok in _TOGGLE_CLASS_RE):
        return True
    href = str(anchor.get("href") or "").strip().lower()
    if href in ("#", "javascript:void(0)", "javascript:;", "javascript:void(0);"):
        return True
    text = anchor.get_text(" ", strip=True)
    if len(text) <= 2 and text.lower() in ("x", "×", "+", "-", "›", "‹", "»", "«"):
        return True
    return False


def _normalize_href(href_raw: str, base_url: str) -> str:
    href = str(href_raw or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if base_url and not href.startswith(("http://", "https://")):
        try:
            href = urljoin(base_url, href)
        except Exception:
            pass
    href, _ = urldefrag(href)
    return href.strip()


def _http_status_for_url(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """HEAD-like probe via GET stream (safe_requests has no HEAD)."""
    out: dict[str, Any] = {"url": url, "checked": False, "status_code": None, "method": None, "error": None}
    try:
        resp = safe_requests_get(
            url,
            timeout=timeout,
            headers=dict(LINK_CHECK_HEADERS),
        )
        out["checked"] = True
        out["status_code"] = int(resp.status_code)
        out["method"] = "GET"
        return out
    except Exception as exc:
        out["error"] = exc.__class__.__name__
        return out


def _verify_broken_links(urls: list[str]) -> list[dict[str, Any]]:
    """HTTP evidence for broken links; deduped, capped."""
    max_checks = max(1, min(20, int(os.getenv("SEO_SCORE_LINK_HTTP_CHECK_MAX", "12"))))
    seen: set[str] = set()
    broken: list[dict[str, Any]] = []
    for raw in urls:
        u = str(raw or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        if len(broken) >= max_checks:
            break
        if not u.startswith(("http://", "https://")):
            continue
        probe = _http_status_for_url(u)
        code = probe.get("status_code")
        if probe.get("checked") and code is not None and int(code) >= 400:
            broken.append(
                {
                    "href": u[:500],
                    "http_status": int(code),
                    "method": probe.get("method"),
                    "reason": f"HTTP {code}",
                    "evidence": probe,
                }
            )
        elif probe.get("error"):
            broken.append(
                {
                    "href": u[:500],
                    "http_status": None,
                    "method": probe.get("method"),
                    "reason": f"Không truy cập được ({probe.get('error')})",
                    "evidence": probe,
                }
            )
    return broken


def analyze_page_links(
    html: str,
    base_url: str,
    *,
    soup: BeautifulSoup | None = None,
    parsed_links: list[dict[str, Any]] | None = None,
    verify_http: bool = True,
) -> dict[str, Any]:
    """Analyze navigational <a href> links only — no fragment/mailto false positives."""
    if not str(html or "").strip():
        out = _empty_link_profile()
        out["link_opportunities"] = ["Không có HTML — không thể đánh giá cấu trúc link."]
        return out

    try:
        if soup is None:
            soup = BeautifulSoup((html or "")[:400_000], "html.parser")
    except Exception:
        out = _empty_link_profile()
        out["link_opportunities"] = ["Không parse được HTML để đọc thẻ <a>."]
        return out

    host = _page_host_key(base_url or "")
    rows: list[dict[str, Any]] = []
    seen_hrefs: set[str] = set()
    anchor_counts: dict[str, int] = {}

    for anchor in soup.find_all("a"):
        if not isinstance(anchor, Tag):
            continue
        if _is_non_nav_control(anchor):
            continue
        href_raw = str(anchor.get("href") or "").strip()
        if _is_skippable_href(href_raw):
            continue
        abs_href = _normalize_href(href_raw, base_url)
        if not abs_href:
            continue
        href_key = abs_href.lower().rstrip("/")
        if href_key in seen_hrefs:
            continue
        seen_hrefs.add(href_key)

        anchor_text = anchor.get_text(" ", strip=True)[:300]
        rel = _rel_tokens(anchor.get("rel"))
        is_nofollow = "nofollow" in rel or "ugc" in rel or "sponsored" in rel
        is_internal = True
        if abs_href.startswith(("http://", "https://")) and host:
            link_host = _page_host_key(abs_href)
            is_internal = bool(link_host) and (link_host == host or link_host.endswith("." + host))
        elif abs_href.startswith(("http://", "https://")):
            is_internal = False

        key = anchor_text.lower().strip() or "(trống)"
        anchor_counts[key] = anchor_counts.get(key, 0) + 1

        rows.append(
            {
                "href": abs_href[:500],
                "anchor": anchor_text,
                "is_internal": is_internal,
                "is_nofollow": is_nofollow,
                "rel": sorted(rel),
            }
        )

    # Legacy parsed_links fallback only when no <a> rows found
    if parsed_links and not rows:
        for item in parsed_links:
            if not isinstance(item, dict):
                continue
            href_raw = str(item.get("href") or "").strip()
            if _is_skippable_href(href_raw):
                continue
            abs_href = _normalize_href(href_raw, base_url)
            if not abs_href:
                continue
            href_key = abs_href.lower().rstrip("/")
            if href_key in seen_hrefs:
                continue
            seen_hrefs.add(href_key)
            rows.append(
                {
                    "href": abs_href[:500],
                    "anchor": str(item.get("anchor") or "")[:300],
                    "is_internal": bool(item.get("is_internal")),
                    "is_nofollow": bool(item.get("is_nofollow")),
                    "rel": list(item.get("rel") or []),
                }
            )

    internal_count = sum(1 for r in rows if r.get("is_internal"))
    external_count = sum(1 for r in rows if not r.get("is_internal"))
    nofollow_count = sum(1 for r in rows if r.get("is_nofollow"))
    dofollow_count = max(0, len(rows) - nofollow_count)
    anchor_texts = [
        {"text": text, "count": count}
        for text, count in sorted(anchor_counts.items(), key=lambda x: (-x[1], x[0]))[:30]
    ]

    http_broken: list[dict[str, Any]] = []
    if verify_http and rows:
        sample_urls = [r["href"] for r in rows if str(r.get("href") or "").startswith(("http://", "https://"))]
        http_broken = _verify_broken_links(sample_urls)

    opportunities: list[str] = []
    if internal_count < 3:
        opportunities.append("Thêm 3–8 internal link contextual tới pillar/cluster liên quan.")
    if external_count == 0:
        opportunities.append("Thêm 1–2 external link tới nguồn uy tín (E-E-A-T).")
    unique_anchors = len(anchor_counts)
    if len(rows) >= 4 and unique_anchors <= max(1, len(rows) // 3):
        opportunities.append("Đa dạng anchor text — tránh lặp cùng một cụm trên nhiều link.")

    partial_data = False
    warning = None
    if not rows:
        partial_data = True
        warning = _LINK_PARTIAL_WARNING
        opportunities.append("Trang không có thẻ <a href> hợp lệ để phân tích.")

    return {
        "internal_links_count": internal_count,
        "external_links_count": external_count,
        "total_links_count": len(rows),
        "broken_links": http_broken[:20],
        "anchor_texts": anchor_texts,
        "nofollow_count": nofollow_count,
        "dofollow_count": dofollow_count,
        "links": rows[:80],
        "link_opportunities": opportunities[:8],
        "partial_data": partial_data,
        "warning": warning,
        "http_verified": bool(verify_http),
        "http_checked_count": len({b.get("href") for b in http_broken}),
    }


def _empty_link_profile(*, partial: bool = True, warning: str | None = _LINK_PARTIAL_WARNING) -> dict[str, Any]:
    return {
        "internal_links_count": 0,
        "external_links_count": 0,
        "total_links_count": 0,
        "broken_links": [],
        "anchor_texts": [],
        "nofollow_count": 0,
        "dofollow_count": 0,
        "links": [],
        "link_opportunities": [],
        "partial_data": partial,
        "warning": warning if partial else None,
        "http_verified": False,
        "http_checked_count": 0,
    }
