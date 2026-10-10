"""
Schema checks for SEO Score — syntax + page-type fit; no free 100 on wrong type.
"""

from __future__ import annotations

from typing import Any

from app.services.schema_validator import validate_schemas

_PAGE_TYPE_SCHEMA: dict[str, list[str]] = {
    "homepage": ["Organization", "WebSite", "WebPage"],
    "article": ["Article", "NewsArticle", "BlogPosting", "WebPage"],
    "category": ["CollectionPage", "WebPage", "BreadcrumbList", "ItemList"],
    "product": ["Product", "Offer", "WebPage"],
    "landing": ["WebPage", "Organization", "Product", "FAQPage"],
    "unknown": ["WebPage", "Article", "Product", "Organization", "FAQPage", "LocalBusiness"],
}


def _collect_types(ld_blocks: list[dict[str, Any]]) -> list[str]:
    types: list[str] = []
    for b in ld_blocks or []:
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t if x)
        elif t:
            types.append(str(t))
    return types


def evaluate_schema_for_page(
    ld_blocks: list[dict[str, Any]],
    *,
    page_type: str | None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ptype = (page_type or "unknown").strip().lower() or "unknown"
    val = validation if validation is not None else validate_schemas(ld_blocks or [])
    types = _collect_types(ld_blocks)
    expected = _PAGE_TYPE_SCHEMA.get(ptype, _PAGE_TYPE_SCHEMA["unknown"])
    has_ld = bool(ld_blocks)
    valid = bool(val.get("valid")) if has_ld else False
    errors = list(val.get("errors") or [])
    warnings = list(val.get("warnings") or [])

    type_match = any(t in expected for t in types) if types else False
    confidence = 0.0
    if not has_ld:
        confidence = 0.9
    elif valid and type_match:
        confidence = 0.85
    elif valid and not type_match:
        confidence = 0.6
    elif not valid and has_ld:
        confidence = 0.75
    else:
        confidence = 0.5

    if not has_ld:
        status = "FAIL"
        score_pct = 0.0
        problem = "Không có JSON-LD."
    elif not valid:
        status = "FAIL"
        score_pct = 35.0
        problem = "; ".join(errors[:3]) or "Schema JSON-LD không hợp lệ."
    elif not type_match:
        status = "WARNING"
        score_pct = 62.0
        problem = f"Schema type {', '.join(types[:4])} không khớp page type {ptype}."
    else:
        status = "PASS"
        score_pct = 100.0
        problem = ""

    return {
        "status": status,
        "score_percent": round(score_pct, 1),
        "confidence": round(confidence, 2),
        "valid": valid,
        "has_ld": has_ld,
        "types": types,
        "expected_types": expected,
        "type_match": type_match,
        "errors": errors,
        "warnings": warnings,
        "problem": problem or "—",
        "evidence": {
            "blocks": len(ld_blocks or []),
            "types_found": types[:8],
            "page_type": ptype,
        },
    }
