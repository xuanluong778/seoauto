"""
Build a numeric feature vector for (query, URL) ranking attribution.

All features are scaled to ~[0, 1] where higher is better unless noted in ``explain``.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.search_intent import intent_similarity
from app.services.serp_fetcher import normalize_serp_url


FEATURE_ORDER: tuple[str, ...] = (
    "content_quality",
    "topical_authority",
    "entity_match",
    "intent_match",
    "internal_linking",
    "page_speed",
    "serp_alignment",
    "domain_authority_proxy",
    "trust_score",
    "indexability",
    "technical_health",
    "keyword_query_fit",
    "historical_momentum",
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _js_level_penalty(level: str) -> float:
    lv = (level or "low").lower()
    if lv == "high":
        return 0.25
    if lv == "medium":
        return 0.55
    return 1.0


def build_feature_vector(
    *,
    query: str,
    target_url: str,
    page_row: dict[str, Any],
    topical_row: dict[str, Any] | None = None,
    query_signals: dict[str, Any] | None = None,
    historical_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    ``page_row``: insight row from ``assemble_page_insight_row`` (``ranking``, ``decision``, …).

    ``topical_row``: one cluster row from topical authority report (authority_score, serp_intent, …).

    ``query_signals``: optional ``{ "dominant_query_intent": str }`` from query / GSC layer.

    ``historical_row``: optional slice from ``ranking_history_engine`` ``by_url`` entry.
    """
    rnk = dict(page_row.get("ranking") or {})
    dec = dict(page_row.get("decision") or {})
    rs = dict(dec.get("resolved_signals") or {})
    summ = dict(dec.get("summary") or {})
    gm = dict(rnk.get("graph_metrics") or {})
    cm = dict(rnk.get("content_metrics") or {})
    top = dict(topical_row or {})
    qs = dict(query_signals or {})

    ranking_score = float(rnk.get("ranking_score") or 0.0)
    content_quality = _clamp01(ranking_score / 100.0)

    auth01 = float(top.get("authority_score") or 0.0)
    if auth01 > 1.0:
        auth01 = auth01 / 100.0
    topical_authority = _clamp01(auth01)

    er = dict(top.get("entity_resolution") or {})
    groups = list(er.get("groups") or [])
    entity_match = _clamp01(min(1.0, len(groups) * 0.12 + 0.15))

    serp_int = str((top.get("serp_intent") or {}).get("serp_intent") or "")
    dom_page = str((top.get("intent_analysis") or {}).get("dominant_intent") or "")
    dom_q = str(qs.get("dominant_query_intent") or dom_page or "")
    intent_match = _clamp01(intent_similarity(serp_int or "informational", dom_q or dom_page or "informational"))

    in_deg = int(gm.get("in_degree") or 0)
    pr = float(gm.get("pagerank_score") or 0.0)
    internal_linking = _clamp01(0.45 * min(1.0, in_deg / 8.0) + 0.55 * min(1.0, pr / 0.08))

    js = str(rs.get("js_dependency_level") or "low").lower()
    page_speed = _clamp01(_js_level_penalty(js))

    serp_alignment = _clamp01(float(top.get("serp_alignment_score") or 0.5))

    domain_authority_proxy = _clamp01(min(1.0, pr / 0.06))

    tt = dict(top.get("topical_trust") or {})
    trust_score = _clamp01(float(tt.get("trust_score") or tt.get("topical_confidence_score") or 0.55))

    indexable = 1.0 if bool(rs.get("final_indexability", True)) else 0.0
    if dict(page_row.get("simulation") or {}).get("will_index") is False:
        indexable *= 0.35

    technical_health = _clamp01(float(summ.get("score") or 70.0) / 100.0)

    wc = int(cm.get("word_count") or 0)
    h = float(cm.get("heading_structure_score") or 0.0)
    keyword_query_fit = _clamp01(0.55 * min(1.0, wc / 2200.0) + 0.45 * h)

    hist = dict(historical_row or {})
    tr = str(hist.get("trend") or "stable").lower()
    if tr == "up":
        historical_momentum = 0.75
    elif tr == "down":
        historical_momentum = 0.35
    else:
        historical_momentum = 0.55
    if hist.get("volatility_score") is not None and float(hist.get("volatility_score") or 0) > 0.55:
        historical_momentum *= 0.85

    vec = {
        "content_quality": round(content_quality, 4),
        "topical_authority": round(topical_authority, 4),
        "entity_match": round(entity_match, 4),
        "intent_match": round(intent_match, 4),
        "internal_linking": round(internal_linking, 4),
        "page_speed": round(page_speed, 4),
        "serp_alignment": round(serp_alignment, 4),
        "domain_authority_proxy": round(domain_authority_proxy, 4),
        "trust_score": round(trust_score, 4),
        "indexability": round(indexable, 4),
        "technical_health": round(technical_health, 4),
        "keyword_query_fit": round(keyword_query_fit, 4),
        "historical_momentum": round(historical_momentum, 4),
    }

    missing: list[str] = []
    if not topical_row:
        missing.append("topical_row")
    if not str(page_row.get("url") or "").strip():
        missing.append("url")
    if not (cm.get("word_count") is not None):
        missing.append("word_count")

    return {
        "query": (query or "").strip(),
        "target_url": normalize_serp_url(str(target_url or "").strip()),
        "feature_vector": vec,
        "feature_order": list(FEATURE_ORDER),
        "missing_inputs": missing,
        "explain": (
            "Vector blends page ranking_score, graph_metrics (PageRank/in-degree), "
            "content_metrics, decision resolved_signals, topical authority row, and optional history."
        ),
    }


def vector_to_array(feature_vector: dict[str, Any], order: list[str] | None = None) -> list[float]:
    names = order or list(FEATURE_ORDER)
    fv = dict(feature_vector.get("feature_vector") or {})
    return [float(fv.get(k, 0.0)) for k in names]
