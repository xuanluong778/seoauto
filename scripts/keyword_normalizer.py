"""
Normalize keywords for clustering and deduplication.

Designed to be cheap at scale (no heavy NLP deps); optional light stemming.
"""

from __future__ import annotations

import re
import string
from typing import Any

_STOP = frozenset(
    """
    a an the and or but if in on at to for of as is was are were be been being
    with from by about into through over under again further then once here there
    when where why how all each both few more most other some such no nor not only
    own same so than too very can will just don should now
    """.split()
)

_STOP_VI = frozenset(
    """
    và hoặc thì là của ở trong ngoài trên dưới cho với từ đến một các những này đó
    khi nếu như để mà còn đã bị được bài viết tin tức mua bán giá tốt nhất
    """.split()
)

_ALL_STOP = _STOP | _STOP_VI


def normalize_keyword(
    phrase: str,
    *,
    remove_stopwords: bool = True,
    stem: bool = True,
) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace, optional stopword removal + basic stem.
    """
    s = (phrase or "").strip().lower()
    punct = string.punctuation.replace("-", "").replace("'", "")
    s = s.translate(str.maketrans("", "", punct))
    s = re.sub(r"[^\w\s\-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    stop = _ALL_STOP if remove_stopwords else frozenset()
    parts = [p for p in s.split() if p and (not remove_stopwords or p not in stop)]
    if stem:
        parts = [_basic_stem(p) for p in parts]
    return " ".join(parts).strip()


def _basic_stem(w: str) -> str:
    if len(w) < 4:
        return w
    for suf in ("ization", "fulness", "ness", "ment", "ions", "tion", "ing", "edly", "ed", "er", "ly"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def normalize_batch(phrases: list[str], **kwargs: Any) -> list[str]:
    return [normalize_keyword(p, **kwargs) for p in phrases]


def dedupe_keyword_dicts(
    records: list[dict[str, Any]],
    *,
    key_field: str = "keyword",
) -> list[dict[str, Any]]:
    """Drop duplicates using :func:`normalize_keyword` (singular/plural/stopword collapse when stem=True)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in records:
        raw = str(r.get(key_field) or "").strip()
        if not raw:
            continue
        nk = normalize_keyword(raw, remove_stopwords=True, stem=True)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        out.append(dict(r))
    return out


def clustering_signature(phrase: str) -> str:
    """Khóa ổn định để gom keyword gần nghĩa (dùng trong merge trước hybrid cluster)."""
    return normalize_keyword(phrase, remove_stopwords=True, stem=True)


def merge_similar_keyword_records(
    records: list[dict[str, Any]],
    *,
    key_field: str = "keyword",
) -> list[dict[str, Any]]:
    """
    Gộp các record có cùng ``clustering_signature`` (lowercase, bỏ stopword, stem đơn giản).

    Giữ bản ghi có volume cao hơn (nếu có ``search_volume``) hoặc chuỗi dài hơn làm keyword hiển thị;
    gom URL GSC từ các dòng nguồn.
    """
    from collections import Counter, defaultdict

    from app.services.serp_fetcher import normalize_serp_url

    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        raw = str(r.get(key_field) or "").strip()
        if not raw:
            continue
        sig = clustering_signature(raw)
        if not sig:
            continue
        if sig not in buckets:
            order.append(sig)
        buckets[sig].append(dict(r))

    merged: list[dict[str, Any]] = []
    for sig in order:
        items = buckets[sig]
        scored = []
        for it in items:
            raw_k = str(it.get(key_field) or "").strip()
            vol = int(it.get("search_volume") or 0)
            scored.append((vol, len(raw_k), raw_k, it))
        scored.sort(reverse=True)
        _, _, _canon_kw, base = scored[0]
        row = dict(base)
        row[key_field] = str(base.get(key_field) or _canon_kw).strip()
        alts = sorted({str(x.get(key_field) or "").strip() for x in items} - {row[key_field]})
        if alts:
            row["merged_keyword_variants"] = alts[:12]
        gsc_urls: list[str] = []
        for x in items:
            u = x.get("gsc_page") or (x.get("url") if str(x.get("source") or "") == "gsc" else None)
            if u:
                try:
                    gsc_urls.append(normalize_serp_url(str(u).strip()))
                except Exception:
                    gsc_urls.append(str(u).strip().lower())
        if gsc_urls:
            top = [u for u, _ in Counter(gsc_urls).most_common(5)]
            row["gsc_landing_urls"] = top
            if not row.get("gsc_primary_url"):
                row["gsc_primary_url"] = top[0]
        merged.append(row)
    return merged
