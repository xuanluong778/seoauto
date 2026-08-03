"""
Aggregate autopilot outcomes and emit learning feedback (effectiveness + safe weight nudges).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.services.autopilot_store import iter_action_outcomes


def build_learning_feedback(*, max_events: int = 600) -> list[dict[str, Any]]:
    """
    Reads ``action_outcomes.jsonl`` and returns structured learning items.

    Callers should append outcomes via ``record_autopilot_outcome`` after validation runs.
    """
    events = list(iter_action_outcomes(max_lines=max_events))
    if not events:
        return [
            {
                "type": "cold_start",
                "message": "No action outcomes logged yet — learning_feedback is empty until validations are recorded.",
            }
        ]

    ratios: dict[str, list[float]] = defaultdict(list)
    success_hits: dict[str, int] = defaultdict(int)
    success_tot: dict[str, int] = defaultdict(int)

    for ev in events:
        it = str(ev.get("issue_type") or "unknown")
        pred = float(ev.get("predicted_impact_delta_prob") or 0.0) or 1e-6
        act = ev.get("actual_impact_delta_prob")
        if act is None:
            continue
        ratios[it].append(float(act) / pred)
        success_tot[it] += 1
        if bool(ev.get("success")):
            success_hits[it] += 1

    feedback: list[dict[str, Any]] = []
    for it, vals in ratios.items():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        rate = success_hits[it] / max(1, success_tot[it])
        feedback.append(
            {
                "type": "issue_type_calibration",
                "issue_type": it,
                "sample_size": len(vals),
                "mean_actual_over_predicted": round(m, 4),
                "success_rate": round(rate, 4),
                "suggested_delta_expected_impact": round(max(-0.04, min(0.04, 0.03 * (1.0 - m))), 4),
                "message": (
                    f"Issue «{it}»: realized impact / predicted = {m:.3f}; success_rate={rate:.2f}. "
                    "Nudge expected_impact_delta_prob in action_generator heuristics by suggested_delta when sample_size≥6."
                ),
            }
        )

    under = [f for f in feedback if f.get("mean_actual_over_predicted", 1) < 0.55 and f.get("sample_size", 0) >= 4]
    if under:
        feedback.append(
            {
                "type": "trust_weight_hint",
                "message": (
                    "Several issue types under-delivered vs predicted — tighten SERP/trust confidence in "
                    "prioritization_engine (multiply confidence by 0.92) until outcomes improve."
                ),
                "apply_to_modules": ["prioritization_engine", "action_generator._base_confidence"],
            }
        )

    return feedback[:24]
