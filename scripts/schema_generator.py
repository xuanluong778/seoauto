"""
Build JSON-LD objects per detected @type from parsed page signals.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse


def _origin(url: str) -> str:
    p = urlparse((url or "").strip() or "https://example.com/")
    scheme = p.scheme or "https"
    netloc = p.netloc or "example.com"
    return f"{scheme}://{netloc}".rstrip("/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_schemas(types: list[str], parsed: dict[str, Any], *, page_url: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    origin = _origin(page_url)
    title = (parsed.get("title") or "Page").strip()[:200]
    desc = (parsed.get("meta_description") or parsed.get("body_text_sample") or "")[:500]
    og_image = (parsed.get("og_image") or "").strip()
    ents = list(parsed.get("entities") or [])
    site_name = title or urlparse(page_url).netloc or "Site"
    org_name = ents[0] if ents else site_name

    for t in types:
        if t == "WebPage":
            node: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "@id": page_url,
                "url": page_url,
                "name": title,
                "description": desc,
                "isPartOf": {"@type": "WebSite", "@id": f"{origin}/#website"},
            }
            if og_image:
                node["primaryImageOfPage"] = {"@type": "ImageObject", "url": urljoin(page_url, og_image)}
            out.append(node)
        elif t == "WebSite":
            out.append(
                {
                    "@context": "https://schema.org",
                    "@type": "WebSite",
                    "@id": f"{origin}/#website",
                    "url": origin,
                    "name": site_name[:200],
                    "potentialAction": {
                        "@type": "SearchAction",
                        "target": f"{origin}/?s={{search_term_string}}",
                        "query-input": "required name=search_term_string",
                    },
                }
            )
        elif t == "Organization":
            out.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "@id": f"{origin}/#org",
                    "name": org_name,
                    "url": origin,
                }
            )
        elif t == "Article":
            out.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Article",
                    "headline": title,
                    "description": desc,
                    "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
                    "dateModified": _now_iso(),
                    "author": {"@type": "Organization", "name": org_name},
                    "publisher": {"@type": "Organization", "name": org_name},
                }
            )
        elif t == "FAQPage":
            qa = _extract_faq_pairs(parsed)
            if not qa:
                qa = [
                    {
                        "@type": "Question",
                        "name": title,
                        "acceptedAnswer": {"@type": "Answer", "text": desc or "See page for details."},
                    }
                ]
            out.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": qa})
        elif t == "HowTo":
            steps = _extract_howto_steps(parsed)
            out.append(
                {
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": title,
                    "description": desc,
                    "step": steps,
                }
            )
        elif t == "Product":
            prod: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": title,
                "description": desc,
                "offers": {
                    "@type": "Offer",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                    "url": page_url,
                },
            }
            if og_image:
                prod["image"] = urljoin(page_url, og_image)
            out.append(prod)
        elif t == "Review":
            out.append(
                {
                    "@context": "https://schema.org",
                    "@type": "Review",
                    "itemReviewed": {"@type": "Thing", "name": title},
                    "reviewBody": desc[:400],
                    "author": {"@type": "Person", "name": "Author"},
                }
            )
        elif t == "BreadcrumbList":
            items = []
            for i, c in enumerate(parsed.get("breadcrumb_items") or [], start=1):
                href = (c.get("url") or "").strip()
                if href and not href.startswith("http"):
                    href = urljoin(page_url, href)
                items.append(
                    {
                        "@type": "ListItem",
                        "position": i,
                        "name": c.get("name"),
                        "item": href or page_url,
                    }
                )
            if items:
                out.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
    return out


def _extract_faq_pairs(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    sample = (parsed.get("body_text_sample") or "")[:4000]
    pairs: list[dict[str, Any]] = []
    for m in re.finditer(r"(?:^|\n)\s*(?:q:|question:?)\s*(.+?)\s*(?:a:|answer:?)\s*(.+?)(?=\n|$)", sample, re.I | re.S):
        q, a = m.group(1).strip()[:300], m.group(2).strip()[:800]
        if q and a:
            pairs.append(
                {
                    "@type": "Question",
                    "name": q,
                    "acceptedAnswer": {"@type": "Answer", "text": a},
                }
            )
    if not pairs and parsed.get("headings"):
        h2 = (parsed.get("headings") or {}).get("h2") or []
        for h in h2[:4]:
            pairs.append(
                {
                    "@type": "Question",
                    "name": h,
                    "acceptedAnswer": {"@type": "Answer", "text": parsed.get("meta_description") or h},
                }
            )
    return pairs[:12]


def _extract_howto_steps(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    h2 = (parsed.get("headings") or {}).get("h2") or []
    steps = []
    for i, name in enumerate(h2[:8], start=1):
        steps.append({"@type": "HowToStep", "position": i, "name": name, "text": name})
    if not steps:
        steps = [{"@type": "HowToStep", "position": 1, "name": "Bước 1", "text": parsed.get("meta_description") or ""}]
    return steps
