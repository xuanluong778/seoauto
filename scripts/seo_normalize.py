"""Chuẩn hóa URL và text — giảm false positive do encoding / khoảng trắng."""

from __future__ import annotations

import html as html_module
import re
from urllib.parse import urljoin, urlparse, urlunparse

_ws_re = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    s = html_module.unescape(str(value))
    s = _ws_re.sub(" ", s).strip()
    return s


def normalize_canonical(href: str | None, base_url: str) -> str:
    if not href or not str(href).strip():
        return ""
    h = normalize_text(href)
    if not h:
        return ""
    if h.startswith("//"):
        p = urlparse(base_url or "https://example.com")
        h = f"{p.scheme}:{h}"
    if base_url and not urlparse(h).netloc:
        h = urljoin(base_url if base_url.endswith("/") else base_url + "/", h)
    try:
        from app.services.crawler import normalize_url

        return normalize_url(h)
    except Exception:
        return h.strip()


def normalize_url_safe(raw: str) -> str:
    from app.services.crawler import normalize_url

    try:
        return normalize_url(raw)
    except Exception:
        return (raw or "").strip()
