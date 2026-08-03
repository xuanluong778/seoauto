"""
Aggregate SERP competitor signals into a benchmark + domain cluster view.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.search_intent import classify_search_intent


def aggregate_serp_benchmark(
    content_rows: list[dict[str, Any]],
    *,
    keyword: str,
) -> dict[str, Any]:
    """``content_rows``: outputs of ``analyze_competitor_content`` merged with fetch row fields."""
    if not content_rows:
        return {
            "avg_word_count": 0,
            "avg_heading_score": 0.0,
            "avg_internal_links": 0.0,
            "avg_content_depth_score": 0.0,
            "avg_keyword_coverage": 0.0,
            "common_ngrams": [],
            "dominant_intent": "informational",
            "sample_size": 0,
        }

    n = len(content_rows)
    aw = sum(int(r.get("word_count") or 0) for r in content_rows) / n
    ah = sum(float(r.get("heading_structure_score") or 0) for r in content_rows) / n
    ai = sum(int(r.get("internal_link_count") or 0) for r in content_rows) / n
    ad = sum(float(r.get("content_depth_score") or 0) for r in content_rows) / n
    ak = sum(float(r.get("keyword_coverage") or 0) for r in content_rows) / n

    blob = " ".join(
        re.findall(
            r"[a-z]{3,}",
            " ".join(str(r.get("title") or "") for r in content_rows).lower(),
        )
    )
    words = blob.split()
    ng: Counter[str] = Counter()
    for i in range(len(words) - 1):
        bg = f"{words[i]} {words[i + 1]}"
        if len(bg) > 6:
            ng[bg] += 1
    common = [w for w, _ in ng.most_common(12)]

    agg_int = classify_search_intent(keyword)

    return {
        "avg_word_count": int(round(aw)),
        "avg_heading_score": round(ah, 3),
        "avg_internal_links": round(ai, 2),
        "avg_content_depth_score": round(ad, 3),
        "avg_keyword_coverage": round(ak, 3),
        "common_ngrams": common,
        "dominant_intent": agg_int["intent"],
        "dominant_intent_confidence": agg_int.get("confidence"),
        "sample_size": n,
    }


def competitor_cluster_view(competitor_fetch_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How domains split across fetched competitors."""
    doms: Counter[str] = Counter()
    for r in competitor_fetch_rows:
        from urllib.parse import urlparse

        u = str(r.get("url") or "")
        try:
            h = (urlparse(u).hostname or "").lower()
            if h.startswith("www."):
                h = h[4:]
            if h:
                doms[h] += 1
        except Exception:
            continue
    total = sum(doms.values()) or 1
    diversity = round(len(doms) / max(total, 1), 4)
    dominant = [{"domain": d, "url_count": c, "share": round(c / total, 3)} for d, c in doms.most_common(8)]
    opp = "high" if len(doms) >= 6 else "medium" if len(doms) >= 3 else "low"
    return {
        "dominant_domains": dominant,
        "diversity_score": diversity,
        "opportunity_level": opp,
        "unique_domains": len(doms),
    }
