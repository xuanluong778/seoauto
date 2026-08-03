"""
SERP result content type + format + dominant intent (Google's winners define the bar).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from app.services.search_intent import classify_search_intent

_ECOM_HOST = re.compile(
    r"(amazon\.|ebay\.|etsy\.|shopify\.|woocommerce|/product/|/products/|/shop/|/cart|/checkout)",
    re.I,
)
_CATEGORY_PATH = re.compile(r"/(category|categories|c|shop|store|collection|collections)/", re.I)
_FORUM = re.compile(r"(reddit\.|quora\.|stackoverflow\.|/forum|/community|/topic/)", re.I)
_BLOG_PATH = re.compile(r"/(blog|news|articles?|posts?|learn|resources)/", re.I)


def _classify_one_result(row: dict[str, Any]) -> dict[str, Any]:
    url = str(row.get("url") or "")
    title = str(row.get("title") or "")
    snip = str(row.get("snippet") or "")
    blob = f"{title} {snip}".lower()
    try:
        p = urlparse(url)
        path = (p.path or "").lower()
        host = (p.hostname or "").lower()
    except Exception:
        path, host = "", ""

    content_type = "blog"
    if _ECOM_HOST.search(url) or _ECOM_HOST.search(blob):
        content_type = "ecommerce"
    elif _FORUM.search(host + url):
        content_type = "forum"
    elif _CATEGORY_PATH.search(path) or re.search(r"/(cat|tag)/[^/]+/?$", path):
        content_type = "category"
    elif _BLOG_PATH.search(path) or "blog" in host:
        content_type = "blog"

    fmt: list[str] = []
    if re.search(r"\b(vs\.?|versus|compare|comparison)\b", blob):
        fmt.append("comparison")
    if re.search(r"\b(best|top \d+|\d+\s+(best|ways|tips))\b", blob):
        fmt.append("listicle")
    if re.search(r"\b(how to|guide|ultimate|step by step|tutorial)\b", blob):
        fmt.append("guide")
    if not fmt:
        fmt.append("listicle" if re.search(r"\b\d+\b", title) else "guide")

    intent_pkg = classify_search_intent(title or snip[:120] or url)
    return {
        "content_type": content_type,
        "content_formats": list(dict.fromkeys(fmt))[:3],
        "intent": str(intent_pkg.get("intent") or "informational"),
    }


def classify_serp_results(serp_results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate top organic rows into SERP-level type/format/intent signals.
    """
    if not serp_results:
        return {
            "serp_dominant_type": "blog",
            "serp_formats": [],
            "serp_intent": "informational",
            "explain": "no_serp_results",
        }

    types: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    intents: Counter[str] = Counter()

    for r in serp_results[:12]:
        one = _classify_one_result(r)
        types[one["content_type"]] += 1
        for f in one.get("content_formats") or []:
            formats[f] += 1
        intents[one.get("intent") or "informational"] += 1

    dom_type = types.most_common(1)[0][0] if types else "blog"
    dom_intent = intents.most_common(1)[0][0] if intents else "informational"
    top_formats = [f for f, _ in formats.most_common(4)]

    return {
        "serp_dominant_type": dom_type,
        "serp_formats": top_formats,
        "serp_intent": dom_intent,
        "type_distribution": dict(types),
        "format_distribution": dict(formats),
        "intent_distribution": {k: round(v / max(1, sum(intents.values())), 3) for k, v in intents.items()},
        "explain": "Heuristic URL path + title/snippet lexicon per result, then majority vote.",
    }
