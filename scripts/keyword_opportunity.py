"""
Keyword opportunity: blends volume proxy, difficulty, your page strength, topical authority.
"""

from __future__ import annotations

import math
from typing import Any


def compute_keyword_opportunity(
    keyword: str,
    *,
    search_volume: int | None,
    difficulty: dict[str, Any],
    your_ranking_score: float,
    topical_authority_score: float | None = None,
) -> dict[str, Any]:
    """
    ``difficulty``: output of ``compute_keyword_difficulty``.
    ``your_ranking_score``: 0–100 from ranking layer for best-matching URL.
    ``topical_authority_score``: 0–100 cluster authority or None (neutral 50).
    """
    kd = float(difficulty.get("difficulty_score") or 50.0)
    vol = int(search_volume) if search_volume is not None else None
    if vol is None or vol <= 0:
        vol_component = 0.55
    else:
        vol_component = min(1.0, math.log1p(vol) / math.log1p(50000))

    ta = float(topical_authority_score) if topical_authority_score is not None else 50.0
    ta_n = max(0.0, min(1.0, ta / 100.0))

    y = max(0.0, min(100.0, float(your_ranking_score)))
    y_n = y / 100.0

    # High opportunity when: volume decent, difficulty not extreme, you are strong, topical fit ok
    raw = (
        22.0 * vol_component
        + 28.0 * y_n
        + 18.0 * ta_n
        + 32.0 * max(0.0, (72.0 - kd) / 72.0)
    )
    opportunity_score = max(0.0, min(100.0, round(raw, 1)))

    if opportunity_score >= 68.0:
        level = "high"
    elif opportunity_score >= 42.0:
        level = "medium"
    else:
        level = "low"

    why: list[str] = []
    if kd < 45:
        why.append("SERP difficulty is on the lower side for this snapshot.")
    if y >= 58:
        why.append("Your audited page already shows solid ranking potential signals.")
    if ta_n >= 0.55:
        why.append("Site topical authority cluster is relatively strong for this theme.")
    if vol_component >= 0.7:
        why.append("Search demand (volume) is meaningful if volume data is accurate.")
    if not why:
        why.append("Opportunity is mixed — prioritize closing authority/content gaps before scaling.")

    actions: list[str] = []
    if kd > 65:
        actions.append("Target long-tail variants or supporting pages before attacking head term.")
    if y < 48:
        actions.append("Fix technical/indexability and strengthen on-page before competing on this SERP.")
    if ta_n < 0.4:
        actions.append("Build topical depth and internal links in this cluster before expecting headway.")
    if vol is None:
        actions.append("Attach real search volume (GSC/API) to refine opportunity scoring.")

    return {
        "keyword": keyword,
        "opportunity_score": opportunity_score,
        "opportunity_level": level,
        "why": why[:8],
        "actions": actions[:8],
    }


def detect_cluster_opportunities(
    clusters: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    *,
    ranking_by_url: dict[str, float] | None = None,
    url_word_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """
    Site-level issues: high volume cluster without a strong URL, cannibalization, thin content vs demand.

    ``ranking_by_url``: URL → ranking_score (0–100) from audit.
    ``url_word_counts``: URL → word count for thin detection.
    """
    ranking_by_url = ranking_by_url or {}
    url_word_counts = url_word_counts or {}
    map_by_c = {str(m.get("cluster_id")): m for m in mappings}
    out: list[dict[str, Any]] = []

    for cl in clusters:
        cid = str(cl.get("cluster_id") or "")
        vol = int(cl.get("total_search_volume") or 0)
        m = map_by_c.get(cid) or {}
        url = str(m.get("target_url") or "")
        ms = float(m.get("match_score") or 0.0)
        rk = float(ranking_by_url.get(url) or 0.0) if url else 0.0
        wc = int(url_word_counts.get(url, 0))

        if vol >= 5000 and (not url or ms < 0.18 or rk < 38):
            out.append(
                {
                    "cluster_id": cid,
                    "issue_type": "high_volume_uncovered",
                    "opportunity_score": round(min(100.0, 40 + vol / 2500 + (1 - ms) * 30), 1),
                    "recommendation": "Create or strengthen one primary URL for this cluster; improve internal links from hubs.",
                }
            )

        if url and vol >= 8000 and wc > 0 and wc < 320 and rk < 55:
            out.append(
                {
                    "cluster_id": cid,
                    "issue_type": "thin_content_high_value_cluster",
                    "opportunity_score": round(min(100.0, 35 + vol / 3000 + (55 - rk) * 0.4), 1),
                    "recommendation": "Expand on-page depth (FAQ, examples) while preserving intent; align headings with cluster phrases.",
                }
            )

    # Cannibalization: same URL wins multiple high-volume clusters weakly
    url_hits: dict[str, list[tuple[str, float, int]]] = {}
    for cl in clusters:
        cid = str(cl.get("cluster_id") or "")
        m = map_by_c.get(cid) or {}
        u = str(m.get("target_url") or "")
        if not u:
            continue
        ms = float(m.get("match_score") or 0)
        vol = int(cl.get("total_search_volume") or 0)
        url_hits.setdefault(u, []).append((cid, ms, vol))

    for u, hits in url_hits.items():
        strong = [h for h in hits if h[1] >= 0.28 and h[2] >= 4000]
        if len(strong) >= 2:
            out.append(
                {
                    "cluster_id": ",".join(h[0] for h in strong[:4]),
                    "issue_type": "cannibalization_risk",
                    "opportunity_score": round(min(100.0, 32 + 6 * len(strong)), 1),
                    "recommendation": f"Multiple high-value clusters map to {u}; consolidate intent or differentiate pages.",
                }
            )

    out.sort(key=lambda r: -float(r.get("opportunity_score") or 0))
    return out[:50]
