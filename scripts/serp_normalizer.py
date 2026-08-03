"""
Normalize raw SERP collector payloads: canonical URLs, dedupe, domain clusters,
per-row SERP features + content type (SERP-derived, not query priors).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from app.services.serp_features import detect_serp_features
from app.services.serp_fetcher import normalize_serp_url
from app.services.serp_intent_classifier import _classify_one_result


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def normalize_ground_truth_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Input shape (collector): ``{query, timestamp, results: [{rank, url, title, snippet, features?}]}``.

    Output adds ``results`` with canonical URLs, ``domain_clusters``, ``serp_features`` (page-level),
    ``explain``.
    """
    q = str(raw.get("query") or "").strip()
    ts = str(raw.get("timestamp") or "")
    rows_in = list(raw.get("results") or [])

    by_url: dict[str, dict[str, Any]] = {}
    for r in rows_in:
        u = normalize_serp_url(str(r.get("url") or ""))
        if not u:
            continue
        rank = int(r.get("rank") or 9999)
        prev = by_url.get(u)
        if prev is None or rank < int(prev.get("rank") or 9999):
            by_url[u] = {
                "rank": rank,
                "url": u,
                "title": str(r.get("title") or "")[:300],
                "snippet": str(r.get("snippet") or "")[:500],
                "features": dict(r.get("features") or {}),
            }

    merged = sorted(by_url.values(), key=lambda x: int(x["rank"]))
    for i, row in enumerate(merged, start=1):
        row["rank"] = i

    serp_results = [{"url": x["url"], "title": x["title"], "snippet": x["snippet"]} for x in merged]
    serp_payload = {"serp_results": serp_results, "raw_api_extras": raw.get("raw_api_extras") or {}}
    page_features = detect_serp_features(serp_payload)

    domain_counts: Counter[str] = Counter()
    for row in merged:
        d = _domain(row["url"])
        if d:
            domain_counts[d] += 1

    out_rows: list[dict[str, Any]] = []
    for row in merged:
        one = _classify_one_result(row)
        row_features = dict(row.get("features") or {})
        row_features.setdefault("page_level", page_features)
        out_rows.append(
            {
                "rank": row["rank"],
                "url": row["url"],
                "title": row["title"],
                "snippet": row["snippet"],
                "features": row_features,
                "content_type": one.get("content_type"),
                "content_formats": one.get("content_formats"),
                "row_intent": one.get("intent"),
            }
        )

    total_urls = max(1, len(out_rows))
    domain_clusters = {d: round(c / total_urls, 4) for d, c in domain_counts.most_common(50)}

    return {
        "query": q,
        "timestamp": ts,
        "results": out_rows,
        "domain_clusters": domain_clusters,
        "serp_features": page_features,
        "explain": (
            "URLs canonicalized via normalize_serp_url; duplicates collapsed to best rank; "
            "domain_clusters are share of organic rows; row_intent/content_type from SERP row "
            "title/snippet/URL heuristics (serp_intent_classifier), not query-only priors."
        ),
    }


def jaccard_urls(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def duplication_rate(urls_a: list[str], urls_b: list[str]) -> float:
    """1 - Jaccard: higher means more disagreement between redundant fetches."""
    return round(1.0 - jaccard_urls(urls_a, urls_b), 4)
