"""
Heuristic on-page content signals for ranking potential (not keyword research tooling).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup


def _visible_text(html: str, max_chars: int = 500_000) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:max_chars]
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:max_chars]


def _word_count(text: str) -> int:
    return len(re.findall(r"[a-zA-Z\u00c0-\u024f0-9]+(?:'[a-z]+)?", text))


def _heading_structure_score(soup: BeautifulSoup) -> float:
    """0–1: presence of H1, reasonable H2 count, penalty for skipped levels."""
    h1n = len(soup.find_all("h1"))
    h2n = len(soup.find_all("h2"))
    h3n = len(soup.find_all("h3"))
    score = 0.0
    if h1n == 1:
        score += 0.45
    elif h1n > 1:
        score += 0.25
    elif h1n == 0:
        score += 0.05
    if h2n >= 2:
        score += min(0.35, 0.08 * h2n)
    elif h2n == 1:
        score += 0.12
    if h3n and h2n:
        score += 0.1
    if h1n and not h2n and h3n > 2:
        score *= 0.75
    return max(0.0, min(1.0, round(score, 3)))


def _keyword_density_estimate(text: str) -> dict[str, Any]:
    """
    Heuristic concentration of the dominant token (not a target keyword list).

    Returns max term frequency among alphabetic words and a simple ``concentration`` flag.
    """
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    if not words:
        return {"top_term_frequency": 0.0, "top_term": None, "concentration": "none"}
    c = Counter(words)
    most, cnt = c.most_common(1)[0]
    tf = cnt / len(words)
    if tf > 0.12:
        level = "high"
    elif tf > 0.06:
        level = "medium"
    else:
        level = "low"
    return {
        "top_term_frequency": round(tf, 4),
        "top_term": most,
        "concentration": level,
    }


def analyze_content(html: str) -> dict[str, Any]:
    """
    Extract word count, depth bucket, heading score, and a density heuristic.
    """
    raw = html if isinstance(html, str) else ""
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        soup = BeautifulSoup("", "html.parser")

    text = _visible_text(raw)
    wc = _word_count(text)
    if wc < 300:
        depth = "thin"
    elif wc < 900:
        depth = "normal"
    else:
        depth = "deep"

    h_score = _heading_structure_score(soup)
    dens = _keyword_density_estimate(text)

    return {
        "word_count": wc,
        "content_depth": depth,
        "heading_structure_score": h_score,
        "keyword_density_estimate": dens,
    }
