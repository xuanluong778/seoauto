"""
Normalized SERP snapshot for a single keyword (positions, domains, cache via serp_fetcher).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from app.services.serp_fetcher import fetch_serp_for_keyword, normalize_serp_url


def _domain_from_url(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def build_serp_snapshot(
    keyword: str,
    *,
    top_n: int | None = None,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    """
    Returns ``{keyword, serp_results: [{position, url, title, snippet, domain}, ...]}``.

    ``top_n`` defaults from env ``SERP_SNAPSHOT_TOP_N`` (10–20).
    """
    n = top_n or int(os.getenv("SERP_SNAPSHOT_TOP_N", "15"))
    n = max(5, min(20, n))
    raw = fetch_serp_for_keyword(keyword, top_n=n, use_cache=True, country=country, language=language, device=device)
    urls = list(raw.get("serp_urls") or [])
    titles = list(raw.get("titles") or [])
    snippets = list(raw.get("snippets") or [])
    results: list[dict[str, Any]] = []
    for i, u in enumerate(urls):
        nu = normalize_serp_url(u)
        if not nu:
            continue
        results.append(
            {
                "position": i + 1,
                "url": nu,
                "title": titles[i] if i < len(titles) else "",
                "snippet": snippets[i] if i < len(snippets) else "",
                "domain": _domain_from_url(nu),
            }
        )
    return {
        "keyword": keyword.strip(),
        "serp_results": results,
        "fetch_source": raw.get("source"),
    }
