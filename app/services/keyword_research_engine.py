"""
Collect keyword candidates from seeds, URL/domain context, GSC, and light expansion.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from app.services.keyword_collector import collect_keywords
from app.services.keyword_normalizer import normalize_keyword


def _host_brand(host: str) -> set[str]:
    h = (host or "").lower()
    if h.startswith("www."):
        h = h[4:]
    return {p for p in re.split(r"[.\-]", h) if len(p) > 2}


def _expand_seeds(seeds: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        k = (phrase or "").strip()
        if not k or len(k) < 2 or len(k) > 120:
            return
        low = k.lower()
        if low in seen:
            return
        seen.add(low)
        out.append(k)

    max_expand = int(os.getenv("KEYWORD_RESEARCH_MAX_EXPAND", "80"))
    for s in seeds:
        k = (s or "").strip()
        if not k or len(k) < 2:
            continue
        _add(k)
        for extra in (
            f"{k} review",
            f"{k} vs",
            f"best {k}",
            f"{k} price",
            f"dịch vụ {k}",
            f"{k} tại nhà",
            f"{k} giá",
            f"{k} báo giá",
            f"{k} tphcm",
            f"{k} hà nội",
            f"{k} gần đây",
            f"{k} uy tín",
            f"{k} chuyên nghiệp",
            f"cách {k}",
            f"chi phí {k}",
            f"{k} tận nơi",
            f"thợ {k}",
            f"{k} 24h",
            f"{k} nhanh",
            f"dịch vụ {k} tphcm",
            f"{k} quận 1",
            f"{k} quận 7",
            f"so sánh {k}",
            f"review {k}",
        ):
            _add(extra)
            if len(out) >= max_expand:
                return out
    return out


def run_keyword_research(
    *,
    seed_keywords: list[str] | None = None,
    url: str | None = None,
    domain: str | None = None,
    gsc_queries: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    force_expand: bool = False,
) -> list[dict[str, Any]]:
    """
    Returns rows: ``keyword``, ``search_volume`` (optional), ``difficulty`` (0–1 estimate),
    ``source`` list of tags (``gsc``, ``page``, ``user``, ``expansion``).
    """
    seeds = list(seed_keywords or [])
    if url and not domain:
        domain = urlparse(url).hostname or ""
    if domain and not seeds:
        seeds = [domain.replace("www.", "")]

    expand_on = force_expand or os.getenv("KEYWORD_RESEARCH_EXPAND", "1").lower() in ("1", "true", "yes")
    expanded = _expand_seeds(seeds) if expand_on else list(seeds)

    collected = collect_keywords(
        user_keywords=expanded,
        pages=pages or [],
        gsc_queries=gsc_queries or [],
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in collected:
        kw = str(row.get("keyword") or "").strip()
        if not kw:
            continue
        nk = normalize_keyword(kw, remove_stopwords=False, stem=False)
        if nk in seen:
            continue
        seen.add(nk)
        src = row.get("source") or "user"
        tags: list[str] = [str(src)]
        if src == "page":
            tags.append("url_context")
        if src == "gsc":
            tags.append("gsc")
        if any(e.lower() == kw.lower() for e in expanded[len(seeds) :]):
            tags.append("expansion")
        vol = int(row.get("search_volume") or 0) if isinstance(row.get("search_volume"), (int, float)) else 0
        # Cheap difficulty proxy: longer multi-word = slightly harder
        diff = round(min(0.95, 0.25 + 0.04 * len(kw.split())), 3)
        out.append(
            {
                "keyword": kw,
                "search_volume": vol or None,
                "difficulty": diff,
                "source": sorted(set(tags)),
            }
        )
    return out[: int(os.getenv("KEYWORD_RESEARCH_MAX_RESULTS", "200"))]
