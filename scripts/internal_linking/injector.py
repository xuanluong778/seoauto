from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

log = logging.getLogger(__name__)


def _norm_url_for_dedupe(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://x.local/{raw.lstrip('/')}")
        host = (p.netloc or "").lower()
        path = re.sub(r"/{2,}", "/", (p.path or "/")).rstrip("/").lower()
        return f"{host}{path}"
    except Exception:
        return raw.lower().rstrip("/")


def _tokenize_words(s: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{2,}", str(s or ""))


def _is_inside_link_or_heading(tag: Tag) -> bool:
    if tag.find_parent("a") is not None:
        return True
    if tag.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None:
        return True
    return False


def _find_text_nodes(soup: BeautifulSoup) -> list[NavigableString]:
    nodes: list[NavigableString] = []
    for el in soup.find_all(string=True):
        if not isinstance(el, NavigableString):
            continue
        txt = str(el)
        if not txt or not txt.strip():
            continue
        parent = getattr(el, "parent", None)
        if not isinstance(parent, Tag):
            continue
        # Skip scripts/styles and already-linked/headings
        if parent.name in {"script", "style", "noscript"}:
            continue
        if parent.find_parent(["script", "style", "noscript"]) is not None:
            continue
        if parent.name == "a" or parent.find_parent("a") is not None:
            continue
        if parent.name in {"h1", "h2", "h3", "h4", "h5", "h6"} or parent.find_parent(
            ["h1", "h2", "h3", "h4", "h5", "h6"]
        ):
            continue
        nodes.append(el)
    return nodes


@dataclass(frozen=True)
class LinkSuggestion:
    url: str
    title: str
    anchor_text: str
    score: float = 0.0


@dataclass(frozen=True)
class InjectionRules:
    max_links: int = 8
    min_word_gap: int = 80
    prefer_unique_urls: bool = True
    avoid_exact_anchor_reuse: bool = True


def inject_internal_links(
    *,
    html: str,
    suggestions: Sequence[LinkSuggestion],
    rules: InjectionRules | None = None,
) -> tuple[str, list[dict]]:
    """
    Inject internal links contextually into HTML.

    Guarantees:
    - Never inject inside existing <a> tags
    - Never inject inside headings
    - Avoid duplicate URLs
    - Cap links/article
    - Apply spacing rules (approx by word counts between injections)
    """
    r = rules or InjectionRules()
    max_links = max(0, min(int(r.max_links), 12))
    if max_links <= 0 or not suggestions:
        return str(html or ""), []

    raw = str(html or "").strip()
    if not raw:
        return raw, []

    soup = BeautifulSoup(raw, "html.parser")
    nodes = _find_text_nodes(soup)
    if not nodes:
        return raw, []

    # Dedupe + sanitize suggestions
    clean: list[LinkSuggestion] = []
    used_urls_norm: set[str] = set()
    for s in suggestions:
        url = str(getattr(s, "url", "") or "").strip()
        title = str(getattr(s, "title", "") or "").strip()
        anchor = re.sub(r"\s+", " ", str(getattr(s, "anchor_text", "") or "").strip())
        if not url or not anchor:
            continue
        nu = _norm_url_for_dedupe(url)
        if r.prefer_unique_urls and nu in used_urls_norm:
            continue
        used_urls_norm.add(nu)
        clean.append(LinkSuggestion(url=url, title=title, anchor_text=anchor, score=float(getattr(s, "score", 0.0) or 0.0)))
        if len(clean) >= max_links * 2:
            break

    if not clean:
        return raw, []

    # Sort by score desc, but randomize slightly so we don't always link the same in identical pages.
    clean.sort(key=lambda x: x.score, reverse=True)
    top = clean[: max_links * 2]
    random.shuffle(top)
    top.sort(key=lambda x: x.score, reverse=True)

    inserted: list[dict] = []
    used_url_norm: set[str] = set()
    used_anchor_norm: set[str] = set()

    words_since = 10_000  # allow first injection quickly

    def _count_words(text: str) -> int:
        return len(_tokenize_words(text))

    # Iterate nodes in order; for each node try to place best remaining suggestion.
    for node in nodes:
        if len(inserted) >= max_links:
            break
        parent = node.parent if isinstance(node.parent, Tag) else None
        if not parent or _is_inside_link_or_heading(parent):
            continue

        txt = str(node)
        txt_clean = re.sub(r"\s+", " ", txt).strip()
        if not txt_clean:
            continue

        words_since += _count_words(txt_clean)
        if words_since < int(r.min_word_gap):
            continue

        # Choose suggestion whose anchor best matches this node text (anchor must appear).
        chosen: LinkSuggestion | None = None
        idx = -1
        for cand in top:
            nu = _norm_url_for_dedupe(cand.url)
            if r.prefer_unique_urls and nu in used_url_norm:
                continue
            an = cand.anchor_text.strip()
            an_norm = an.lower()
            if r.avoid_exact_anchor_reuse and an_norm in used_anchor_norm:
                continue
            # Must find a case-insensitive occurrence in this text node
            m = re.search(re.escape(an), txt, flags=re.I)
            if not m:
                continue
            # Don't inject very short anchors into very short nodes
            if len(an) < 6 and len(txt_clean) < 60:
                continue
            chosen = cand
            idx = m.start()
            break
        if not chosen:
            continue

        # Perform replacement in the single text node (only first occurrence)
        an = chosen.anchor_text
        m = re.search(re.escape(an), txt, flags=re.I)
        if not m:
            continue
        start, end = m.start(), m.end()
        before = txt[:start]
        match = txt[start:end]
        after = txt[end:]

        a_tag = soup.new_tag("a", href=chosen.url)
        a_tag.string = match

        frag = []
        if before:
            frag.append(NavigableString(before))
        frag.append(a_tag)
        if after:
            frag.append(NavigableString(after))
        node.replace_with(*frag)

        used_url_norm.add(_norm_url_for_dedupe(chosen.url))
        used_anchor_norm.add(chosen.anchor_text.lower())
        inserted.append(
            {
                "url": chosen.url,
                "title": chosen.title,
                "anchor_text": match,
                "score": chosen.score,
            }
        )
        words_since = 0

    return str(soup), inserted

