"""
Per-competitor-page content features for SERP benchmarking (depth, headings, keyword cover, readability).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup


def _visible_text(html: str, max_chars: int = 200_000) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:max_chars]
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:max_chars]


def _keyword_coverage(text: str, keyword: str) -> float:
    if not text or not keyword:
        return 0.0
    toks = set(re.findall(r"[a-z0-9]{3,}", keyword.lower()))
    if not toks:
        return 0.0
    words = re.findall(r"[a-z0-9]{3,}", text.lower())
    if not words:
        return 0.0
    hit = sum(1 for w in words if w in toks)
    return round(min(1.0, (hit / max(len(words), 1)) * 5.0), 3)


def _readability_basic(text: str) -> dict[str, Any]:
    """Very rough readability proxy (not true Flesch)."""
    sents = max(1, len(re.split(r"[.!?]+", text)))
    words = max(1, len(re.findall(r"\w+", text)))
    syll = len(re.findall(r"[aeiouy]+", text.lower()))
    asl = words / sents
    asw = syll / max(words, 1)
    # lower asl+asw slightly easier
    score = max(0.0, min(100.0, 96.0 - 1.2 * asl - 8.0 * asw))
    return {"readability_score": round(score, 1), "avg_sentence_length": round(asl, 1)}


def _semantic_richness_spread(text: str, *, max_terms: int = 80) -> float:
    """TF-IDF-like concentration inverse as richness: higher when vocabulary diverse."""
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    if len(words) < 20:
        return 0.2
    c = Counter(words)
    top_share = c.most_common(1)[0][1] / len(words)
    uniq_ratio = len(set(words)) / len(words)
    rich = 0.55 * uniq_ratio + 0.45 * (1.0 - min(0.85, top_share * 3))
    return round(max(0.0, min(1.0, rich)), 3)


def analyze_competitor_content(
    html: str,
    keyword: str,
    url: str,
    *,
    base_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    ``base_features``: optional row from ``fetch_competitor_page`` (word_count, heading_structure_score, ...).
    """
    base = dict(base_features or {})
    raw_html = html or str(base.get("html_excerpt") or "")
    text = _visible_text(raw_html)
    wc = int(base.get("word_count") or len(re.findall(r"\w+", text)))
    h_score = float(base.get("heading_structure_score") or 0.0)
    depth = base.get("content_depth") or ("thin" if wc < 400 else "normal" if wc < 1200 else "deep")
    depth_score = {"thin": 0.25, "normal": 0.55, "deep": 0.9}.get(str(depth), 0.5)

    cov = float(_keyword_coverage(text, keyword))
    read = _readability_basic(text)
    sem = _semantic_richness_spread(text)

    return {
        "url": url,
        "content_depth_score": round(depth_score, 3),
        "heading_structure_score": round(h_score, 3),
        "keyword_coverage": cov,
        "semantic_richness": sem,
        "readability": read,
        "word_count": wc,
        "content_depth_label": depth,
    }
