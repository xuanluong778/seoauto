"""
Bucket prioritized actions into quick wins vs mid-term vs long-term execution lanes.
"""

from __future__ import annotations

from typing import Any


def build_execution_roadmap(prioritized_actions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    ``roadmap`` keys: ``quick_wins``, ``mid_term``, ``long_term``.
    """
    quick: list[dict[str, Any]] = []
    mid: list[dict[str, Any]] = []
    long: list[dict[str, Any]] = []

    for a in prioritized_actions:
        eff = str(a.get("effort") or "medium").lower()
        ps = float(a.get("priority_score") or 0.0)
        if eff == "low" and ps >= 0.018:
            quick.append(a)
        elif eff == "high" or float(a.get("expected_impact_delta_prob") or 0) >= 0.14:
            long.append(a)
        else:
            mid.append(a)

    return {
        "quick_wins": quick[:12],
        "mid_term": mid[:15],
        "long_term": long[:10],
        "explain": (
            "quick_wins = low effort + priority_score≥0.018; long_term = high effort OR high expected Δp; "
            "mid_term = remainder."
        ),
    }
