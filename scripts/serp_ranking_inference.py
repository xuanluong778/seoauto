"""
Heuristic inference of which on-page signals correlate with winning this SERP.
"""

from __future__ import annotations

from typing import Any


def infer_ranking_factors(
    benchmark: dict[str, Any],
    content_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Correlation-style importance 0–1 from how much winners vary vs central tendency.

    ``content_rows``: per-competitor analyzed rows (word_count, heading_structure_score, ...).
    """
    if not content_rows:
        return {"dominant_factors": [], "explain": "No competitor samples."}

    n = len(content_rows)
    wcs = [int(r.get("word_count") or 0) for r in content_rows]
    hs = [float(r.get("heading_structure_score") or 0) for r in content_rows]
    ils = [int(r.get("internal_link_count") or 0) for r in content_rows]
    ds = [float(r.get("content_depth_score") or 0) for r in content_rows]

    def spread(vals: list[float]) -> float:
        if len(vals) < 2:
            return 0.0
        m = sum(vals) / len(vals)
        v = sum((x - m) ** 2 for x in vals) / len(vals)
        return (v**0.5) / max(m, 1e-6)

    sw = spread([float(x) for x in wcs])
    sh = spread(hs)
    sil = spread([float(x) for x in ils])
    sd = spread(ds)

    bw = float(benchmark.get("avg_word_count") or 0)
    importance = {
        "content_depth": min(0.95, 0.35 + 0.45 * sd + 0.12 * min(1.0, bw / 2500.0)),
        "heading_structure": min(0.9, 0.25 + 0.55 * sh + 0.1 * float(benchmark.get("avg_heading_score") or 0)),
        "internal_links": min(0.85, 0.2 + 0.5 * sil + 0.15 * min(1.0, float(benchmark.get("avg_internal_links") or 0) / 40.0)),
        "word_count": min(0.9, 0.22 + 0.5 * sw + 0.12 * min(1.0, bw / 2000.0)),
    }
    ranked = sorted(importance.items(), key=lambda x: -x[1])
    factors = [{"factor": k, "importance": round(v, 3)} for k, v in ranked]

    return {
        "dominant_factors": factors[:5],
        "explain": "Importance blends SERP central averages with cross-result variance (high variance ⇒ signal matters for separation).",
    }
