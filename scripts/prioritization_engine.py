"""
Score actions: impact × confidence ÷ effort (higher = do first).
"""

from __future__ import annotations

from typing import Any

_EFFORT_W = {"low": 1.0, "medium": 2.1, "high": 3.6}


def prioritize_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Adds ``priority_score`` and sorts descending.
    """
    out: list[dict[str, Any]] = []
    for a in actions:
        row = dict(a)
        impact = float(row.get("expected_impact_delta_prob") or 0.0)
        conf = float(row.get("confidence") or 0.65)
        eff = str(row.get("effort") or "medium").lower()
        w = float(_EFFORT_W.get(eff, 2.1))
        row["priority_score"] = round((impact * max(0.15, conf)) / max(0.85, w), 5)
        out.append(row)
    out.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    return out
