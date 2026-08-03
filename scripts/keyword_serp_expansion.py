"""
Expand keyword candidates using organic SERP titles/snippets (proxy for related searches / PAA).
"""

from __future__ import annotations

import re
from typing import Any

from app.services.serp_fetcher import fetch_serp_for_keyword


_SPLIT_TTL = re.compile(r"[\|\-–—:·]+")


def _phrases_from_serp_text(text: str, *, seed_lower: str, seen: set[str], out: list[str], cap: int) -> None:
    t = (text or "").strip()
    if len(t) < 8 or len(t) > 140:
        return
    low = t.lower()
    if low == seed_lower or low in seen:
        return
    # drop pure site-name titles
    if re.fullmatch(r"[\w\s]+\.(com|io|net|org)", low):
        return
    seen.add(low)
    out.append(t[:120])
    if len(out) >= cap:
        return
    for chunk in _SPLIT_TTL.split(t):
        c = chunk.strip()
        if 10 <= len(c) <= 120:
            cl = c.lower()
            if cl != seed_lower and cl not in seen:
                seen.add(cl)
                out.append(c)
                if len(out) >= cap:
                    return


def expand_keywords_from_serp(
    seeds: list[str],
    *,
    per_seed_cap: int = 24,
    total_cap: int = 400,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> list[dict[str, Any]]:
    """
    Returns rows ``{keyword, source}`` with ``source`` ``serp`` (not yet merged with user seeds).
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in seeds:
        s = (seed or "").strip()
        if not s:
            continue
        sl = s.lower()
        snap = fetch_serp_for_keyword(s, top_n=10, country=country, language=language, device=device)
        buf: list[str] = []
        for title in snap.get("titles") or []:
            _phrases_from_serp_text(str(title), seed_lower=sl, seen=seen, out=buf, cap=per_seed_cap)
        for snip in snap.get("snippets") or []:
            _phrases_from_serp_text(str(snip), seed_lower=sl, seen=seen, out=buf, cap=per_seed_cap)
        for kw in buf:
            rows.append({"keyword": kw, "source": "serp"})
            if len(rows) >= total_cap:
                return rows
    return rows
