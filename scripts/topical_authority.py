"""
Cluster-level topical authority — depth, internal links, PageRank mass.
"""

from __future__ import annotations

import math
from typing import Any


def _log_coverage(size: int) -> float:
    return min(1.0, math.log1p(size) / math.log1p(24))


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_topical_authority(
    cluster: dict[str, Any],
    graph: dict[str, Any],
    ranking_data: dict[str, Any],
) -> dict[str, Any]:
    """
    ``cluster``: ``{ "topic_label", "pages", "cluster_size" }``
    ``graph``: internal link graph with ``nodes`` url -> { incoming, outgoing }
    ``ranking_data``: url -> { pagerank_score, word_count, content_depth, ... }

    Returns authority_score 0–100, authority_level, coverage_score, internal_linking_score.
    """
    pages = list(cluster.get("pages") or [])
    nodes = dict(graph.get("nodes") or {})
    size = max(1, len(pages))
    page_set = set(pages)

    pr_vals: list[float] = []
    depths: list[float] = []
    for u in pages:
        row = dict(ranking_data.get(u) or {})
        pr_vals.append(float(row.get("pagerank_score") or 0.0))
        wc = int(row.get("word_count") or 0)
        d = str(row.get("content_depth") or "thin")
        depth_score = 0.35 if d == "thin" else 0.65 if d == "normal" else 1.0
        depths.append(min(1.0, depth_score * min(1.0, wc / 1200.0)))

    pr_mass = _mean(pr_vals)
    depth_signal = _mean(depths)

    internal_edges = 0
    possible = max(0, size * (size - 1))
    for u in pages:
        node = nodes.get(u) or {}
        for v in node.get("outgoing") or []:
            if v in page_set and v != u:
                internal_edges += 1
    # normalize directed edge count (cap)
    link_density = internal_edges / max(1, min(possible, size * 6))
    internal_linking_score = min(1.0, link_density * 2.2 + internal_edges / max(8.0, size * 3.0))

    # coverage: more pages in cluster + not all thin
    coverage_score = min(1.0, _log_coverage(size) * 0.55 + depth_signal * 0.45)

    authority_raw = (
        22.0 * min(1.0, size / 12.0)
        + 28.0 * internal_linking_score
        + 28.0 * pr_mass
        + 22.0 * depth_signal
    )
    authority_score = max(0.0, min(100.0, round(authority_raw, 1)))

    if authority_score >= 68.0:
        level = "high"
    elif authority_score >= 38.0:
        level = "medium"
    else:
        level = "low"

    return {
        "authority_score": authority_score,
        "authority_level": level,
        "coverage_score": round(float(coverage_score), 3),
        "internal_linking_score": round(float(internal_linking_score), 3),
    }


def compute_topical_authority_composite(
    *,
    coverage_score: float,
    authority_flow_score: float,
    gap_score: float,
    content_depth_score: float,
    legacy_authority_0_100: float | None = None,
) -> dict[str, Any]:
    """
    Production-style topical authority 0–1 from multiple signals (not keyword density).

    ``gap_score``: higher = larger gap vs SERP / competitors → subtracts from authority.
    ``content_depth_score``: 0–1 from mean page depth in cluster.
    ``legacy_authority_0_100``: optional blend with classic cluster PageRank/link model.
    """
    cov = max(0.0, min(1.0, float(coverage_score)))
    flow = max(0.0, min(1.0, float(authority_flow_score)))
    gap = max(0.0, min(1.0, float(gap_score)))
    depth = max(0.0, min(1.0, float(content_depth_score)))
    serp_alignment = 1.0 - gap

    composite = 0.30 * cov + 0.20 * flow + 0.30 * serp_alignment + 0.20 * depth
    if legacy_authority_0_100 is not None:
        leg = max(0.0, min(1.0, float(legacy_authority_0_100) / 100.0))
        composite = 0.72 * composite + 0.28 * leg

    composite = round(max(0.0, min(1.0, composite)), 4)
    if composite >= 0.62:
        level = "high"
    elif composite >= 0.38:
        level = "medium"
    else:
        level = "low"

    # Confidence: penalize if gap unknown (0.5 neutral) and reward multi-page clusters
    conf = 0.55 + 0.15 * cov + 0.12 * flow + 0.1 * depth
    if gap == 0.5:
        conf -= 0.06
    conf = round(max(0.25, min(0.95, conf)), 3)

    authority_score_0_100 = round(composite * 100.0, 1)

    return {
        "topic": "",
        "authority_score": composite,
        "authority_score_0_100": authority_score_0_100,
        "authority_level": level,
        "confidence": conf,
        "components": {
            "coverage_weighted": round(0.30 * cov, 4),
            "authority_flow_weighted": round(0.20 * flow, 4),
            "serp_alignment_weighted": round(0.30 * serp_alignment, 4),
            "content_depth_weighted": round(0.20 * depth, 4),
        },
        "explain": "Weighted blend: coverage 30%, internal authority flow 20%, SERP alignment (1−gap) 30%, content depth 20%; optional 28% legacy graph authority.",
    }


def compute_topical_authority_v2(
    *,
    coverage_score: float,
    authority_flow_score: float,
    gap_score: float,
    serp_alignment_score: float,
    intent_consistency_score: float,
    entity_centrality_score: float,
    trust_score: float,
    legacy_authority_0_100: float | None = None,
) -> dict[str, Any]:
    """
    Topical Authority AI v2 — multi-signal, SERP- and intent-aware.

    Weights: coverage 25%, flow 15%, (1−gap) 20%, SERP alignment 15%,
    intent consistency 10%, entity centrality 10%, trust 5%.
    """
    def _cl(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    cov = _cl(coverage_score)
    flow = _cl(authority_flow_score)
    gap = _cl(gap_score)
    align = _cl(serp_alignment_score)
    intent_c = _cl(intent_consistency_score)
    cent = _cl(entity_centrality_score)
    trust = _cl(trust_score)

    gap_term = 1.0 - gap
    composite = (
        0.25 * cov
        + 0.15 * flow
        + 0.20 * gap_term
        + 0.15 * align
        + 0.10 * intent_c
        + 0.10 * cent
        + 0.05 * trust
    )
    if legacy_authority_0_100 is not None:
        leg = _cl(float(legacy_authority_0_100) / 100.0)
        composite = 0.68 * composite + 0.32 * leg

    composite = round(max(0.0, min(1.0, composite)), 4)
    if composite >= 0.62:
        level = "high"
    elif composite >= 0.38:
        level = "medium"
    else:
        level = "low"

    base_conf = (
        0.28
        + 0.14 * cov
        + 0.10 * flow
        + 0.12 * align
        + 0.10 * intent_c
        + 0.08 * cent
        + 0.06 * gap_term
    )
    conf = round(min(0.95, max(0.22, base_conf * (0.42 + 0.58 * trust))), 3)

    return {
        "topic": "",
        "authority_score": composite,
        "authority_score_0_100": round(composite * 100.0, 1),
        "authority_level": level,
        "confidence": conf,
        "components": {
            "coverage_25": round(0.25 * cov, 4),
            "authority_flow_15": round(0.15 * flow, 4),
            "serp_gap_inverse_20": round(0.20 * gap_term, 4),
            "serp_alignment_15": round(0.15 * align, 4),
            "intent_consistency_10": round(0.10 * intent_c, 4),
            "entity_centrality_10": round(0.10 * cent, 4),
            "trust_5": round(0.05 * trust, 4),
        },
        "explain": "v2: entity+intent+SERP+trust; gap enters as (1−gap); confidence scaled by trust signal.",
    }
