"""
Extract structured signals from HTML (or plain text wrapped as HTML) for schema generation.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def _text(el: Any) -> str:
    if not el:
        return ""
    return el.get_text(" ", strip=True)


def parse_page_content(html: str, *, base_url: str = "") -> dict[str, Any]:
    """
    Returns title, meta, headings hierarchy, lightweight entities, section flags (FAQ, HowTo, product, review).
    """
    raw = (html or "").strip()
    if not raw:
        return {"error": "empty_input", "url": base_url}

    soup = BeautifulSoup(raw[:500_000], "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title_el = soup.find("title")
    title = _text(title_el)[:300]
    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not md:
        md = soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
    meta_description = (md.get("content") or "").strip()[:500] if md else ""

    og = soup.find("meta", attrs={"property": re.compile(r"^og:image$", re.I)})
    og_image = (og.get("content") or "").strip() if og else ""

    headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
    for lvl in ("h1", "h2", "h3"):
        for h in soup.find_all(lvl, limit=20):
            t = _text(h)
            if t and t not in headings[lvl]:
                headings[lvl].append(t[:240])

    body_text = _text(soup.find("body"))[:25_000].lower()

    # Section heuristics (data-driven from DOM + text)
    faq_nodes = soup.find_all(string=re.compile(r"faq|frequently asked|câu hỏi", re.I))
    has_faq = bool(soup.select("[itemtype*='FAQPage']")) or bool(
        re.search(r"\b(q:|question|đáp án|answer)\b", body_text[:8000])
    ) or len(faq_nodes) > 0

    howto = bool(re.search(r"\b(step\s*\d|bước\s*\d|how to|hướng dẫn)\b", body_text[:8000]))
    product = bool(
        re.search(
            r"\b(add to cart|mua ngay|price:|€|\$|usd|vnd|đồng|sku|in stock|out of stock)\b",
            body_text[:8000],
        )
    ) or bool(soup.select("[itemtype*='Product']"))
    review = bool(re.search(r"\b(\d\.?\d?\s*\/\s*5|stars?|đánh giá|review)\b", body_text[:8000]))
    article = bool(soup.find("article")) or bool(soup.find("time", attrs={"datetime": True}))

    # Simple "entities": capitalized phrases + org from og:site_name
    og_site = soup.find("meta", attrs={"property": re.compile(r"^og:site_name$", re.I)})
    org_name = (og_site.get("content") or "").strip() if og_site else ""
    entities: list[str] = []
    if org_name:
        entities.append(org_name)
    for m in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", _text(soup.find("body"))[:4000]):
        if len(m) > 5 and m not in entities:
            entities.append(m)
            if len(entities) >= 12:
                break

    crumbs = []
    nav = soup.find("nav") or soup.find(class_=re.compile(r"breadcrumb", re.I))
    if nav:
        for a in nav.find_all("a", href=True, limit=12):
            t = _text(a)
            if t:
                crumbs.append({"name": t[:120], "url": (a.get("href") or "").strip()})

    return {
        "url": base_url,
        "title": title,
        "meta_description": meta_description,
        "og_image": og_image,
        "headings": headings,
        "entities": entities,
        "sections": {
            "has_faq": has_faq,
            "has_howto": howto,
            "has_product": product,
            "has_review": review,
            "has_article_shell": article,
        },
        "breadcrumb_items": crumbs,
        "body_text_sample": body_text[:1200],
    }
