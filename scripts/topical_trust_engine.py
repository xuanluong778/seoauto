"""
Trust / confidence for topical scores: crawl quality, render reliability, SERP & embedding data.
"""

from __future__ import annotations

import os
from typing import Any


def compute_topical_trust(
    cluster_urls: list[str],
    *,
    pages_by_url: dict[str, dict[str, Any]],
    serp_results_count: int,
    embedding_used: bool,
) -> dict[str, Any]:
    """
    Lower ``topical_confidence_score`` when crawl data is weak — reduces false positives.
    """
    issues: list[str] = []
    cq_vals: list[float] = []
    trust_flags: list[str] = []

    for u in cluster_urls:
        p = pages_by_url.get(u) or {}
        cq = p.get("crawl_quality_score")
        if cq is not None:
            try:
                cq_vals.append(float(cq))
            except (TypeError, ValueError):
                pass
        dt = str(p.get("data_trust") or "").lower()
        if dt and dt not in ("high", "good"):
            trust_flags.append(f"data_trust:{u[:48]}")
        if p.get("skip_seo_analysis"):
            issues.append("Một số URL bị skip SEO analysis (crawl quality thấp).")
        if str(p.get("quality_level") or "").lower() in ("low", "poor"):
            issues.append("quality_level thấp trên một phần URL cluster.")

    crawl_quality_score = sum(cq_vals) / max(1, len(cq_vals)) if cq_vals else 0.72
    if not cq_vals:
        issues.append("Thiếu crawl_quality_score — dùng prior trung tính (giảm confidence).")
        crawl_quality_score = 0.62

    if crawl_quality_score < 0.45:
        issues.append("Low crawl quality — tín hiệu topical kém tin cậy hơn.")

    content_reliability = 0.78
    if trust_flags:
        content_reliability = max(0.35, 0.78 - 0.06 * min(5, len(trust_flags)))
        issues.append("Một phần URL có data_trust không cao.")

    serp_avail = min(1.0, serp_results_count / 8.0) if serp_results_count else 0.0
    if serp_results_count == 0:
        issues.append("Không có SERP snapshot — alignment chỉ heuristic.")

    emb_avail = 1.0 if embedding_used else 0.45
    if not embedding_used and os.getenv("TOPICAL_USE_EMBEDDINGS", "0").lower() not in ("1", "true", "yes"):
        pass  # optional message only if user expected embeddings
    elif not embedding_used:
        issues.append("Embedding không khả dụng cho pass này.")

    topical_confidence_score = round(
        0.38 * crawl_quality_score
        + 0.28 * content_reliability
        + 0.22 * (0.55 + 0.45 * serp_avail)
        + 0.12 * emb_avail,
        4,
    )
    topical_confidence_score = max(0.2, min(0.96, topical_confidence_score))

    if topical_confidence_score >= 0.72:
        trust_level = "high"
    elif topical_confidence_score >= 0.48:
        trust_level = "medium"
    else:
        trust_level = "low"

    # Down-weight SERP / entity signals when trust is low (propagation to downstream engines)
    t = topical_confidence_score
    weight_adjustment = {
        "serp_alignment": round(min(1.0, 0.55 + 0.55 * t), 3),
        "entity_signal": round(min(1.0, 0.52 + 0.48 * t), 3),
        "topical_composite": round(min(1.0, 0.45 + 0.55 * t), 3),
    }

    return {
        "topical_confidence_score": topical_confidence_score,
        "trust_score": topical_confidence_score,
        "trust_level": trust_level,
        "weight_adjustment": weight_adjustment,
        "trust_issues": issues[:10],
        "signals": {
            "crawl_quality_score": round(crawl_quality_score, 3),
            "content_reliability": round(content_reliability, 3),
            "serp_data_availability": round(serp_avail, 3),
            "embedding_availability": round(emb_avail, 3),
            "serp_results_used": serp_results_count,
        },
        "explain": "Weighted crawl quality, reliability flags, SERP coverage, embedding availability; weight_adjustment scales SERP/entity reliance.",
    }
