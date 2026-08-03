"""
Site-level SEO strategy synthesis (roadmap + linking + cluster expansion).
"""

from __future__ import annotations

from typing import Any


def build_seo_strategy_ai_site(
    *,
    topical_authority: list[dict[str, Any]],
    ranking_decision: dict[str, Any],
    keyword_intelligence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Aggregate actions from topical v2 + ranking gaps + keyword opportunities."""
    next_actions: list[str] = []
    roadmap: list[str] = []
    linking: list[str] = []
    expansion: list[str] = []

    for row in topical_authority or []:
        for a in row.get("actions") or []:
            if isinstance(a, str) and a.strip() and a not in next_actions:
                next_actions.append(a)
        t = str(row.get("topic") or "")
        if t and str(row.get("cluster_health") or "") == "weak":
            roadmap.append(f"Pillar refresh + 4–6 supporting URLs cho cluster «{t}».")

    rd = dict(ranking_decision or {})
    if not rd.get("will_rank"):
        for r in rd.get("primary_reasons") or []:
            if r not in next_actions:
                next_actions.append(f"Ranking: {r}")

    kw = keyword_intelligence or {}
    for op in (kw.get("opportunities") or [])[:8]:
        cid = str(op.get("cluster_id") or "").strip()
        it = str(op.get("issue_type") or "").strip()
        rec = str(op.get("recommendation") or "").strip()
        if cid or it:
            expansion.append(f"Cluster {cid or '?'} — {it or 'opportunity'}: {rec[:100]}")

    if topical_authority:
        linking.append("Tạo hub nội bộ: mỗi cluster mạnh 1 URL pillar nhận anchor từ 80% URL cùng cluster.")
        linking.append("Bổ sung contextual links từ category/menu tới orphan trong topical health.")

    if not roadmap:
        roadmap.append("Duy trì editorial calendar theo topical_authority mean score; ưu tiên cluster có gap SERP cao.")

    return {
        "next_actions": next_actions[:20],
        "content_roadmap": roadmap[:12],
        "internal_linking_plan": linking[:10],
        "cluster_expansion_plan": expansion[:12],
        "explain": "Merged topical actions, ranking_decision v3 reasons, keyword opportunities, and internal link heuristics.",
    }
