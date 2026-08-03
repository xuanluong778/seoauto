"""
Cluster-level search intent distribution and consistency (SERP truth should align later).
"""

from __future__ import annotations

import math
from typing import Any

from app.services.search_intent import classify_search_intent


def _entropy_norm(counts: dict[str, float]) -> float:
    """0 = single intent, ~1 = uniform mix."""
    vals = [max(1e-9, float(v)) for v in counts.values()]
    s = sum(vals)
    if s <= 0:
        return 0.0
    probs = [v / s for v in vals]
    h = -sum(p * math.log(p + 1e-12) for p in probs)
    h_max = math.log(len(probs) + 1e-12) if probs else 1.0
    return h / h_max if h_max > 0 else 0.0


def analyze_cluster_intent(
    cluster: dict[str, Any],
    *,
    topics_by_url: dict[str, dict[str, Any]],
    topic_label: str,
    brand_terms: set[str] | None = None,
) -> dict[str, Any]:
    """
    Aggregate intent from each page proxy (primary_topic + keywords → synthetic query).
    """
    urls = list(cluster.get("pages") or [])
    dist = {"informational": 0.0, "navigational": 0.0, "transactional": 0.0, "commercial": 0.0}
    if not urls:
        return {
            "dominant_intent": "informational",
            "intent_distribution": dist,
            "intent_consistency_score": 0.35,
            "explain": "empty_cluster",
        }

    for u in urls:
        row = topics_by_url.get(u) or {}
        primary = str(row.get("primary_topic") or "").strip()
        kws = row.get("keywords") or []
        tail = " ".join(str(x) for x in (kws[:8] if isinstance(kws, list) else []) if str(x).strip())
        pseudo_query = f"{topic_label} {primary} {tail}".strip()[:240]
        if len(pseudo_query) < 4:
            pseudo_query = topic_label or primary or "content"
        pkg = classify_search_intent(pseudo_query, brand_terms=brand_terms or set())
        intent = str(pkg.get("intent") or "informational")
        if intent not in dist:
            intent = "informational"
        dist[intent] += float(pkg.get("confidence") or 0.5)

    s = sum(dist.values()) or 1.0
    dist_n = {k: round(v / s, 4) for k, v in dist.items()}
    dominant = max(dist_n, key=lambda k: dist_n[k])

    mix = _entropy_norm(dist_n)
    # High mix → lower consistency; informational+commercial overlap is mild penalty
    info_comm = dist_n.get("informational", 0) + dist_n.get("commercial", 0)
    trans = dist_n.get("transactional", 0)
    info = dist_n.get("informational", 0)

    consistency = 1.0 - 0.55 * mix
    if trans >= 0.35 and info >= 0.35 and dominant != "navigational":
        consistency -= 0.12  # transactional vs informational tension
    if dist_n.get("commercial", 0) >= 0.45 and dist_n.get("informational", 0) >= 0.45:
        consistency += 0.04  # allowed overlap
    consistency = round(max(0.15, min(1.0, consistency)), 4)

    return {
        "dominant_intent": dominant,
        "intent_distribution": dist_n,
        "intent_consistency_score": consistency,
        "explain": "Per-URL pseudo-query from topic tokens + classify_search_intent; entropy penalizes mixed intent.",
    }
