"""
Merge crawl quality, proxy stats, and domain priors into crawl_record fields
and trust gating for the SEO pipeline.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.crawl_quality import compute_crawl_quality
from app.services.domain_intelligence import domain_reliability_score
from app.services.proxy_manager import proxy_reliability_score

_QUALITY_SKIP = float(os.getenv("CRAWL_QUALITY_THRESHOLD_SKIP", "0.35"))
_CONF_SKIP = float(os.getenv("CRAWL_CONFIDENCE_THRESHOLD_SKIP", "0.32"))


def compute_crawl_confidence(
    *,
    crawl_quality_score: float,
    proxy_server: str | None,
    domain: str,
) -> float:
    pr = proxy_reliability_score(proxy_server)
    dr = domain_reliability_score(domain)
    wq, wp, wd = 0.5, 0.28, 0.22
    conf = wq * float(crawl_quality_score) + wp * pr + wd * dr
    return max(0.0, min(1.0, round(conf, 4)))


def enrich_page_crawl_intelligence(
    page: dict[str, Any],
    *,
    domain: str,
    proxy_server: str | None = None,
) -> dict[str, Any]:
    """
    Mutates ``page`` with quality, confidence, trust flags, explainability, and pipeline skip flag.

    Idempotent: recomputes from current page fields.
    """
    px = proxy_server or page.get("proxy_used")
    qc = compute_crawl_quality(page)
    conf = compute_crawl_confidence(
        crawl_quality_score=qc["crawl_quality_score"],
        proxy_server=px,
        domain=domain or "",
    )
    low_q = qc["crawl_quality_score"] < _QUALITY_SKIP
    low_c = conf < _CONF_SKIP
    trust = "high"
    if low_q or low_c:
        trust = "low" if (qc["crawl_quality_score"] < _QUALITY_SKIP * 0.85 or conf < _CONF_SKIP * 0.9) else "medium"

    page["crawl_quality_score"] = qc["crawl_quality_score"]
    page["quality_level"] = qc["quality_level"]
    page["reliability_flags"] = qc["reliability_flags"]
    page["crawl_quality_explain"] = qc.get("explain") or []
    page["crawl_confidence_score"] = conf
    page["data_trust"] = trust
    page["skip_seo_analysis"] = bool(low_q or low_c)
    return page
