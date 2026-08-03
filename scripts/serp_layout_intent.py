"""
Infer search intent signals from top organic URLs (+ titles): page-type mix → intent distribution.

Used as a clustering constraint alongside lexical intent heuristics.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

# Page types we classify from URL/title heuristics (no full HTML fetch).
PAGE_TYPES = frozenset(
    {
        "blog",
        "article",
        "news",
        "product",
        "category",
        "video",
        "forum",
        "docs",
        "homepage",
        "login",
        "directory",
        "landing",
        "other",
    }
)

# Roll each page type into a classic search-intent bucket for % distribution.
_TYPE_TO_INTENT: dict[str, str] = {
    "blog": "informational",
    "article": "informational",
    "news": "informational",
    "docs": "informational",
    "forum": "informational",
    "video": "informational",
    "product": "transactional",
    "category": "commercial",
    "directory": "commercial",
    "landing": "commercial",
    "homepage": "navigational",
    "login": "navigational",
    "other": "informational",
}

_BLOG_PATH = re.compile(
    r"/(blog|posts?|articles?|bai-viet|tin-tuc|kien-thuc|huong-dan)(/|$)",
    re.I,
)
_NEWS_PATH = re.compile(r"/(news|tin-tuc-su-kien|press)(/|$)", re.I)
_PRODUCT_PATH = re.compile(
    r"/(product|products|p/|item|items|shop|store|cart|checkout|san-pham|sp/|mua-hang)(/|$)",
    re.I,
)
_CATEGORY_PATH = re.compile(
    r"/(categor(?:y|ies)|collections?|catalog|department|danh-muc|dmsp|nhom-hang)(/|$)",
    re.I,
)
_FORUM_PATH = re.compile(r"/(forum|community|threads?|topic)(/|$)", re.I)
_DOCS_PATH = re.compile(r"/(docs?|documentation|support/help|kb)(/|$)", re.I)
_LOGIN_PATH = re.compile(r"/(login|signin|dang-nhap|register|signup)(/|$)", re.I)
_VIDEO_HOST = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com|tiktok\.com)", re.I)


def classify_page_type(url: str, title: str = "") -> str:
    """Lightweight page archetype from URL path + title (top-10 context)."""
    u = (url or "").strip()
    t = (title or "").strip().lower()
    if not u:
        return "other"
    low = u.lower()
    if _VIDEO_HOST.search(low) or "/watch?" in low or "youtube.com" in low:
        return "video"
    try:
        p = urlparse(u)
        path = (p.path or "/").lower()
        host = (p.hostname or "").lower()
    except Exception:
        return "other"

    if _LOGIN_PATH.search(path) or "login" in t or "đăng nhập" in t:
        return "login"
    if path in ("/", "") or path.count("/") <= 1 and len(path) < 4:
        if not host.startswith("www.") and path in ("/", ""):
            return "homepage"

    if _PRODUCT_PATH.search(path) or "add to cart" in t or "mua ngay" in t or "giỏ hàng" in t:
        return "product"
    if _CATEGORY_PATH.search(path):
        return "category"
    if _FORUM_PATH.search(path):
        return "forum"
    if _DOCS_PATH.search(path):
        return "docs"
    if _NEWS_PATH.search(path) or "breaking" in t or "tin nóng" in t:
        return "news"
    if _BLOG_PATH.search(path) or "how to" in t or "hướng dẫn" in t:
        return "blog"

    if " review" in t or " vs " in t or "đánh giá" in t or "so sánh" in t:
        return "landing"

    if path.count("/") >= 2 and len(path) > 24:
        return "article"

    return "other"


def infer_serp_layout_intent(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """
    From a ``fetch_serp_for_keyword`` snapshot, derive page-type mix + rolled-up intent %.

    Returns ``None`` if there are no organic URLs.
    """
    urls = list(snapshot.get("serp_urls") or [])
    titles = list(snapshot.get("titles") or [])
    if not urls:
        return None

    page_types: list[str] = []
    for i, u in enumerate(urls):
        title = titles[i] if i < len(titles) else ""
        page_types.append(classify_page_type(str(u), str(title)))

    n = len(page_types)
    type_counts = Counter(page_types)
    page_type_distribution = {k: round(v / n, 4) for k, v in type_counts.most_common()}

    intent_counts: Counter[str] = Counter()
    for pt in page_types:
        intent_counts[_TYPE_TO_INTENT.get(pt, "informational")] += 1

    intent_keys = ["informational", "navigational", "transactional", "commercial"]
    intent_distribution = {k: round(intent_counts.get(k, 0) / n, 4) for k in intent_keys}

    ranked = intent_counts.most_common()
    top_intent, top_c = ranked[0]
    second_c = ranked[1][1] if len(ranked) > 1 else 0
    top_share = top_c / n
    second_share = second_c / n

    top_type_share = (type_counts.most_common(1)[0][1] / n) if type_counts else 0.0

    # Mixed when SERP is split across intents or page archetypes are fragmented.
    mixed = (
        top_share < float(os.getenv("SERP_INTENT_TOP_SHARE_MIN", "0.48"))
        or second_share >= float(os.getenv("SERP_INTENT_SECOND_SHARE_TRIGGER", "0.28"))
        or top_type_share < float(os.getenv("SERP_PAGE_TYPE_TOP_SHARE_MIN", "0.35"))
    )

    effective = "mixed_intent" if mixed else str(top_intent)

    return {
        "page_types": page_types,
        "page_type_distribution": page_type_distribution,
        "intent_distribution": intent_distribution,
        "mixed_intent": mixed,
        "effective_intent": effective,
        "top_page_types": type_counts.most_common(5),
    }
