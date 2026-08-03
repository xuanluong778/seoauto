"""
Compare your crawled pages to SERP competitors: authority, content, topical alignment gaps.
"""

from __future__ import annotations

import math
import re
from typing import Any


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower()) if len(w) > 2}


def _match_score(keyword: str, url: str, title: str) -> float:
    kt = _tokens(keyword)
    if not kt:
        return 0.2
    blob = f"{url} {title}".lower()
    hits = sum(1 for t in kt if t in blob)
    return min(1.0, 0.15 + 0.22 * hits)


def analyze_ranking_gap(
    keyword: str,
    your_pages: list[dict[str, Any]],
    serp_data: dict[str, Any],
) -> dict[str, Any]:
    """
    ``your_pages``: ``[{ "url", "ranking_score"?, "word_count"?, "primary_topic"?, "title"? }, ...]``
    ``serp_data``: merged fetch + ``serp_analysis`` with ``competitors`` (enriched list).
    """
    comps = list(serp_data.get("serp_analysis", {}).get("competitors") or serp_data.get("competitors") or [])
    if not your_pages:
        return {
            "best_matching_url": None,
            "position_estimate": None,
            "authority_gap": None,
            "content_gap": None,
            "topical_gap": None,
            "actionable_gap": ["Add crawled pages or connect site crawl to compare against this SERP."],
        }

    best_url = None
    best_sc = -1.0
    best_row: dict[str, Any] = {}
    for p in your_pages:
        url = str(p.get("url") or "")
        title = str(p.get("title") or p.get("parsed_title") or "")
        sc = _match_score(keyword, url, title)
        if sc > best_sc:
            best_sc = sc
            best_url = url
            best_row = dict(p)

    your_pr = float(best_row.get("pagerank_score") or best_row.get("pagerank") or 0.35)
    your_wc = int(best_row.get("word_count") or 0)
    your_topic = str(best_row.get("primary_topic") or "").lower()

    max_c = 0.0
    snippet_lens: list[int] = []
    for c in comps:
        max_c = max(max_c, float(c.get("estimated_authority") or 0))
        sn = str(c.get("snippet") or "")
        snippet_lens.append(len(sn))

    med_snip = sorted(snippet_lens)[len(snippet_lens) // 2] if snippet_lens else 120
    proxy_comp_wc = max(400, min(2400, int(med_snip * 4.5)))

    authority_gap = round(max(0.0, max_c - your_pr), 4)
    content_gap = int(max(0, proxy_comp_wc - your_wc))

    topical_gap = 0.35
    yt = _tokens(your_topic) if your_topic else set()
    ctitles = _tokens(" ".join(str(c.get("title") or "") for c in comps[:10]))
    if yt:
        overlap = len(yt & ctitles)
        topical_gap = round(1.0 - min(1.0, overlap / max(1, len(yt))), 3)

    # Position estimate: map composite strength to 1–30
    your_strength = 0.45 * your_pr + 0.35 * min(1.0, your_wc / 1400.0) + 0.2 * best_sc
    bench = sum(float(x.get("estimated_authority") or 0.3) for x in comps[:10]) / max(1, min(10, len(comps)))
    ratio = your_strength / max(0.15, bench)
    pos = int(round(14 / max(0.35, min(1.8, ratio))))
    pos = max(1, min(22, pos))

    actions: list[str] = []
    if authority_gap > 0.2:
        actions.append("Grow internal links and topical hubs to lift PageRank toward SERP leaders.")
    if content_gap > 250:
        actions.append("Expand depth (FAQ, entities, examples) to match or exceed implied competitor content mass.")
    if topical_gap > 0.35:
        actions.append("Tighten primary topic and H1/title alignment with the target query intent.")
    if not actions:
        actions.append("Iterate titles for query coverage; earn citations and brand SERP signals.")

    return {
        "best_matching_url": best_url,
        "position_estimate": pos,
        "authority_gap": authority_gap,
        "content_gap": content_gap,
        "topical_gap": topical_gap,
        "actionable_gap": actions[:6],
    }
