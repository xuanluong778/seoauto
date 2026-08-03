"""
Score keyword clusters for prioritization (volume × intent value × opportunity × (1 - difficulty)).
"""

from __future__ import annotations

from typing import Any

_INTENT_VALUE = {
    "transactional": 1.0,
    "commercial": 0.78,
    "informational": 0.55,
    "navigational": 0.38,
}


def score_keyword_clusters(
    clusters: list[dict[str, Any]],
    *,
    ranking_probability: float | None = None,
    mean_serp_alignment: float | None = None,
) -> list[dict[str, Any]]:
    """
    Adds ``priority_score`` and ``recommended_content_type`` per cluster.

    ``ranking_opportunity`` blends site-level ``ranking_probability`` and optional ``mean_serp_alignment``.
    """
    rp = 0.55
    if ranking_probability is not None:
        rp = max(0.08, min(0.95, float(ranking_probability)))
    align = mean_serp_alignment
    if align is None:
        align = 0.5
    align = max(0.05, min(0.98, float(align)))
    ranking_opp = round(0.55 * rp + 0.45 * align, 4)

    out: list[dict[str, Any]] = []
    for c in clusters:
        row = dict(c)
        intent = str(row.get("intent") or "informational").lower()
        iv = float(_INTENT_VALUE.get(intent, 0.55))
        vol = int(row.get("total_search_volume") or 0)
        vol_n = min(1.0, vol / max(1.0, float(5000.0))) if vol else 0.12
        serp_ov = float(row.get("serp_overlap_score") or row.get("serp_similarity_avg") or 0.0)
        diff = 0.45
        kws = row.get("keywords") or []
        diffs = [float(x.get("difficulty")) for x in kws if x.get("difficulty") is not None]
        if diffs:
            diff = sum(diffs) / len(diffs)
        else:
            diff = max(0.12, min(0.9, 0.55 - 0.35 * serp_ov))
        diff = max(0.08, min(0.95, diff))
        score = (vol_n * iv * ranking_opp) * (1.0 - diff * 0.85)
        row["priority_score"] = round(max(0.0, score) * 100.0, 2)
        row["ranking_opportunity_component"] = ranking_opp
        row["intent_value"] = iv
        if intent in ("transactional", "commercial"):
            row["recommended_content_type"] = "conversion-focused landing + comparison/FAQ blocks"
        elif intent == "navigational":
            row["recommended_content_type"] = "brand hub + sitelinks-friendly structure"
        else:
            row["recommended_content_type"] = "deep guide / pillar + FAQ schema where SERP shows PAA"
        out.append(row)
    out.sort(key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    return out
