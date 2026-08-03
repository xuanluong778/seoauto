"""
Topic cluster coverage: pages, depth, entity diversity, lexical/subtopic signals.
"""

from __future__ import annotations

import math
from typing import Any


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def compute_topic_cluster_coverage(
    cluster: dict[str, Any],
    *,
    pages_topics_by_url: dict[str, dict[str, Any]],
    ranking_data: dict[str, dict[str, Any]],
    cluster_graph: dict[str, Any] | None = None,
    serp_entity_hints: list[str] | None = None,
) -> dict[str, Any]:
    """
    ``cluster``: ``topic_label``, ``pages``, ``cluster_size``.
    ``cluster_graph``: merged ``extract_topic_graph`` output for cluster URLs (optional).
    ``serp_entity_hints``: n-grams / entities from SERP titles/snippets (optional).
    """
    label = str(cluster.get("topic_label") or "mixed")
    urls = list(cluster.get("pages") or [])
    n_pages = len(urls)
    if n_pages == 0:
        return {
            "topic": label,
            "coverage_score": 0.0,
            "coverage_level": "low",
            "missing_subtopics": [],
            "explain": "empty_cluster",
        }

    wcs: list[int] = []
    kw_union: set[str] = set()
    secondary_union: set[str] = set()
    for u in urls:
        row = dict(ranking_data.get(u) or {})
        wcs.append(int(row.get("word_count") or 0))
        pt = pages_topics_by_url.get(u) or {}
        for k in pt.get("keywords") or []:
            if isinstance(k, str) and len(k) > 2:
                kw_union.add(k.lower())
        for s in pt.get("secondary_topics") or []:
            if isinstance(s, str) and len(s) > 2:
                secondary_union.add(s.lower())

    avg_wc = _mean([float(x) for x in wcs])
    depth_norm = min(1.0, math.log1p(avg_wc) / math.log1p(2200))

    graph_nodes = list((cluster_graph or {}).get("nodes") or [])
    entity_topics = {str(n.get("topic") or "").lower() for n in graph_nodes if n.get("topic")}
    entity_diversity = min(1.0, len(entity_topics) / max(12.0, 4.0 + n_pages * 1.8))

    # Keyword coverage: breadth of vocabulary vs cluster size (not density)
    kw_breadth = min(1.0, len(kw_union) / max(24.0, 10.0 + n_pages * 14.0))

    # Subtopics: secondary headings/topics represented
    sub_cov = min(1.0, len(secondary_union) / max(6.0, 2.0 + n_pages * 2.5))

    coverage_raw = (
        0.22 * min(1.0, math.log1p(n_pages) / math.log1p(14))
        + 0.28 * depth_norm
        + 0.22 * entity_diversity
        + 0.16 * kw_breadth
        + 0.12 * sub_cov
    )
    coverage_score = round(max(0.0, min(1.0, coverage_raw)), 4)

    missing_subtopics: list[str] = []
    if serp_entity_hints:
        have = entity_topics | kw_union | secondary_union
        for hint in serp_entity_hints[:40]:
            h = hint.strip().lower()
            if len(h) < 4:
                continue
            if h not in have and not any(h in x or x in h for x in have if len(x) > 3):
                missing_subtopics.append(h)
        missing_subtopics = missing_subtopics[:12]

    if not missing_subtopics and graph_nodes:
        # suggest expanding on mid-tier entities not reinforced by many edges
        low_imp = [str(n["topic"]) for n in graph_nodes[12:22] if float(n.get("importance") or 0) < 0.35]
        missing_subtopics = low_imp[:6]

    if coverage_score >= 0.62:
        level = "high"
    elif coverage_score >= 0.38:
        level = "medium"
    else:
        level = "low"

    return {
        "topic": label,
        "number_of_pages": n_pages,
        "avg_word_count": int(round(avg_wc)),
        "entity_diversity": round(entity_diversity, 4),
        "keyword_coverage_breadth": round(kw_breadth, 4),
        "subtopic_coverage": round(sub_cov, 4),
        "coverage_score": coverage_score,
        "coverage_level": level,
        "missing_subtopics": missing_subtopics,
        "explain": "Combines page count, avg depth, merged entity graph diversity, and heading-derived subtopics.",
    }
