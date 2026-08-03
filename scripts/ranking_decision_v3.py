"""
Ranking decision v3: multi-signal site-level probability (not a checklist).
"""

from __future__ import annotations

from typing import Any


def build_site_ranking_decision_v3(
    *,
    technical_health: float,
    indexable_ratio: float,
    mean_ranking_score_0_100: float,
    mean_topical_authority_0_1: float,
    mean_serp_alignment: float,
    penalties: list[dict[str, Any]],
    trust_weight_adjustment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    ``mean_topical_authority_0_1``: average cluster composite authority (0–1).

    Penalties are negative impacts applied to ``ranking_probability``.
    """
    tech = max(0.0, min(1.0, float(technical_health) / 100.0))
    idx = max(0.0, min(1.0, float(indexable_ratio)))
    rnk = max(0.0, min(1.0, float(mean_ranking_score_0_100) / 100.0))
    top = max(0.0, min(1.0, float(mean_topical_authority_0_1)))
    align = max(0.0, min(1.0, float(mean_serp_alignment)))

    wa = dict(trust_weight_adjustment or {})
    aw_align = float(wa.get("serp_alignment", 1.0))
    aw_top = float(wa.get("topical_composite", 1.0))

    base = (
        0.18 * tech
        + 0.22 * idx
        + 0.24 * rnk
        + 0.22 * top * aw_top
        + 0.14 * align * aw_align
    )

    pen_sum = sum(float(p.get("impact") or 0) for p in penalties)
    prob = base + pen_sum
    prob = round(max(0.03, min(0.93, prob)), 3)

    will_rank = bool(idx >= 0.52 and prob >= 0.48)

    reasons: list[str] = []
    if not will_rank:
        if idx < 0.52:
            reasons.append("Indexing / indexability simulation yếu trên một phần lớn URL.")
        if top * aw_top < 0.38:
            reasons.append("Low topical authority (entity + intent + coverage composite).")
        if align * aw_align < 0.4:
            reasons.append("SERP intent / format misalignment vs winners.")
        if rnk < 0.42:
            reasons.append("Technical + graph ranking potential trung bình thấp.")
        for p in penalties[:4]:
            reasons.append(str(p.get("reason") or p.get("type") or "penalty"))

    if not reasons and will_rank:
        reasons.append("Multi-signal stack đủ mạnh để có xác suất ranking hợp lý (không bảo đảm vị trí).")

    return {
        "will_rank": will_rank,
        "ranking_probability": prob,
        "primary_reasons": reasons[:8],
        "components": {
            "technical": round(tech, 3),
            "indexable_ratio": round(idx, 3),
            "mean_ranking_score": round(rnk, 3),
            "mean_topical_authority": round(top, 3),
            "mean_serp_alignment": round(align, 3),
            "penalty_sum": round(pen_sum, 3),
        },
        "explain": "v3 blends technical health, indexability ratio, mean page ranking score, trust-weighted topical + SERP alignment, then applies penalty impacts.",
    }
