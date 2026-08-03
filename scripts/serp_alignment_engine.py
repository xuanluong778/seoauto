"""
Map SERP feature signals to schema recommendations and alignment notes.
"""

from __future__ import annotations

from typing import Any


def build_serp_alignment(
    *,
    schema_types: list[str],
    serp_formats: list[str] | None,
    serp_dominant: str | None,
    serp_features: dict[str, Any] | None,
) -> dict[str, Any]:
    formats = [str(x).lower() for x in (serp_formats or [])]
    feats = dict(serp_features or {})
    suggestions: list[str] = []
    matched: list[str] = []
    gaps: list[str] = []

    def has_schema(t: str) -> bool:
        return t in schema_types

    if "faq" in formats or feats.get("has_faq"):
        if has_schema("FAQPage"):
            matched.append("FAQ SERP ↔ FAQPage schema")
        else:
            gaps.append("SERP shows FAQ-style results; add FAQPage + Question/Answer pairs from real content.")
            suggestions.append("Add FAQPage only if page has genuine Q&A blocks.")

    if "ecommerce" in str(serp_dominant).lower() or feats.get("commercial_organic_hint"):
        if has_schema("Product"):
            matched.append("Product-heavy SERP ↔ Product schema")
        else:
            gaps.append("SERP is product/commercial; consider Product + Offer with accurate price/stock.")
            suggestions.append("Add Product with valid offers, GTIN/MPN if available.")

    if "guide" in formats or feats.get("has_howto"):
        if has_schema("HowTo"):
            matched.append("How-to SERP ↔ HowTo schema")
        else:
            gaps.append("SERP shows step-by-step guides; consider HowTo with ordered steps.")
            suggestions.append("Add HowTo with one step per logical instruction.")

    if "review" in formats or feats.get("has_review_snippet"):
        if has_schema("Review"):
            matched.append("Review snippets ↔ Review schema")
        else:
            suggestions.append("If editorial reviews exist, add Review with rating aggregate where applicable.")

    if not gaps and not suggestions:
        suggestions.append("Align primary entity (Article vs Product) with dominant SERP intent.")

    score = 0.5
    if matched:
        score = min(1.0, 0.5 + 0.15 * len(matched))
    if gaps:
        score = max(0.2, score - 0.1 * len(gaps))

    return {
        "serp_dominant_type": serp_dominant,
        "serp_formats": formats,
        "matched": matched,
        "gaps": gaps,
        "suggestions": suggestions,
        "alignment_score": round(score, 2),
    }
