"""
Làm giàu cluster cho content planning: main/supporting keywords, SERP type, gợi ý dạng nội dung.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _row_search_volume(r: dict[str, Any]) -> int:
    sv = r.get("search_volume")
    if isinstance(sv, dict):
        return int(sv.get("avg_monthly") or 0)
    try:
        return int(sv or 0)
    except (TypeError, ValueError):
        return 0


def _aggregate_serp_page_types(mem_rows: list[dict[str, Any]]) -> dict[str, Any]:
    type_ctr: Counter[str] = Counter()
    for r in mem_rows:
        sig = r.get("serp_layout_intent")
        if not isinstance(sig, dict):
            continue
        for pt in sig.get("page_types") or []:
            if pt:
                type_ctr[str(pt)] += 1
    if not type_ctr:
        return {"primary_serp_page_type": None, "serp_page_type_mix": {}, "serp_page_types_top": []}
    top = type_ctr.most_common(5)
    primary = top[0][0]
    total = sum(type_ctr.values()) or 1
    mix = {k: round(c / total, 4) for k, c in top}
    return {
        "primary_serp_page_type": primary,
        "serp_page_type_mix": mix,
        "serp_page_types_top": [{"page_type": k, "share": round(v / total, 4)} for k, v in top],
    }


def suggested_content_type(*, cluster_intent: str, primary_serp_page_type: str | None) -> str:
    """Gợi ý định dạng nội dung chính (không thay thế brief chi tiết)."""
    it = (cluster_intent or "informational").lower()
    pt = (primary_serp_page_type or "").lower()
    if it == "mixed_intent":
        return "pillar_or_hub_page"
    if pt in ("product",):
        return "product_or_collection_landing" if it == "transactional" else "comparison_buying_guide"
    if pt in ("category", "directory"):
        return "category_hub_or_buyers_guide"
    if pt in ("blog", "article", "news", "docs"):
        return "long_form_article_or_guide"
    if pt == "video":
        return "video_script_or_embedded_article"
    if pt in ("forum",):
        return "community_faq_or_ugc_summary"
    if it == "transactional":
        return "conversion_focused_landing"
    if it == "commercial":
        return "comparison_or_roundup"
    if it == "navigational":
        return "brand_or_resource_hub"
    return "informational_article"


def enrich_hybrid_cluster_for_planning(cluster: dict[str, Any]) -> dict[str, Any]:
    """
    Thêm field phục vụ lập kế hoạch (giữ nguyên ``keywords`` list dict gốc — đã sort volume trong clusterer).
    """
    mem = list(cluster.get("keywords") or [])
    if not mem:
        cluster.setdefault("supporting_keywords", [])
        cluster.setdefault("keywords_prioritized", [])
        cluster.setdefault("suggested_content_type", suggested_content_type(cluster_intent=str(cluster.get("intent") or ""), primary_serp_page_type=None))
        return cluster

    prioritized: list[dict[str, Any]] = []
    for idx, r in enumerate(mem):
        prioritized.append(
            {
                "keyword": str(r.get("keyword") or ""),
                "priority_rank": idx + 1,
                "search_volume": _row_search_volume(r),
                "intent_cluster": str(r.get("intent_cluster") or r.get("intent") or ""),
                "intent_confidence": float(r.get("intent_confidence") or 0.0),
            }
        )
    main_kw = str(mem[0].get("keyword") or cluster.get("cluster_name") or "")
    supporting = [str(r.get("keyword") or "") for r in mem[1:] if r.get("keyword")]
    serp_agg = _aggregate_serp_page_types(mem)
    ctype = suggested_content_type(
        cluster_intent=str(cluster.get("intent") or "informational"),
        primary_serp_page_type=serp_agg.get("primary_serp_page_type"),
    )
    cluster["main_keyword"] = main_kw
    cluster["supporting_keywords"] = supporting
    cluster["keywords_prioritized"] = prioritized
    cluster["serp_page_type_summary"] = serp_agg
    cluster["primary_serp_page_type"] = serp_agg.get("primary_serp_page_type")
    cluster["suggested_content_type"] = ctype
    return cluster


def enrich_tfidf_cluster_for_planning(cluster: dict[str, Any], *, kw_rows_by_lower: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """TF‑IDF cluster (keywords là list string): bổ sung cấu trúc gần giống hybrid."""
    kws = [str(x).strip() for x in (cluster.get("keywords") or []) if str(x).strip()]
    if not kws:
        return cluster
    rows: list[dict[str, Any]] = []
    by = kw_rows_by_lower or {}
    for k in kws:
        r = by.get(k.lower(), {"keyword": k, "search_volume": 0, "intent": cluster.get("intent")})
        rows.append(dict(r))
    rows.sort(key=lambda x: -_row_search_volume(x))
    tmp = {
        "keywords": rows,
        "intent": cluster.get("intent"),
        "cluster_name": cluster.get("cluster_name"),
    }
    enrich_hybrid_cluster_for_planning(tmp)
    cluster["main_keyword"] = tmp.get("main_keyword") or kws[0]
    cluster["supporting_keywords"] = tmp.get("supporting_keywords", kws[1:])
    cluster["keywords_prioritized"] = tmp.get("keywords_prioritized", [])
    cluster["serp_page_type_summary"] = {"primary_serp_page_type": None, "serp_page_type_mix": {}, "note": "tfidf_mode_no_serp_layout"}
    cluster["primary_serp_page_type"] = None
    cluster["suggested_content_type"] = tmp.get("suggested_content_type") or suggested_content_type(
        cluster_intent=str(cluster.get("intent") or "informational"),
        primary_serp_page_type=None,
    )
    return cluster
