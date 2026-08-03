"""
Cluster keywords: SERP-grounded hybrid (existing clusterer) → simplified API objects.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.services.intent_classifier import classify_keywords_batch
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_intelligence import guess_brand_terms


def _cluster_entity_from_raw(c: dict[str, Any], idx: int) -> dict[str, Any]:
    seen: set[str] = set()
    variations: list[str] = []
    for x in (c.get("keywords") or []):
        kw = str(x.get("keyword") if isinstance(x, dict) else x or "").strip()
        if not kw:
            continue
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        variations.append(kw)
    primary = str(c.get("main_keyword") or c.get("cluster_name") or (variations[0] if variations else "")).strip()
    if primary and primary.lower() not in seen:
        variations.insert(0, primary)
    total_volume = int(c.get("total_search_volume") or 0)
    return {
        "cluster_id": f"cluster_{idx + 1}",
        "primary_keyword": primary,
        "variations": variations,
        "total_volume": total_volume,
        "cluster_size": int(c.get("cluster_size") or len(variations)),
        "intent": str(c.get("intent") or "informational"),
        "cohesion_score": c.get("cohesion_score"),
        "serp_overlap_score": float(c.get("serp_overlap_score") or 0.0),
        "detail": {
            "intent_source": c.get("intent_source"),
            "serp_data_available": bool((c.get("explain") or {}).get("serp_data_available", True))
            if isinstance(c.get("explain"), dict)
            else True,
            "explain": c.get("explain") if isinstance(c.get("explain"), dict) else {},
        },
    }


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

    # KEYWORD_CLUSTER_MAX_INPUT:
    # - > 0: cap input list to that size (safety)
    # - 0 or < 0: no cap (may be very slow for large N due to O(N^2) matrices)
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

    # Build a volume map from enriched keyword rows inside clusters_raw so the UI can
    # render chart/tables without extra round-trips.
    volumes: dict[str, int] = {}
    for c in clusters_raw or []:
        for r in (c.get("keywords") or []):
            if not isinstance(r, dict):
                continue
            kw = str(r.get("keyword") or "").strip()
            if not kw:
                continue
            try:
                volumes[kw] = int(r.get("search_volume") or 0)
            except Exception:
                volumes[kw] = 0
    volume_sum = int(sum(int(v or 0) for v in volumes.values()))

    # Re-classify cluster intent from SERP GT on main keyword when few members
    main_phrases = [str(c.get("main_keyword") or c.get("cluster_name") or "") for c in clusters_raw]
    main_phrases = [p for p in main_phrases if p]
    if main_phrases:
        hits = classify_keywords_batch(main_phrases, brand_terms=brand, max_serp_gt=min(20, len(main_phrases)))
        by_m = {str(r.get("keyword") or "").lower(): r for r in hits}
        for c in clusters_raw:
            mk = str(c.get("main_keyword") or "").lower()
            if mk in by_m:
                c["intent"] = str(by_m[mk].get("intent") or c.get("intent"))
                c["intent_source"] = by_m[mk].get("source")

    clusters: list[dict[str, Any]] = [_cluster_entity_from_raw(c, i) for i, c in enumerate(clusters_raw)]

    return {
        "clusters": clusters,
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
            "serp_overlap_note": "Pairwise SERP overlap (weighted URL + domain) + semantic + intent gate; cache key = serp_cache_digest on snapshots.",
            "cluster_strictness": cluster_strictness or os.getenv("KEYWORD_CLUSTER_STRICTNESS", "normal"),
        },
    }
