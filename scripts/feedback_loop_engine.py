"""
Conservative feedback suggestions from recent validation events.

Adjusts trust weights slightly and flags modules when systematic misalignment appears.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.ground_truth_store import iter_validation_events


def run_feedback_loop(*, max_events: int = 200) -> dict[str, Any]:
    """
    Scan ``validation_log.jsonl`` and emit safe nudges to ``trust_weight_adjustment``.

    This is intentionally conservative: multiplicative factors clamped near 1.0.
    """
    events = list(iter_validation_events(max_lines=max_events))
    if not events:
        return {
            "trust_weight_adjustment": {"serp_alignment": 1.0, "topical_composite": 1.0},
            "unreliable_modules": [],
            "signals": {"events": 0},
            "explain": "No validation history yet — no feedback.",
        }

    bad_align = 0
    absent_high_prob = 0
    for ev in events:
        reasons = list(ev.get("misalignment_reasons") or [])
        blob = " ".join(reasons).lower()
        if "serp alignment" in blob or "alignment" in blob:
            bad_align += 1
        if "absent" in blob or "high ranking_probability" in blob:
            absent_high_prob += 1

    n = len(events)
    aw_align = 1.0 - min(0.12, 0.03 * (bad_align / max(1, n // 3 or 1)))
    aw_top = 1.0 - min(0.08, 0.02 * (absent_high_prob / max(1, n // 3 or 1)))

    unreliable: list[dict[str, Any]] = []
    if bad_align >= max(4, n // 4):
        unreliable.append(
            {
                "module": "mean_serp_alignment_signal",
                "severity": "watch",
                "reason": "Repeated validator hints referencing SERP alignment vs observed ranks.",
            }
        )
    if absent_high_prob >= max(4, n // 4):
        unreliable.append(
            {
                "module": "ranking_probability_head",
                "severity": "watch",
                "reason": "Several events with high probability but missing/weak URL presence in SERP samples.",
            }
        )

    reason_counts = Counter()
    for ev in events:
        for r in ev.get("misalignment_reasons") or []:
            reason_counts[str(r)[:120]] += 1

    return {
        "trust_weight_adjustment": {
            "serp_alignment": round(max(0.85, min(1.05, aw_align)), 4),
            "topical_composite": round(max(0.88, min(1.05, aw_top)), 4),
        },
        "unreliable_modules": unreliable,
        "signals": {
            "events": n,
            "bad_alignment_hints": bad_align,
            "absent_high_prob_hints": absent_high_prob,
            "top_reasons": [k for k, _ in reason_counts.most_common(5)],
        },
        "explain": (
            "Reads recent validation events; applies small downward multipliers on "
            "``serp_alignment`` / ``topical_composite`` trust weights when repeated "
            "misalignment strings occur. Flags modules for human review only."
        ),
    }
