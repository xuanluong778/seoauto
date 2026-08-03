"""
Lightweight topic signals from HTML (title, headings, main-ish body) — no heavy NLP.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup, Tag

# English + short Vietnamese function-word strip (extend as needed)
_STOPWORDS_EN: frozenset[str] = frozenset(
    """
    a an the and or but if then else for to of in on at by from as is was are were been be
    has have had having do does did doing will would could should may might must can need
    with without into over under again further once here there when where why how all both
    each few more most other some such no nor not only own same so than too very just also
    your our their its this that these those what which who whom whose about above below
    between through during before after while because until unless although though per via
    """.split()
)
_STOPWORDS_VI: frozenset[str] = frozenset(
    """
    và hoặc thì là có được các những một này đó khi nếu để của trong cho từ với về theo như
    còn đã sẽ bị được rất rồi chỉ cũng hay làm sao điều mà không phải trên dưới giữa
    """.split()
)
_STOPWORDS = _STOPWORDS_EN | _STOPWORDS_VI

_TOKEN_RE = re.compile(r"[a-z0-9\u00c0-\u024f]{2,}", re.I)


def _simple_stem(token: str) -> str:
    t = token.lower()
    if len(t) <= 4:
        return t
    for suf in ("ing", "tion", "ness", "ally", "ment", "ments", "ious", "eous", "able", "ible"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    return t


def _normalize_token(raw: str) -> str | None:
    t = _simple_stem(raw.strip().lower())
    if len(t) < 2 or t in _STOPWORDS:
        return None
    return t


def _tokens_from_text(text: str, max_tokens: int = 400) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        n = _normalize_token(m.group(0))
        if n:
            out.append(n)
        if len(out) >= max_tokens:
            break
    return out


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    for sel in ("nav", "footer", "header", "aside", "form", "noscript", "script", "style"):
        for el in soup.find_all(sel):
            el.decompose()
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        role = (el.get("role") or "").lower()
        if role in ("navigation", "contentinfo", "banner", "complementary"):
            el.decompose()


def _main_text(soup: BeautifulSoup) -> str:
    _strip_boilerplate(soup)
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
    if main:
        return main.get_text(" ", strip=True)
    # fallback: body without already stripped chrome
    body = soup.find("body")
    if body:
        return body.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def extract_topics(html: str) -> dict[str, Any]:
    """
    Extract ``primary_topic``, ``secondary_topics``, ``topic_confidence`` from HTML.

    Also returns ``keywords`` (token list) for clustering — used by the topical layer.
    """
    raw = html if isinstance(html, str) else ""
    if not raw.strip():
        return {
            "primary_topic": "unknown",
            "secondary_topics": [],
            "topic_confidence": 0.0,
            "keywords": [],
        }

    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        soup = BeautifulSoup("", "html.parser")

    title_el = soup.find("title")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    h1_text = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h1")[:3])
    h2_text = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h2")[:12])

    # Clone-ish parse for main content only
    try:
        soup2 = BeautifulSoup(raw, "html.parser")
    except Exception:
        soup2 = BeautifulSoup("", "html.parser")
    body_text = _main_text(soup2)

    title_tokens = _tokens_from_text(title, 80)
    heading_tokens = _tokens_from_text(f"{h1_text} {h2_text}", 120)
    body_tokens = _tokens_from_text(body_text, 400)

    head_counter = Counter(title_tokens + heading_tokens)
    body_counter = Counter(body_tokens)
    combined = Counter(title_tokens + heading_tokens + body_tokens)

    primary_topic = "unknown"
    if combined:
        primary_topic = combined.most_common(1)[0][0]

    secondary_topics: list[str] = []
    seen = {primary_topic}
    for tok, _ in combined.most_common(12):
        if tok in seen:
            continue
        seen.add(tok)
        secondary_topics.append(tok)
        if len(secondary_topics) >= 8:
            break

    # Confidence: heading/title agreement with body + mass in top term
    if not combined:
        conf = 0.0
    else:
        top_cnt = combined.most_common(1)[0][1]
        mass_top = top_cnt / max(1, sum(combined.values()))
        head_body_overlap = 0
        if body_counter and head_counter:
            head_set = set(head_counter)
            head_body_overlap = sum(body_counter[t] for t in head_set if t in body_counter) / max(
                1, sum(body_counter.values())
            )
        conf = min(
            1.0,
            max(0.0, 0.2 + 0.45 * mass_top + 0.35 * min(1.0, head_body_overlap * 1.4)),
        )

    keywords = list(combined.keys())
    # stable order: frequency then alpha
    keywords = sorted(set(keywords), key=lambda t: (-combined[t], t))[:200]

    return {
        "primary_topic": primary_topic,
        "secondary_topics": secondary_topics,
        "topic_confidence": round(conf, 3),
        "keywords": keywords,
    }
