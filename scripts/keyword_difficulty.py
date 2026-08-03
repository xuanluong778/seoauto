"""
Keyword difficulty from SERP competitor analysis — relative competition, not third-party KD APIs.
"""

from __future__ import annotations

import math
from typing import Any


def compute_keyword_difficulty(serp_analysis: dict[str, Any]) -> dict[str, Any]:
    """
    ``serp_analysis``: output of ``analyze_serp_competitors`` (``avg_authority``, ``max_authority``,
    ``authority_distribution``, ``weak_pages_count``, ``competitors`` list).
    """
    comp = list(serp_analysis.get("competitors") or [])
    n = max(1, len(comp))
    avg_a = float(serp_analysis.get("avg_authority") or 0.0)
    max_a = float(serp_analysis.get("max_authority") or 0.0)
    p90 = float((serp_analysis.get("authority_distribution") or {}).get("p90") or avg_a)
    weak = int(serp_analysis.get("weak_pages_count") or 0)

    # Homogeneity: low stdev of authority → harder (everyone similarly strong)
    auths = [float(x.get("estimated_authority") or 0) for x in comp]
    if len(auths) >= 2:
        mean = sum(auths) / len(auths)
        var = sum((a - mean) ** 2 for a in auths) / len(auths)
        stdev = math.sqrt(var)
        homogeneity = 1.0 - min(1.0, stdev * 2.2)
    else:
        homogeneity = 0.35

    base = 38.0 + 42.0 * max_a + 18.0 * avg_a + 12.0 * p90
    base += homogeneity * 14.0
    base -= min(22.0, weak * 3.8)

    difficulty_score = max(0.0, min(100.0, round(base, 1)))
    if difficulty_score < 38.0:
        level = "easy"
    elif difficulty_score < 62.0:
        level = "medium"
    else:
        level = "hard"

    reasoning: list[str] = []
    if max_a >= 0.55:
        reasoning.append("Top of SERP includes very high authority signals (internal PR or strong domains).")
    if homogeneity > 0.62:
        reasoning.append("Competitor strength is homogeneous — few weak URLs to displace.")
    if weak >= 3:
        reasoning.append("Several weaker competitors detected — more room to break in with better content/links.")
    if avg_a < 0.32:
        reasoning.append("Average competitor authority is moderate — niche may still be contestable.")
    if not reasoning:
        reasoning.append("Difficulty driven by blended authority percentiles and SERP depth.")

    return {
        "difficulty_score": difficulty_score,
        "difficulty_level": level,
        "reasoning": reasoning[:8],
    }
