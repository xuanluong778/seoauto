"""Heuristic page type — giảm false positive (H1, meta…) theo ngữ cảnh."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

from bs4 import BeautifulSoup

PageType = Literal["homepage", "article", "category", "landing", "unknown"]


def detect_page_type(url: str, html: str, parsed: dict[str, Any] | None = None) -> PageType:
    path = (urlparse(url).path or "/").lower()
    if path in ("/", ""):
        return "homepage"

    if re.search(r"/(tag|tags|category|categories|shop|store|collection|collections)/", path):
        return "category"
    if re.search(r"/(lp|landing|promo|campaign)/", path):
        return "landing"
    if re.search(
        r"/(\d{4}/\d{2}/|blog/|news/|bai-viet/|posts?/|article/|p/\d)",
        path,
    ):
        return "article"

    safe = html if isinstance(html, str) else ""
    if len(safe) > 500_000:
        safe = safe[:500_000]
    soup = BeautifulSoup(safe, "html.parser")

    for script in soup.find_all("script"):
        st = script.get("type") or ""
        if "ld+json" not in str(st).lower():
            continue
        txt = script.string or script.get_text() or ""
        if any(x in txt for x in ("Article", "NewsArticle", "BlogPosting")):
            return "article"

    body = soup.find("body")
    class_str = ""
    if body and body.get("class"):
        class_str = " ".join(str(c) for c in body.get("class", [])).lower()
    if re.search(r"single-post|postid-|type-post|article", class_str):
        return "article"
    if re.search(r"archive|category|tax-|blog-index", class_str):
        return "category"

    wc = int((parsed or {}).get("word_count") or 0)
    links = len(soup.find_all("a", href=True))
    if wc < 400 and links > 40:
        return "category"

    if wc > 600 and path.count("/") >= 3:
        return "article"

    return "unknown"
