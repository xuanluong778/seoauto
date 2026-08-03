"""
JSON-LD shape checks + required-field heuristics for common rich-result types.
"""

from __future__ import annotations

import json
from typing import Any


_REQUIRED: dict[str, list[str]] = {
    "Article": ["headline", "author"],
    "FAQPage": ["mainEntity"],
    "HowTo": ["name", "step"],
    "Product": ["name", "offers"],
    "Review": ["itemReviewed", "reviewBody", "author"],
    "BreadcrumbList": ["itemListElement"],
    "WebPage": ["url", "name"],
}


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
        if node.get("@context") != "https://schema.org":
            warnings.append(f"schema[{i}]: @context should be https://schema.org")
        t = node.get("@type")
        if not t:
            errors.append(f"schema[{i}]: missing @type")
            continue
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
