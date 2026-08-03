"""
Page vs cluster topical alignment — keyword overlap with cluster centroid label.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _page_tokens(page: dict[str, Any]) -> Counter[str]:
    primary = str(page.get("primary_topic") or "").strip().lower()
    secs = [str(x).strip().lower() for x in (page.get("secondary_topics") or [])]
    kws = [str(x).strip().lower() for x in (page.get("keywords") or [])]
    c: Counter[str] = Counter()
    if primary and primary != "unknown":
        c[primary] += 5
    for s in secs[:10]:
        if s:
            c[s] += 2
    for k in kws[:60]:
        if k:
            c[k] += 1
    return c


def compute_page_topic_relevance(page: dict[str, Any], cluster: dict[str, Any]) -> dict[str, Any]:
    """
    ``page``: topic extraction dict (+ optional ``url``).
    ``cluster``: ``topic_label``, ``pages``, ``cluster_size``.
    """
    label = str(cluster.get("topic_label") or "").strip().lower()
    bag = _page_tokens(page)
    if not label or label == "mixed" or label == "unknown":
        # weak centroid — use overlap with union of secondaries only
        overlap = 0.35
    else:
        overlap = min(1.0, float(bag.get(label, 0)) / max(3.0, sum(bag.values()) * 0.25 + 0.01))

    primary = str(page.get("primary_topic") or "").strip().lower()
    topic_alignment = bool(primary and primary == label)

    if topic_alignment:
        base = 0.72
    else:
        base = 0.28 + 0.55 * overlap

    conf = float(page.get("topic_confidence") or 0.0)
    relevance_score = max(0.0, min(1.0, round(base * 0.82 + conf * 0.18, 3)))

    if relevance_score >= 0.62:
        rel_level = "high"
    elif relevance_score >= 0.38:
        rel_level = "medium"
    else:
        rel_level = "low"

    return {
        "relevance_score": relevance_score,
        "relevance_level": rel_level,
        "topic_alignment": topic_alignment,
    }
