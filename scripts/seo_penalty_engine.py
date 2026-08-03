"""
Hard-style penalties for ranking simulation (intent, SERP, trust, cloaking, JS).
"""

from __future__ import annotations

from typing import Any


def compute_seo_penalties(
    *,
    intent_mismatch: bool,
    serp_alignment_score: float,
    topical_trust_score: float,
    cloaking_risk: bool,
    cloaking_level: str | None,
    js_dependency_level: str | None,
    serp_volatility: float | None = None,
) -> list[dict[str, Any]]:
    """
    Returns ``[{ "type", "impact", "reason" }]`` with ``impact`` negative (e.g. -0.32).
    """
    penalties: list[dict[str, Any]] = []

    if intent_mismatch:
        penalties.append(
            {
                "type": "intent_mismatch",
                "impact": -0.32,
                "reason": "Site / cluster intent không khớp intent dominant trên SERP.",
            }
        )

    if serp_alignment_score < 0.42:
        penalties.append(
            {
                "type": "serp_misalignment",
                "impact": round(-0.18 - 0.35 * (0.42 - serp_alignment_score), 3),
                "reason": "Loại nội dung / format lệch so với winners SERP.",
            }
        )

    if topical_trust_score < 0.45:
        penalties.append(
            {
                "type": "low_trust_data",
                "impact": round(-0.12 - 0.25 * (0.45 - topical_trust_score), 3),
                "reason": "Crawl/render/SERP tín hiệu tin cậy thấp — giảm trọng số suy luận.",
            }
        )

    lvl = str(cloaking_level or "").lower()
    if cloaking_risk or lvl in ("high", "medium"):
        penalties.append(
            {
                "type": "cloaking_signal",
                "impact": -0.28 if lvl == "high" else -0.16,
                "reason": "Raw vs rendered / cloaking heuristic — rủi ro trust Google.",
            }
        )

    js = str(js_dependency_level or "").lower()
    if js == "high":
        penalties.append(
            {
                "type": "js_dependency_risk",
                "impact": -0.14,
                "reason": "JS dependency cao — nội dung chính có thể muộn / không ổn định cho bot.",
            }
        )
    elif js == "medium":
        penalties.append(
            {
                "type": "js_dependency_risk",
                "impact": -0.07,
                "reason": "JS dependency trung bình.",
            }
        )

    if serp_volatility is not None and serp_volatility > 0.72:
        penalties.append(
            {
                "type": "serp_volatility",
                "impact": -0.06,
                "reason": "SERP đa dạng type — template đơn ít đủ để thắng hơn.",
            }
        )

    return penalties
