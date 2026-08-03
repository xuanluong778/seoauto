"""
Generate conservative JSON-LD (WebSite + Organization + WebPage) from URL + optional fields.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


def build_schema_jsonld(
    *,
    url: str,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    p = urlparse((url or "").strip())
    origin = f"{p.scheme or 'https'}://{p.netloc or ''}".rstrip("/")
    page_url = (url or "").strip()
    nm = (name or p.netloc or "Site").strip() or "Website"
    desc = (description or f"Trang {nm}.").strip()

    graph: list[dict[str, Any]] = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": f"{origin}/#website",
            "url": origin or page_url,
            "name": nm,
            "potentialAction": {
                "@type": "SearchAction",
                "target": f"{origin}/?s={{search_term_string}}",
                "query-input": "required name=search_term_string",
            },
        },
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "@id": f"{origin}/#org",
            "name": nm,
            "url": origin or page_url,
        },
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "@id": page_url,
            "url": page_url,
            "name": nm,
            "description": desc,
            "isPartOf": {"@id": f"{origin}/#website"},
        },
    ]
    return {"@context": "https://schema.org", "@graph": graph}


def build_schema_jsonld_string(**kwargs: Any) -> str:
    return json.dumps(build_schema_jsonld(**kwargs), ensure_ascii=False, indent=2)
