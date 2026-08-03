"""
Multi-page SERP ground-truth collection with optional redundancy and trust metrics.

Uses ``fetch_serp_keyword_page`` (SerpAPI / Google CSE) up to ``top_n`` (max 100).
Falls back to ``fetch_serp_for_keyword`` for a single shallow page when pagination is unavailable.
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.services.ground_truth_store import utc_now_iso
from app.services.serp_fetcher import (
    fetch_serp_for_keyword,
    fetch_serp_keyword_page,
    normalize_serp_url,
)


def _truth_top_n_default() -> int:
    return max(10, min(100, int(os.getenv("GROUND_TRUTH_TOP_N", "50"))))


def _redundancy_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.getenv("GROUND_TRUTH_SERP_REDUNDANCY", "1").strip().lower() in ("1", "true", "yes", "on")


def _collect_pages(keyword: str, *, top_n: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returns ``(results, meta)`` where each result is
    ``{rank, url, title, snippet, features}`` and meta explains fetch stats.
    """
    kw = (keyword or "").strip()
    top_n = max(1, min(100, top_n))
    attempts = 0
    ok_pages = 0
    pages: list[dict[str, Any]] = []

    for start in range(1, top_n + 1, 10):
        attempts += 1
        page = fetch_serp_keyword_page(kw, start=start, num=10, use_cache=False)
        if not page or not (page.get("serp_urls") or []):
            break
        ok_pages += 1
        pages.append(page)
        if len(page.get("serp_urls") or []) < 10:
            break

    results: list[dict[str, Any]] = []
    rank = 0
    seen: set[str] = set()
    for pg in pages:
        urls = list(pg.get("serp_urls") or [])
        titles = list(pg.get("titles") or [])
        snippets = list(pg.get("snippets") or [])
        for i, u in enumerate(urls):
            if rank >= top_n:
                break
            u = normalize_serp_url(str(u))
            if not u or u in seen:
                continue
            seen.add(u)
            rank += 1
            results.append(
                {
                    "rank": rank,
                    "url": u,
                    "title": str(titles[i] if i < len(titles) else "")[:300],
                    "snippet": str(snippets[i] if i < len(snippets) else "")[:500],
                    "features": {"source": pg.get("source"), "page_start": pg.get("start")},
                }
            )
        if rank >= top_n:
            break

    if not results:
        attempts += 1
        snap = fetch_serp_for_keyword(kw, top_n=min(10, top_n), use_cache=False)
        urls = list(snap.get("serp_urls") or [])
        titles = list(snap.get("titles") or [])
        snippets = list(snap.get("snippets") or [])
        if urls:
            ok_pages += 1
        for i, u in enumerate(urls[:top_n]):
            u = normalize_serp_url(str(u))
            if not u:
                continue
            results.append(
                {
                    "rank": i + 1,
                    "url": u,
                    "title": str(titles[i] if i < len(titles) else "")[:300],
                    "snippet": str(snippets[i] if i < len(snippets) else "")[:500],
                    "features": {"source": snap.get("source"), "page_start": 1, "fallback": "single_page"},
                }
            )

    nonempty_fields = 0
    total_fields = max(1, len(results) * 3)
    for r in results:
        nonempty_fields += int(bool(r.get("url")))
        nonempty_fields += int(bool(str(r.get("title") or "").strip()))
        nonempty_fields += int(bool(str(r.get("snippet") or "").strip()))
    render_completeness = round(nonempty_fields / total_fields, 4)
    fetch_success_rate = round(ok_pages / max(1, attempts), 4)

    meta = {
        "attempted_pages": attempts,
        "successful_pages": ok_pages,
        "fetch_success_rate": fetch_success_rate,
        "render_completeness": render_completeness,
        "rank_depth_returned": len(results),
        "rank_depth_requested": top_n,
        "explain": (
            "fetch_success_rate = successful SERP pages / attempts; "
            "render_completeness = share of non-empty url/title/snippet fields across rows."
        ),
    }
    return results, meta


def collect_serp_ground_truth(
    query: str,
    *,
    top_n: int | None = None,
    redundancy: bool | None = None,
    raw_api_extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Collect one ground-truth SERP document. Optionally performs a second independent
    pass and measures URL-list disagreement (duplication_rate as 1 - Jaccard).

    Returns:
      ``{query, timestamp, results, raw_api_extras?, data_trust, collector_meta}``
    """
    q = (query or "").strip()
    tn = int(top_n) if top_n is not None else _truth_top_n_default()
    results, meta = _collect_pages(q, top_n=tn)

    dup_rate = 0.0
    second_urls: list[str] = []
    if _redundancy_enabled(redundancy) and results:
        time.sleep(float(os.getenv("GROUND_TRUTH_REDUNDANCY_DELAY_SEC", "0.35")))
        r2, meta2 = _collect_pages(q, top_n=min(tn, len(results) + 20))
        second_urls = [str(x.get("url") or "") for x in r2]
        first_urls = [str(x.get("url") or "") for x in results]
        from app.services.serp_normalizer import duplication_rate as _dup_rate

        dup_rate = _dup_rate(first_urls, second_urls)
        meta["redundant_pass"] = {
            "attempted_pages": meta2.get("attempted_pages"),
            "successful_pages": meta2.get("successful_pages"),
        }

    data_trust = {
        "fetch_success_rate": meta.get("fetch_success_rate", 0.0),
        "render_completeness": meta.get("render_completeness", 0.0),
        "duplication_rate": round(dup_rate, 4),
        "explain": (
            "Trust proxies: higher fetch_success_rate and render_completeness are better; "
            "duplication_rate (1 - Jaccard of URLs vs redundant pass) near 0 means stable listing, "
            "high values may indicate volatility, geo variance, or provider inconsistency."
        ),
    }

    out: dict[str, Any] = {
        "query": q,
        "timestamp": utc_now_iso(),
        "results": results,
        "data_trust": data_trust,
        "collector_meta": meta,
    }
    if raw_api_extras:
        out["raw_api_extras"] = raw_api_extras
    return out
