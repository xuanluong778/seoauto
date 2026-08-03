"""
Assemble Keyword Intelligence JSON (research → dedupe → cluster → score → summaries).
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse

from app.services.intent_classifier import classify_keywords_batch
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_normalizer import dedupe_keyword_dicts
from app.services.keyword_intelligence import guess_brand_terms
from app.services.keyword_research_engine import run_keyword_research
from app.services.opportunity_scoring_engine import score_keyword_clusters


def build_keyword_intelligence_response(
    *,
    seed_keyword: str | None = None,
    seed_keywords: list[str] | None = None,
    domain: str | None = None,
    url: str | None = None,
    gsc_queries: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    ranking_decision_v3: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Public bundle: ``keywords``, ``clusters``, ``intent_summary``, ``priority_opportunities``.
    """
    seeds = list(seed_keywords or [])
    if seed_keyword and seed_keyword.strip():
        seeds.insert(0, seed_keyword.strip())
    if not seeds and url:
        seeds = [urlparse(url).path.strip("/").replace("-", " ") or urlparse(url).hostname or ""]

    host = urlparse(url or "").hostname or (domain or "")
    brand = guess_brand_terms(f"https://{host}" if host else "https://example.com")

    raw_records = run_keyword_research(
        seed_keywords=seeds,
        url=url,
        domain=domain,
        gsc_queries=gsc_queries,
        pages=pages,
    )
    records = dedupe_keyword_dicts(raw_records, key_field="keyword")
    if not records:
        return {
            "keywords": [],
            "clusters": [],
            "intent_summary": {},
            "priority_opportunities": [],
            "explain": "No keyword candidates after research/dedupe — add seeds, GSC queries, or crawl pages.",
        }

    clusters = build_keyword_clusters(records, brand_terms=brand, fetch_serp=None)
    rp = None
    align = None
    if ranking_decision_v3:
        rp = float(ranking_decision_v3.get("ranking_probability") or 0.0)
        comps = dict((ranking_decision_v3.get("components") or {}))
        align = float(comps.get("mean_serp_alignment") or 0.0)
    scored = score_keyword_clusters(clusters, ranking_probability=rp, mean_serp_alignment=align)

    uniq_kw = []
    seen = set()
    for c in scored:
        for r in c.get("keywords") or []:
            k = str(r.get("keyword") or "").strip().lower()
            if k and k not in seen:
                seen.add(k)
                uniq_kw.append(str(r.get("keyword") or "").strip())

    intent_rows = classify_keywords_batch(uniq_kw, brand_terms=brand, max_serp_gt=min(12, len(uniq_kw)))
    dist = Counter(str(r.get("intent") or "informational") for r in intent_rows)
    tot = sum(dist.values()) or 1
    intent_summary = {k: round(v / tot, 4) for k, v in dist.items()}

    kw_out = []
    intent_by_kw = {str(r.get("keyword") or "").lower(): r for r in intent_rows}
    for r in records:
        kw = str(r.get("keyword") or "")
        hit = intent_by_kw.get(kw.lower())
        kw_out.append(
            {
                **r,
                "intent": (hit or {}).get("intent", "informational"),
                "intent_confidence": (hit or {}).get("confidence", 0.5),
                "intent_source": (hit or {}).get("source", "nlp_fallback"),
            }
        )

    priority = scored[:15]

    return {
        "keywords": kw_out,
        "clusters": scored,
        "intent_summary": intent_summary,
        "priority_opportunities": priority,
        "meta": {
            "seed_count": len(seeds),
            "keyword_candidates": len(records),
            "cluster_count": len(scored),
            "serp_clustering": bool(scored[0].get("explain")) if scored else False,
        },
    }
