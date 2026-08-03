"""
SERP competitor authority heuristics: internal PageRank when URL is in crawl, else domain + depth proxy.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse


def _path_depth(url: str) -> int:
    try:
        p = urlparse(url).path.strip("/")
        if not p:
            return 0
        return len([x for x in p.split("/") if x])
    except Exception:
        return 1


def _title_quality_score(title: str, keyword: str) -> float:
    t = (title or "").strip().lower()
    if not t:
        return 0.15
    score = 0.35
    if 25 <= len(t) <= 72:
        score += 0.25
    elif len(t) > 72:
        score += 0.1
    kws = [w for w in re.findall(r"[a-z0-9]{3,}", (keyword or "").lower()) if len(w) > 2]
    for w in kws[:4]:
        if w in t:
            score += 0.12
    return max(0.0, min(1.0, round(score, 3)))


def _external_authority_proxy(
    domain: str,
    domain_counts: Counter[str],
    depth: int,
    title_score: float,
) -> float:
    """0–1 proxy when URL not in internal graph."""
    freq = domain_counts.get(domain, 1)
    dom_boost = min(0.45, 0.08 * math.log1p(freq))
    depth_penalty = min(0.35, depth * 0.07)
    base = 0.22 + dom_boost - depth_penalty
    base += 0.18 * title_score
    return max(0.05, min(0.95, round(base, 3)))


def analyze_serp_competitors(
    serp_results: list[dict[str, Any]],
    crawl_data: dict[str, Any] | None,
    *,
    keyword: str = "",
) -> dict[str, Any]:
    """
    ``crawl_data``: ``url`` -> ``{ "pagerank_score": float, "word_count": int, ... }`` for pages you crawled.

    Returns aggregate authority stats and per-row ``estimated_authority`` on copies of results.
    """
    crawl_data = crawl_data or {}
    domain_counts: Counter[str] = Counter()
    for r in serp_results:
        d = str(r.get("domain") or "").strip().lower()
        if d:
            domain_counts[d] += 1

    authorities: list[float] = []
    enriched: list[dict[str, Any]] = []
    weak = 0

    for r in serp_results:
        row = dict(r)
        url = str(row.get("url") or "").strip()
        domain = str(row.get("domain") or "").strip().lower()
        title = str(row.get("title") or "")
        depth = _path_depth(url)
        tq = _title_quality_score(title, keyword)

        internal = crawl_data.get(url) or crawl_data.get(url.rstrip("/"))
        if isinstance(internal, dict) and internal.get("pagerank_score") is not None:
            auth = float(internal["pagerank_score"])
            row["authority_source"] = "internal_pagerank"
            wc = int(internal.get("word_count") or 0)
            if wc < 350:
                auth *= 0.92
                weak += 1
        else:
            auth = _external_authority_proxy(domain, domain_counts, depth, tq)
            row["authority_source"] = "serp_heuristic"
            if auth < 0.28 and tq < 0.45:
                weak += 1

        row["estimated_authority"] = round(auth, 4)
        row["title_quality_score"] = tq
        row["path_depth"] = depth
        authorities.append(auth)
        enriched.append(row)

    if not authorities:
        return {
            "avg_authority": 0.0,
            "max_authority": 0.0,
            "authority_distribution": {"p50": 0.0, "p90": 0.0},
            "weak_pages_count": 0,
            "competitors": [],
        }

    authorities.sort()
    mid = len(authorities) // 2
    p50 = authorities[mid]
    p90 = authorities[int(max(0, len(authorities) * 0.9 - 1))]

    return {
        "avg_authority": round(sum(authorities) / len(authorities), 4),
        "max_authority": round(max(authorities), 4),
        "authority_distribution": {"p50": round(p50, 4), "p90": round(p90, 4)},
        "weak_pages_count": int(weak),
        "competitors": enriched,
    }
