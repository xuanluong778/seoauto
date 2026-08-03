"""
Fill recommended fields and light entity enrichment for JSON-LD nodes.
"""

from __future__ import annotations

from typing import Any


def optimize_schemas(schemas: list[dict[str, Any]], parsed: dict[str, Any]) -> list[dict[str, Any]]:
    entities = list(parsed.get("entities") or [])
    out: list[dict[str, Any]] = []
    for node in schemas:
        n = dict(node)
        t = n.get("@type")
        if t == "Article":
            if entities and not n.get("keywords"):
                n["keywords"] = ", ".join(entities[:8])
            if not n.get("datePublished"):
                n["datePublished"] = n.get("dateModified")
        if t == "Product":
            if not n.get("brand") and entities:
                n["brand"] = {"@type": "Brand", "name": entities[0]}
            if n.get("image") is None and parsed.get("og_image"):
                n["image"] = parsed.get("og_image")
        if t == "FAQPage":
            me = n.get("mainEntity")
            if isinstance(me, list) and me:
                for q in me:
                    if isinstance(q, dict) and not q.get("acceptedAnswer"):
                        q["acceptedAnswer"] = {"@type": "Answer", "text": parsed.get("meta_description") or ""}
        out.append(n)
    return out
