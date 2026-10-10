"""
JSON-LD shape checks + required-field heuristics for common rich-result types.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup


_REQUIRED: dict[str, list[str]] = {
    "Article": ["headline", "author"],
    "NewsArticle": ["headline", "author"],
    "BlogPosting": ["headline", "author"],
    "FAQPage": ["mainEntity"],
    "HowTo": ["name", "step"],
    "Product": ["name", "offers"],
    "Review": ["itemReviewed", "reviewBody", "author"],
    "BreadcrumbList": ["itemListElement"],
    "WebPage": ["url", "name"],
    "Organization": ["name"],
}


def flatten_schema_nodes(obj: Any) -> list[dict[str, Any]]:
    """Flatten @graph / nested lists into object nodes."""
    out: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                _walk(item)
            if node.get("@type"):
                out.append(node)
            return
        out.append(node)

    _walk(obj)
    return out


def extract_jsonld_from_html(html: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse application/ld+json blocks. Returns (nodes, parse_error_messages)."""
    nodes: list[dict[str, Any]] = []
    errors: list[str] = []
    safe = html if isinstance(html, str) else ""
    if not safe.strip():
        return [], []
    soup = BeautifulSoup(safe, "html.parser")
    for i, script in enumerate(soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)})):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"block[{i}]: JSON không hợp lệ ({exc.msg})")
            continue
        nodes.extend(flatten_schema_nodes(data))
    return nodes, errors


def _type_names(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if x]
    if value:
        return [str(value)]
    return []


def validate_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        json.dumps(schemas)
    except (TypeError, ValueError) as e:
        errors.append(f"json_not_serializable: {e}")
        return {"valid": False, "warnings": warnings, "errors": errors}

    for i, node in enumerate(schemas):
        if not isinstance(node, dict):
            errors.append(f"schema[{i}] must be object")
            continue
        ctx = node.get("@context")
        if ctx and ctx not in ("https://schema.org", "http://schema.org"):
            warnings.append(f"schema[{i}]: @context should be https://schema.org")
        types = _type_names(node.get("@type"))
        if not types:
            errors.append(f"schema[{i}]: missing @type")
            continue
        for t in types:
            req = _REQUIRED.get(str(t), [])
            for field in req:
                if field not in node or node[field] in (None, "", [], {}):
                    errors.append(f"schema[{i}] ({t}): missing recommended field '{field}'")

            if t == "FAQPage":
                me = node.get("mainEntity")
                if isinstance(me, list) and not me:
                    errors.append(f"schema[{i}] (FAQPage): mainEntity empty")

            if t == "Product":
                offers = node.get("offers")
                if isinstance(offers, dict) and not offers.get("price") and not offers.get("priceSpecification"):
                    warnings.append(f"schema[{i}] (Product): add price for Merchant listings")

    valid = len(errors) == 0
    return {"valid": valid, "warnings": warnings, "errors": errors}
