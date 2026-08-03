"""
Choose schema.org types from parsed content + page intent + SERP dominant signals.
"""

from __future__ import annotations

from typing import Any


def detect_schema_types(
    parsed: dict[str, Any],
    *,
    page_url: str | None = None,
    page_intent: str | None = None,
    serp_dominant_type: str | None = None,
    serp_formats: list[str] | None = None,
) -> list[str]:
    """
    Returns ordered unique types (primary first). Always includes WebPage baseline.
    """
    sec = dict(parsed.get("sections") or {})
    types: list[str] = []

    def add(t: str) -> None:
        if t and t not in types:
            types.append(t)

    # SERP-informed priors
    st = (serp_dominant_type or "").lower()
    sf = [str(x).lower() for x in (serp_formats or [])]
    if "ecommerce" in st or sec.get("has_product"):
        add("Product")

    if sec.get("has_faq") or "faq" in " ".join(sf):
        add("FAQPage")
    if sec.get("has_howto") or "guide" in sf:
        add("HowTo")
    if sec.get("has_review"):
        add("Review")

    pi = (page_intent or "").lower()
    if pi == "transactional" and "Product" not in types and sec.get("has_product"):
        add("Product")
    if pi in ("commercial", "informational"):
        if not any(t in types for t in ("FAQPage", "HowTo", "Product")):
            add("Article")

    if sec.get("has_article_shell") and "Article" not in types:
        add("Article")

    add("WebPage")
    if parsed.get("breadcrumb_items"):
        add("BreadcrumbList")

    # Organization when we have brand-like entity
    if parsed.get("entities"):
        add("Organization")

    pu = (page_url or "").strip()
    if pu.startswith("http") and "WebSite" not in types:
        types.insert(max(0, len(types) - 1), "WebSite")

    return types
