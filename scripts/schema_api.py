"""
Orchestrate: parse → SERP (optional) → detect types → generate → optimize → validate → alignment.
"""

from __future__ import annotations

import html as html_module
import re
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.content_parser import parse_page_content
from app.services.schema_generator import generate_schemas
from app.services.schema_optimizer import optimize_schemas
from app.services.schema_type_detector import detect_schema_types
from app.services.schema_validator import validate_schemas
from app.services.search_intent import classify_search_intent
from app.services.serp_alignment_engine import build_serp_alignment
from app.services.serp_features import detect_serp_features
from app.services.serp_fetcher import fetch_serp


def _strip_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(x) for x in obj]
    return obj


def _fetch_html(url: str) -> tuple[str, str | None]:
    u = (url or "").strip()
    if not u.startswith("http"):
        return "", "url_must_be_http_https"
    try:
        r = requests.get(
            u,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SchemaGenerator/1.1; +https://schema.org/docs)"},
        )
        if r.status_code >= 400:
            return "", f"http_{r.status_code}"
        return r.text or "", None
    except requests.RequestException as e:
        return "", f"fetch_error:{e.__class__.__name__}"


def _infer_serp_formats(features: dict[str, Any], serp_results: list[dict[str, Any]]) -> list[str]:
    fmt: list[str] = []
    if features.get("has_faq"):
        fmt.append("faq")
    if features.get("has_video"):
        fmt.append("video")
    blob = " ".join(
        f"{r.get('title','')} {r.get('snippet','')}" for r in serp_results[:12]
    ).lower()
    if re.search(r"\b(how to|steps?|hướng dẫn|tutorial)\b", blob):
        fmt.append("guide")
    if re.search(r"\b(review|rating|vs\.?|compare)\b", blob):
        fmt.append("review")
    return list(dict.fromkeys(fmt))


def _infer_serp_dominant(formats: list[str], features: dict[str, Any], commercial_hint: bool) -> str:
    if commercial_hint:
        return "ecommerce"
    if "faq" in formats or features.get("has_faq"):
        return "informational_faq"
    if "guide" in formats:
        return "informational_guide"
    if features.get("has_featured_snippet"):
        return "informational_definition"
    return "mixed"


def _pick_primary(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    priority = ("FAQPage", "Product", "HowTo", "Article", "Review", "WebPage", "WebSite", "Organization")
    for t in priority:
        for s in schemas:
            if s.get("@type") == t:
                return s
    return schemas[0] if schemas else {}


def build_schema_generator_response(
    *,
    url: str | None = None,
    html: str | None = None,
    text: str | None = None,
    seed_keyword: str | None = None,
    fetch_serp_flag: bool = True,
) -> dict[str, Any]:
    """
    Exactly one of ``url``, ``html``, or ``text`` should be non-empty for best results.
    ``url`` is used as canonical @id when HTML/text is supplied without a real page URL.
    """
    page_url = (url or "").strip()
    raw_html = (html or "").strip()
    err: str | None = None

    if raw_html:
        pass
    elif (text or "").strip():
        esc = html_module.escape((text or "")[:200_000])
        raw_html = (
            "<!DOCTYPE html><html><head><title>Provided text</title></head>"
            f"<body><pre>{esc}</pre></body></html>"
        )
        if not page_url:
            page_url = "https://example.com/user-supplied-text"
    elif page_url:
        raw_html, ferr = _fetch_html(page_url)
        if ferr:
            err = ferr
            raw_html = ""
    else:
        return {
            "ok": False,
            "error": "Provide url, html, or text",
            "schemas": [],
            "primary_schema": {},
            "validation": {"valid": False, "warnings": [], "errors": ["missing_input"]},
            "serp_alignment": {},
        }

    if not raw_html:
        return {
            "ok": False,
            "error": err or "empty_html",
            "schemas": [],
            "primary_schema": {},
            "validation": {"valid": False, "warnings": [], "errors": [err or "no_content"]},
            "serp_alignment": {},
            "page_url": page_url or None,
        }

    parsed = parse_page_content(raw_html, base_url=page_url or "")
    if parsed.get("title") in ("", "Provided text") and (text or "").strip():
        parsed["title"] = ((text or "").strip()[:120] + "…") if len((text or "").strip()) > 120 else (text or "").strip()

    kw = (seed_keyword or "").strip() or (parsed.get("title") or "").strip()
    if not kw and page_url:
        kw = (urlparse(page_url).path or "/").replace("/", " ").strip() or "page"

    intent_pkg = classify_search_intent(kw)
    page_intent = str(intent_pkg.get("intent") or "informational")

    serp_payload: dict[str, Any] = {}
    features: dict[str, Any] = {}
    serp_formats: list[str] = []
    serp_dominant = "mixed"
    commercial_hint = False

    if fetch_serp_flag and kw:
        try:
            serp_payload = fetch_serp(kw, num=10)
            organic = list(serp_payload.get("serp_results") or [])
            features = detect_serp_features(serp_payload)
            blob = " ".join(f"{r.get('title','')} {r.get('snippet','')}" for r in organic[:12]).lower()
            commercial_hint = bool(re.search(r"\b(buy|price|shop|cart|deal|\$\s?\d|€\s?\d)\b", blob))
            features = {**features, "commercial_organic_hint": commercial_hint}
            serp_formats = _infer_serp_formats(features, organic)
            serp_dominant = _infer_serp_dominant(serp_formats, features, commercial_hint)
        except Exception as e:  # noqa: BLE001
            serp_payload = {"fetch_error": str(e)}

    types = detect_schema_types(
        parsed,
        page_url=page_url or None,
        page_intent=page_intent,
        serp_dominant_type=serp_dominant,
        serp_formats=serp_formats,
    )

    canonical_url = page_url or parsed.get("url") or "https://example.com/page"
    schemas = generate_schemas(types, parsed, page_url=canonical_url)
    schemas = optimize_schemas(schemas, parsed)
    schemas = [_strip_nulls(s) for s in schemas]
    validation = validate_schemas(schemas)
    serp_alignment = build_serp_alignment(
        schema_types=[str(s.get("@type")) for s in schemas],
        serp_formats=serp_formats,
        serp_dominant=serp_dominant,
        serp_features=features,
    )

    primary = _pick_primary(schemas)

    return {
        "ok": True,
        "page_url": canonical_url,
        "detected_types": types,
        "page_intent": page_intent,
        "intent_reasoning": intent_pkg.get("reasoning"),
        "serp_keyword_used": kw,
        "serp_dominant_type": serp_dominant,
        "serp_formats": serp_formats,
        "schemas": schemas,
        "primary_schema": primary,
        "validation": validation,
        "serp_alignment": serp_alignment,
        "parsed_summary": {
            "title": parsed.get("title"),
            "sections": parsed.get("sections"),
            "headings_count": {k: len(v or []) for k, v in (parsed.get("headings") or {}).items()},
        },
    }
