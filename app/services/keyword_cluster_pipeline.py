"""
Cluster keywords: SERP-grounded hybrid (existing clusterer) → simplified API objects.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.services.cluster_content_map import build_content_map_summary, build_content_plans_from_clusters, enrich_cluster_for_content_map
from app.services.intent_classifier import classify_keywords_batch
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_intelligence import guess_brand_terms

_REAL_VOLUME_SOURCES = frozenset({"api", "dataforseo", "api_cache", "google_ads"})


def _volume_for_map(row: dict[str, Any]) -> int | None:
    src = str(row.get("volume_source") or "").lower()
    if src not in _REAL_VOLUME_SOURCES:
        return None
    try:
        v = int(row.get("search_volume") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _cluster_entity_from_raw(c: dict[str, Any], idx: int, *, input_count: int) -> dict[str, Any]:
    """Legacy shim — delegates to Content Map enricher."""
    return enrich_cluster_for_content_map(c, idx=idx, input_keyword_count=input_count)


def build_keyword_cluster_api_response(
    keywords: list[str],
    *,
    fetch_serp: bool = True,
    brand_host_hint: str | None = None,
    serp_country: str | None = None,
    serp_language: str | None = None,
    serp_device: str | None = None,
    cluster_strictness: str | None = None,
    progress_hook: callable | None = None,
) -> dict[str, Any]:
    """
    ``keywords``: raw strings (from research or CSV). Deduplicated; capped for CPU/SERP cost.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for k in keywords or []:
        s = str(k or "").strip()
        if len(s) < 2 or len(s) > 200:
            continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        cleaned.append(s)

    max_in = int(os.getenv("KEYWORD_CLUSTER_MAX_INPUT", "500"))
    truncated = False
    if max_in > 0:
        truncated = len(cleaned) > max_in
        if truncated:
            cleaned = cleaned[:max_in]

    if not cleaned:
        return {"clusters": [], "meta": {"error": "no_keywords", "truncated": False}}

    records = [{"keyword": k, "source": "api_input"} for k in cleaned]
    host = urlparse(brand_host_hint or "").hostname or (brand_host_hint or "")
    brand = guess_brand_terms(f"https://{host}" if host else "https://example.com")

    clusters_raw = build_keyword_clusters(
        records,
        brand_terms=brand,
        fetch_serp=fetch_serp,
        serp_country=serp_country,
        serp_language=serp_language,
        serp_device=serp_device,
        cluster_strictness=cluster_strictness,
        progress_hook=progress_hook,
    )

    if progress_hook:
        progress_hook(93, "Đang tổng hợp kết quả…")

    volumes: dict[str, int] = {}
    for c in clusters_raw or []:
        for r in (c.get("keywords") or []):
            if not isinstance(r, dict):
                continue
            kw = str(r.get("keyword") or "").strip()
            if not kw:
                continue
            v = _volume_for_map(r)
            if v is not None:
                volumes[kw] = v
    volume_sum = int(sum(volumes.values())) if volumes else None

    skip_reclass = os.getenv("KEYWORD_CLUSTER_SKIP_INTENT_RECLASS", "1").lower() in ("1", "true", "yes")
    main_phrases = [str(c.get("main_keyword") or c.get("cluster_name") or "") for c in clusters_raw]
    main_phrases = [p for p in main_phrases if p]
    if main_phrases and not skip_reclass:
        if progress_hook:
            progress_hook(96, "Đang phân loại intent…")
        hits = classify_keywords_batch(main_phrases, brand_terms=brand, max_serp_gt=min(20, len(main_phrases)))
        by_m = {str(r.get("keyword") or "").lower(): r for r in hits}
        for c in clusters_raw:
            mk = str(c.get("main_keyword") or "").lower()
            if mk in by_m:
                c["intent"] = str(by_m[mk].get("intent") or c.get("intent"))
                c["intent_source"] = by_m[mk].get("source")

    clusters: list[dict[str, Any]] = [
        _cluster_entity_from_raw(c, i, input_count=len(cleaned)) for i, c in enumerate(clusters_raw)
    ]

    if progress_hook:
        progress_hook(100, "Hoàn tất")

    summary = build_content_map_summary(clusters)
    content_plans = build_content_plans_from_clusters(clusters)

    return {
        "clusters": clusters,
        "content_plans": content_plans,
        "volumes": volumes,
        "content_map_summary": summary,
        "meta": {
            "entity": "cluster",
            "input_count": len(seen),
            "cluster_count": len(clusters),
            "truncated": truncated,
            "max_input": max_in,
            "fetch_serp": fetch_serp,
            "search_volume_sum": volume_sum,
            "deduplicated_keyword_count": len(volumes),
            "serp_locale": {
                "country": serp_country or "",
                "language": serp_language or "",
                "device": serp_device or "",
            },
            "cluster_strictness": cluster_strictness or os.getenv("KEYWORD_CLUSTER_STRICTNESS", "normal"),
            "clustering_method": "serp_shared_url_count" if fetch_serp else "semantic_fallback_same_intent_topic",
            "min_shared_urls_for_merge": int(os.getenv("KEYWORD_CLUSTER_SERP_MIN_SHARED_URLS", "3")),
        },
    }
