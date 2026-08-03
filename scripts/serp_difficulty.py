"""
SERP difficulty 0–100: domain diversity, content strength, benchmark tightness.
"""

from __future__ import annotations

from typing import Any


def compute_serp_difficulty(
    benchmark: dict[str, Any],
    cluster_view: dict[str, Any],
    *,
    competitor_count: int,
) -> dict[str, Any]:
    """
    Higher score = harder to break in (strong, diverse incumbents + thick content).
    """
    div = float(cluster_view.get("diversity_score") or 0.0)
    uniq = int(cluster_view.get("unique_domains") or 0)
    aw = int(benchmark.get("avg_word_count") or 0)
    ah = float(benchmark.get("avg_heading_score") or 0.0)
    ail = float(benchmark.get("avg_internal_links") or 0.0)

    # Diversity increases difficulty (many distinct strong domains)
    d_comp = min(35.0, div * 55.0 + min(uniq, 10) * 1.8)
    # Content bar
    c_comp = min(40.0, (aw / 3500.0) * 38.0 + ah * 22.0 + min(ail / 35.0, 1.0) * 18.0)
    # Sample confidence
    s = min(25.0, max(competitor_count, 1) * 2.2)

    score = min(100.0, round(d_comp + c_comp + s, 1))
    return {
        "difficulty_score": score,
        "components": {
            "domain_competition": round(d_comp, 1),
            "content_bar": round(c_comp, 1),
            "sample_confidence": round(s, 1),
        },
        "explain": "Difficulty rises with unique strong domains and high average word count / structure / internal links among top results.",
    }
