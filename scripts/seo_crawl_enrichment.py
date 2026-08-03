"""
Compose crawl-time SEO signals (canonical, indexability, HTML diff, JS risk, cloaking).

Used by Playwright and HTTP detailed crawlers so ``analyzer`` receives one schema.
"""

from __future__ import annotations

from typing import Any

from app.services.canonical_utils import resolve_canonical_signals
from app.services.html_compare import build_html_comparison
from app.services.indexability import assess_indexability
from app.services.js_analysis import build_seo_signals, compute_js_seo_risk, detect_cloaking_risk


def enrich_crawl_page_record(
    *,
    rendered_html: str,
    raw_html: str,
    final_effective_url: str,
    raw_final_url: str,
    playwright_status: int,
    raw_http_status: int,
    playwright_headers: dict[str, Any],
    raw_headers: dict[str, Any],
    raw_fetch_error: str | None = None,
) -> dict[str, Any]:
    """
    Build canonical resolution, indexability, advanced ``raw_vs_rendered``, JS/cloaking, and ``seo_signals``.

    When ``rendered_html`` is empty, indexability still uses HTTP status + raw headers where useful.
    """
    fe = final_effective_url or ""
    rf = raw_final_url or fe

    raw_vs = build_html_comparison(
        raw_html or "",
        rendered_html or "",
        raw_final_url=rf,
        rendered_final_url=fe,
    )
    if raw_fetch_error:
        raw_vs["raw_fetch_error"] = raw_fetch_error

    canonical_resolution = resolve_canonical_signals(
        rendered_html or "",
        fe,
        raw_final_url_after_redirects=rf,
    )

    idx_html = rendered_html if (rendered_html or "").strip() else raw_html
    idx_status = playwright_status if (rendered_html or "").strip() else raw_http_status
    idx_headers = playwright_headers if (rendered_html or "").strip() else raw_headers

    indexability = assess_indexability(
        idx_html,
        idx_headers,
        int(idx_status or 0),
        secondary_headers=raw_headers,
    )

    js_risk = compute_js_seo_risk(raw_vs)
    cloaking = detect_cloaking_risk(raw_vs)
    seo_signals = build_seo_signals(
        html_compare=raw_vs,
        indexability=indexability,
        js_risk=js_risk,
        cloaking=cloaking,
    )

    out: dict[str, Any] = {
        "raw_vs_rendered": raw_vs,
        "canonical_resolution": canonical_resolution,
        "indexability": indexability,
        "js_seo_risk_score": js_risk["js_seo_risk_score"],
        "js_seo_risk_level": js_risk["js_seo_risk_level"],
        "cloaking_risk": cloaking["cloaking_risk"],
        "cloaking_reason": cloaking["cloaking_reason"],
        "seo_signals": seo_signals,
    }
    return out
