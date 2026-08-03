"""
Actionable content strategy from SERP benchmark + gaps + inferred factors.
"""

from __future__ import annotations

from typing import Any


def build_content_strategy(
    keyword: str,
    *,
    target_url: str,
    benchmark: dict[str, Any],
    gap_issues: list[dict[str, Any]],
    ranking_factors: list[dict[str, Any]],
) -> dict[str, Any]:
    wc = int(benchmark.get("avg_word_count") or 800)
    target_wc = int(max(wc * 1.05, wc + 200))

    ctype = "guide"
    low = (keyword or "").lower()
    if any(x in low for x in ("best", "top", "review", "vs")):
        ctype = "list"
    if any(x in low for x in ("tool", "calculator", "generator", "checker")):
        ctype = "tool"
    if any(x in low for x in ("buy", "price", "cheap", "order")):
        ctype = "landing"

    must_kw = list(benchmark.get("common_ngrams") or [])[:10]
    structure = ["Single clear H1 aligned to query", "2–4 H2 sections (intent-matched)", "FAQ or comparison block", "CTA / next-step block"]
    if ctype == "list":
        structure.insert(1, "Numbered or card list for entities")
    if ctype == "tool":
        structure = ["Above-the-fold interactive", "How it works (H2)", "Trust + limitations", "Related guides"]

    link_strat = "Link from 2+ high-PR internal hubs plus breadcrumbs; add 4–8 contextual links to sibling topics."
    if any(g.get("issue") == "weak_internal_linking_vs_serp" for g in gap_issues):
        link_strat = "Priority: expand internal links to match SERP-average inlinks; use descriptive anchors."

    return {
        "target_url": target_url,
        "recommended_word_count": target_wc,
        "recommended_structure": structure,
        "must_have_keywords": must_kw,
        "internal_linking_strategy": link_strat,
        "content_type": ctype,
        "why": "Targets SERP centroid length, borrows winning n-grams, and aligns format to query modifiers.",
        "informed_by_factors": [f.get("factor") for f in ranking_factors[:3]],
    }
