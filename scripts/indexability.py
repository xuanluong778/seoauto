"""
Indexability: HTTP status + HTML meta robots + X-Robots-Tag (response headers).

Any explicit noindex / none in meta or headers → not indexable.
Mismatches between raw vs rendered headers lower confidence.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.seo_normalize import normalize_text


def _header_ci(headers: dict[str, Any] | None, name: str) -> str:
    if not headers:
        return ""
    want = name.lower()
    for k, v in headers.items():
        if str(k).lower() == want:
            return normalize_text(str(v))
    return ""


def _meta_robots_directives(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []
    for name in ("robots", "googlebot"):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content") is not None:
            parts.append(normalize_text(m.get("content")))
    return ", ".join(p for p in parts if p)


def _has_noindex_none(text: str) -> bool:
    t = (text or "").lower()
    if "none" in t:
        return True
    return bool(re.search(r"\bnoindex\b", t))


def assess_indexability(
    rendered_html: str,
    response_headers: dict[str, Any] | None,
    http_status: int,
    *,
    secondary_headers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta_txt = _meta_robots_directives(rendered_html or "")
    xr = _header_ci(response_headers, "x-robots-tag")
    sec_xr = _header_ci(secondary_headers, "x-robots-tag") if secondary_headers else ""

    meta_n = _has_noindex_none(meta_txt)
    xr_n = _has_noindex_none(xr)
    sec_n = _has_noindex_none(sec_xr)

    base_conf = 0.9
    if sec_xr and xr and sec_xr.lower().strip() != xr.lower().strip():
        base_conf -= 0.1
    if meta_txt and xr and meta_n != xr_n:
        base_conf -= 0.12

    if http_status < 200 or http_status >= 400:
        return {
            "indexable": False,
            "indexability_reason": f"Mã HTTP {http_status} — không phải phản hồi thành công cho indexing thông thường.",
            "indexability_confidence": 0.97,
            "meta_robots_text": meta_txt or None,
            "x_robots_tag": xr or None,
            "x_robots_tag_raw": sec_xr or None,
        }

    blocked = meta_n or xr_n or sec_n
    if blocked:
        parts: list[str] = []
        if meta_n:
            parts.append("Meta robots/googlebot: noindex hoặc none.")
        if xr_n:
            parts.append("X-Robots-Tag (document cuối): noindex/none.")
        if sec_n and (not xr_n or sec_xr.lower() != xr.lower()):
            parts.append("X-Robots-Tag trên raw HTTP báo noindex/none (so với document).")
        return {
            "indexable": False,
            "indexability_reason": " ".join(parts).strip(),
            "indexability_confidence": max(0.42, min(0.97, base_conf)),
            "meta_robots_text": meta_txt or None,
            "x_robots_tag": xr or None,
            "x_robots_tag_raw": sec_xr or None,
        }

    return {
        "indexable": True,
        "indexability_reason": "HTTP 200 và không phát hiện noindex/none trong meta robots chính hoặc X-Robots-Tag đã xét.",
        "indexability_confidence": max(0.58, min(0.95, base_conf)),
        "meta_robots_text": meta_txt or None,
        "x_robots_tag": xr or None,
        "x_robots_tag_raw": sec_xr or None,
    }
