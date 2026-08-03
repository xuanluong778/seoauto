"""
Collect keyword candidates from user input, crawled pages, and optional GSC query rows.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


def _strip_html(html: str, max_len: int = 12000) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html[:max_len], "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html[:max_len])


def _tokens_from_text(text: str, *, min_len: int = 4, max_ngrams: int = 40) -> list[str]:
    text = re.sub(r"[^\w\s\-]", " ", (text or "").lower())
    words = [w for w in text.split() if len(w) >= min_len]
    out: list[str] = []
    # unigrams + bigrams (phrase-like)
    for w in words[:80]:
        if w not in out:
            out.append(w)
    for i in range(len(words) - 1):
        bg = f"{words[i]} {words[i + 1]}"
        if len(bg) >= 7 and bg not in out:
            out.append(bg)
        if len(out) >= max_ngrams:
            break
    return out


def extract_keywords_from_page(page: dict[str, Any], *, max_keywords: int = 25) -> list[dict[str, Any]]:
    """Pull phrases from title, H1, and visible text (heuristic, not full KE)."""
    url = str(page.get("url") or "")
    html = str(page.get("html") or "")
    title = ""
    h1s: list[str] = []
    try:
        soup = BeautifulSoup(html[:80000], "html.parser")
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)
        for h in soup.find_all("h1")[:3]:
            txt = h.get_text(strip=True)
            if txt:
                h1s.append(txt)
    except Exception:
        pass

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def add(kw: str, *, kind: str) -> None:
        k = kw.strip()
        if len(k) < 3 or len(k) > 120:
            return
        low = k.lower()
        if low in seen:
            return
        seen.add(low)
        out.append({"keyword": k, "source": "page", "url": url, "origin": kind})

    for part in [title, *h1s]:
        if part:
            add(part, kind="heading")

    body = _strip_html(html)
    for tok in _tokens_from_text(body):
        add(tok, kind="content")
        if len(out) >= max_keywords:
            break
    return out


def collect_keywords(
    *,
    user_keywords: list[str] | None = None,
    pages: list[dict[str, Any]] | None = None,
    gsc_queries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Merge sources into a de-duplicated list of ``{keyword, source, url?}``.

    ``gsc_queries`` items: ``{"query": str, "page"?: str}`` (Search Console rows).
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(kw: str, source: str, url: str | None = None, **extra: Any) -> None:
        k = (kw or "").strip()
        if len(k) < 2:
            return
        low = k.lower()
        if low in seen:
            return
        seen.add(low)
        row: dict[str, Any] = {"keyword": k, "source": source}
        if url:
            row["url"] = url
        row.update(extra)
        out.append(row)

    for u in user_keywords or []:
        push(str(u), "user")

    for row in gsc_queries or []:
        q = str(row.get("query") or row.get("keys") or "").strip()
        if not q:
            continue
        pg = row.get("page") or row.get("url")
        push(q, "gsc", str(pg) if pg else None)

    for page in pages or []:
        if int(page.get("status") or 0) != 200:
            continue
        for ex in extract_keywords_from_page(page):
            push(ex["keyword"], "page", ex.get("url"), origin=ex.get("origin"))

    return out
