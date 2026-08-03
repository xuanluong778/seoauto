"""
Query-driven intent: GSC queries > keyword clusters > page content fallback.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from app.services.search_intent import classify_search_intent


def _gsc_query_text(row: dict[str, Any]) -> str:
    return str(row.get("query") or row.get("keyword") or row.get("keys") or "").strip()


def analyze_queries_intent(
    *,
    gsc_queries: list[dict[str, Any]] | None = None,
    cluster_keywords: list[dict[str, Any]] | None = None,
    fallback_text: str | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """
    Returns (per_query_rows, priority_source, cluster_intent_summary).

    ``cluster_keywords``: list of ``{"keyword": "..."}`` or raw strings from cluster.
    """
    out: list[dict[str, Any]] = []
    priority = "content"

    if gsc_queries:
        priority = "gsc"
        for row in gsc_queries[:80]:
            q = _gsc_query_text(row)
            if len(q) < 2:
                continue
            pkg = classify_search_intent(q)
            out.append(
                {
                    "query": q,
                    "intent": str(pkg.get("intent") or "informational"),
                    "confidence": float(pkg.get("confidence") or 0.5),
                }
            )
    elif cluster_keywords:
        priority = "clusters"
        for row in cluster_keywords[:80]:
            if isinstance(row, str):
                q = row.strip()
            else:
                q = str(row.get("keyword") or row.get("query") or "").strip()
            if len(q) < 2:
                continue
            pkg = classify_search_intent(q)
            out.append(
                {
                    "query": q,
                    "intent": str(pkg.get("intent") or "informational"),
                    "confidence": float(pkg.get("confidence") or 0.5),
                }
            )

    if not out and (fallback_text or "").strip():
        priority = "content"
        pkg = classify_search_intent(fallback_text[:240])
        out.append(
            {
                "query": (fallback_text or "")[:120],
                "intent": str(pkg.get("intent") or "informational"),
                "confidence": float(pkg.get("confidence") or 0.45),
            }
        )

    dist: Counter[str] = Counter()
    wsum: dict[str, float] = {}
    for row in out:
        it = str(row.get("intent") or "informational")
        c = float(row.get("confidence") or 0.5)
        dist[it] += 1
        wsum[it] = wsum.get(it, 0.0) + c

    total = sum(dist.values()) or 1
    dist_n = {k: round(v / total, 4) for k, v in dist.items()}
    dominant = max(dist_n, key=lambda k: dist_n[k]) if dist_n else "informational"
    vals_sorted = sorted(dist_n.values(), reverse=True)
    top_two = vals_sorted[:2] if vals_sorted else [1.0]
    intent_conflict = bool(
        len(top_two) >= 2 and top_two[0] < 0.52 and top_two[1] >= 0.22 and (top_two[0] - top_two[1]) < 0.18
    )

    cluster_summary = {
        "dominant_intent": dominant,
        "intent_distribution": dist_n,
        "intent_conflict": intent_conflict,
        "query_count": len(out),
        "priority_source": priority,
        "explain": "GSC > cluster keywords > page text; conflict when top intents nearly tied.",
    }
    return out, priority, cluster_summary


def build_cluster_query_intent(
    *,
    gsc_queries: list[dict[str, Any]] | None,
    cluster_keyword_rows: list[dict[str, Any]] | None,
    fallback_topic_label: str,
) -> dict[str, Any]:
    """Single cluster / site slice entry point."""
    rows, _prio, summary = analyze_queries_intent(
        gsc_queries=gsc_queries,
        cluster_keywords=cluster_keyword_rows,
        fallback_text=fallback_topic_label,
    )
    return {"queries": rows[:40], **summary}
