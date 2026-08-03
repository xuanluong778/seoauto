"""

Intent-first keyword clustering with semantic + SERP overlap (delegates to hybrid clusterer).

"""



from __future__ import annotations



import os

from typing import Any



from app.services.cluster_planning_output import enrich_hybrid_cluster_for_planning

from app.services.keyword_clusterer import cluster_keywords





def build_keyword_clusters(

    keyword_records: list[dict[str, Any]],

    *,

    brand_terms: set[str] | None = None,

    fetch_serp: bool | None = None,

    serp_country: str | None = None,

    serp_language: str | None = None,

    serp_device: str | None = None,

    cluster_strictness: str | None = None,
    progress_hook: callable | None = None,

) -> list[dict[str, Any]]:

    """

    Wraps :func:`cluster_keywords` and exposes ``serp_overlap_score`` (alias of internal SERP cohesion).



    ``fetch_serp`` defaults True for this module so SERP overlap participates unless disabled.

    """

    if fetch_serp is None:

        fetch_serp = os.getenv("KEYWORD_INTEL_CLUSTER_FETCH_SERP", "1").lower() in ("1", "true", "yes")

    clusters = cluster_keywords(

        keyword_records,

        brand_terms=brand_terms,

        fetch_serp=fetch_serp,

        serp_country=serp_country,

        serp_language=serp_language,

        serp_device=serp_device,

        cluster_strictness=cluster_strictness,
        progress_hook=progress_hook,

    )

    for c in clusters:

        enrich_hybrid_cluster_for_planning(c)

        serp_avg = float(c.get("serp_similarity_avg") or 0.0)

        c["serp_overlap_score"] = round(serp_avg, 4)

        c["cluster_size"] = len(c.get("keywords") or [])

        kws = c.get("keywords") or []

        main_kw = str(c.get("main_keyword") or (kws[0] or {}).get("keyword") or c.get("cluster_name") or "")

        c["main_keyword"] = main_kw

        c["intent"] = str(c.get("intent") or "informational")

    return clusters


