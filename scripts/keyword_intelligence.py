"""
Orchestrate keyword collection → clustering → URL mapping → coverage metrics.

When ``KEYWORD_INTEL_DEFAULT`` / ``enable_keyword_intelligence`` is on and
``KEYWORD_SERP_INTEL=1``, clusters receive ``serp_analysis`` from
:mod:`app.services.serp_intelligence` (SERP snapshot, benchmarks, gaps, strategy).

Designed for audit-time batching; for millions of keywords, shard by site and
lower ``KEYWORD_CLUSTER_MAX_FEATURES`` / raise ``KEYWORD_CLUSTER_COSINE_THRESHOLD``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from app.services.keyword_clusterer import cluster_keywords
from app.services.keyword_collector import collect_keywords
from app.services.keyword_mapper import build_keyword_signals_by_url, map_clusters_to_urls
from app.services.keyword_normalizer import normalize_keyword


def guess_brand_terms(host: str) -> set[str]:
    h = (host or "").lower()
    if h.startswith("www."):
        h = h[4:]
    parts = re.split(r"[.\-]", h)
    return {p for p in parts if len(p) > 2}


def build_keyword_intelligence_bundle(
    pages: list[dict[str, Any]],
    start_url: str,
    *,
    user_keywords: list[str] | None = None,
    gsc_queries: list[dict[str, Any]] | None = None,
    fetch_serp: bool | None = None,
) -> dict[str, Any]:
    host = urlparse(start_url).hostname or ""
    brand = guess_brand_terms(host)

    collected = collect_keywords(user_keywords=user_keywords, pages=pages, gsc_queries=gsc_queries)
    if not collected:
        return {
            "clusters": [],
            "keywords": [],
            "mappings": [],
            "url_signals": {},
            "coverage_summary": {
                "total_keywords": 0,
                "total_clusters": 0,
                "covered_clusters": 0,
                "uncovered_clusters": 0,
            },
        }

    clusters = cluster_keywords(collected, brand_terms=brand, fetch_serp=fetch_serp)
    mappings = map_clusters_to_urls(clusters, pages)
    url_signals = build_keyword_signals_by_url(clusters, mappings)

    seen: set[str] = set()
    flat_kw: list[dict[str, Any]] = []
    for cl in clusters:
        for r in cl.get("keywords") or []:
            nk = normalize_keyword(str(r.get("keyword") or ""))
            if nk and nk not in seen:
                seen.add(nk)
                flat_kw.append(r)

    covered = 0
    for m in mappings:
        if str(m.get("target_url") or "") and float(m.get("match_score") or 0) >= 0.15:
            covered += 1
    total_c = len(clusters)
    summary = {
        "total_keywords": len(flat_kw),
        "total_clusters": total_c,
        "covered_clusters": covered,
        "uncovered_clusters": max(0, total_c - covered),
    }

    return {
        "clusters": clusters,
        "keywords": flat_kw,
        "mappings": mappings,
        "url_signals": url_signals,
        "coverage_summary": summary,
    }


def attach_cluster_opportunities(
    bundle: dict[str, Any],
    *,
    ranking_by_url: dict[str, float],
    url_word_counts: dict[str, int],
) -> dict[str, Any]:
    from app.services.keyword_opportunity import detect_cluster_opportunities

    out = dict(bundle)
    out["opportunities"] = detect_cluster_opportunities(
        out.get("clusters") or [],
        out.get("mappings") or [],
        ranking_by_url=ranking_by_url,
        url_word_counts=url_word_counts,
    )
    return out


def persist_keyword_intel(
    db: Any,
    project_id: int,
    bundle: dict[str, Any],
) -> None:
    """Persist clusters, keywords, and URL mappings for a project."""
    from app.models.keyword_intel import SEOKeywordClusterEntity, SEOKeywordEntity, SEOKeywordUrlMapping

    clusters = bundle.get("clusters") or []
    mappings = bundle.get("mappings") or []

    for cl in clusters:
        cid = str(cl.get("cluster_id") or "")
        db.add(
            SEOKeywordClusterEntity(
                project_id=project_id,
                cluster_uid=cid,
                cluster_name=str(cl.get("cluster_name") or "")[:500],
                dominant_intent=str(cl.get("intent") or ""),
                intent_confidence=float(cl.get("intent_confidence") or 0) or None,
                total_search_volume=int(cl.get("total_search_volume") or 0) or None,
                explain_json=json.dumps(cl.get("explain") or {}, ensure_ascii=False)[:65000],
            )
        )
        for r in cl.get("keywords") or []:
            db.add(
                SEOKeywordEntity(
                    project_id=project_id,
                    keyword=str(r.get("keyword") or "")[:2000],
                    normalized_keyword=normalize_keyword(str(r.get("keyword") or ""))[:500],
                    source=str(r.get("source") or "page"),
                    page_url=str(r.get("url") or "")[:2000] if r.get("url") else None,
                    search_volume=r.get("search_volume"),
                    volume_source=str(r.get("volume_source") or "")[:24] or None,
                    volume_confidence=float(r.get("volume_confidence") or 0) or None,
                    intent=str(r.get("intent") or "")[:32] or None,
                    intent_confidence=float(r.get("intent_confidence") or 0) or None,
                    cluster_uid=cid[:64],
                    details_json=json.dumps(
                        {"intent_reasoning": r.get("intent_reasoning")}, ensure_ascii=False
                    )[:8000],
                )
            )

    for m in mappings:
        db.add(
            SEOKeywordUrlMapping(
                project_id=project_id,
                cluster_uid=str(m.get("cluster_id") or "")[:64],
                target_url=str(m.get("target_url") or "")[:4000],
                match_score=float(m.get("match_score") or 0.0),
            )
        )
    db.commit()
