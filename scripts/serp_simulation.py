"""
Estimate whether your page can crack top 10 given SERP competitor strength.
"""

from __future__ import annotations

import math
from typing import Any


def simulate_serp_ranking(
    keyword: str,
    your_page: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    ``your_page``: at least ``pagerank_score`` or ``estimated_authority``, ``word_count``, optional ``title``.
    ``competitors``: enriched SERP rows with ``estimated_authority``.
    """
    comps = competitors[:15]
    if not comps:
        return {
            "estimated_position_range": [8, 15],
            "probability_top10": 0.35,
            "limiting_factors": ["No SERP competitors supplied — wide uncertainty."],
        }

    auths = sorted([float(c.get("estimated_authority") or 0.25) for c in comps], reverse=True)
    top10 = auths[:10]
    bench = sum(top10) / len(top10)

    y_pr = float(your_page.get("pagerank_score") or your_page.get("estimated_authority") or 0.3)
    y_wc = int(your_page.get("word_count") or 0)
    y_strength = 0.55 * y_pr + 0.45 * min(1.0, y_wc / 1200.0)

    gap = bench - y_strength
    p10 = 1.0 / (1.0 + math.exp(3.2 * gap - 0.35))
    p10 = max(0.05, min(0.92, round(p10, 3)))

    center = 6 + int(round(14 * (1.0 - y_strength / max(0.2, bench))))
    center = max(3, min(18, center))
    lo = max(1, center - 4)
    hi = min(22, center + 5)

    lims: list[str] = []
    if gap > 0.25:
        lims.append("Average top-10 competitor authority proxy exceeds your page strength.")
    if y_wc < 500:
        lims.append("Thin content vs typical ranking pages for informational SERPs.")
    if bench > 0.65:
        lims.append("Dense high-authority SERP — brand and link equity dominate.")
    if not lims:
        lims.append("Limited factors in model — still validate with live rank tracking.")

    return {
        "estimated_position_range": [lo, hi],
        "probability_top10": p10,
        "limiting_factors": lims[:6],
    }
