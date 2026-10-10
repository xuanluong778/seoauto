"""
Search intent analysis for SEO Score — SERP Top 10 evidence with confidence.
"""

from __future__ import annotations

from typing import Any

from app.services.search_intent import classify_search_intent
from app.services.serp_intent_classifier import classify_serp_results

_INTENTS = ("informational", "commercial", "transactional", "navigational", "local", "mixed", "unknown")

_PAGE_TYPE_EXPECTED: dict[str, set[str]] = {
    "homepage": {"navigational", "commercial", "informational", "mixed"},
    "article": {"informational", "commercial", "mixed"},
    "category": {"commercial", "informational", "navigational", "mixed"},
    "product": {"transactional", "commercial", "mixed"},
    "landing": {"transactional", "commercial", "mixed"},
    "unknown": set(_INTENTS),
}


def _page_intent_from_signals(
    *,
    page_type: str,
    title: str,
    body_text: str,
    keyword: str | None,
) -> dict[str, Any]:
    blob = " ".join(x for x in (title, body_text[:1200], keyword or "") if x).strip()
    pkg = classify_search_intent(blob or (keyword or ""))
    intent = str(pkg.get("intent") or "unknown").lower()
    conf = float(pkg.get("confidence") or 0.5)
    if page_type == "product" and intent in ("informational", "unknown"):
        intent = "transactional"
        conf = max(conf, 0.55)
    if page_type == "article" and intent == "unknown":
        intent = "informational"
        conf = max(conf, 0.5)
    return {"intent": intent, "confidence": round(min(1.0, conf), 2), "source": "page_heuristic"}


def analyze_search_intent(
    *,
    keyword: str | None,
    page_type: str | None,
    title: str,
    body_text: str,
    serp_rows: list[dict[str, Any]] | None,
    page_intent_breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compare page intent vs SERP dominant intent.
    Low confidence → warning path, never hard fail.
    """
    pk = (keyword or "").strip()
    ptype = (page_type or "unknown").strip().lower() or "unknown"
    page_intent = page_intent_breakdown or _page_intent_from_signals(
        page_type=ptype,
        title=title,
        body_text=body_text,
        keyword=pk or None,
    )
    pi = str(page_intent.get("intent") or "unknown").lower()
    page_conf = float(page_intent.get("confidence") or 0.5)

    serp_pkg = classify_serp_results(serp_rows or []) if serp_rows else None
    if not serp_pkg or not serp_rows:
        return {
            "dominant_intent": pi if pk else "unknown",
            "page_intent": pi,
            "serp_intent": "unknown",
            "confidence": round(min(page_conf, 0.45), 2),
            "serp_confidence": 0.0,
            "intent_distribution": {},
            "serp_sample_size": 0,
            "page_type": ptype,
            "mismatch": False,
            "mismatch_reason": "Chưa có dữ liệu SERP Top 10." if pk else "Chưa nhập keyword.",
            "status": "UNKNOWN",
            "evidence": {"serp_rows": 0, "keyword": pk},
        }

    serp_intent = str(serp_pkg.get("serp_intent") or "unknown").lower()
    dist = dict(serp_pkg.get("intent_distribution") or {})
    sample = min(len(serp_rows or []), 12)
    serp_conf = 0.0
    if dist and serp_intent in dist:
        serp_conf = float(dist.get(serp_intent) or 0)
    elif sample >= 5:
        serp_conf = 0.55
    elif sample >= 3:
        serp_conf = 0.45
    else:
        serp_conf = 0.35
    serp_conf = round(min(1.0, serp_conf + min(0.15, sample * 0.01)), 2)

    expected = _PAGE_TYPE_EXPECTED.get(ptype, _PAGE_TYPE_EXPECTED["unknown"])
    mismatch = pi not in (serp_intent, "unknown") and serp_intent not in (pi, "unknown", "mixed")
    if pi in expected and serp_intent in expected:
        mismatch = False
    mismatch_reason = ""
    if mismatch:
        mismatch_reason = f"Trang thiên {pi} nhưng SERP Top 10 thiên {serp_intent}."
    elif pi == "unknown" or serp_intent == "unknown":
        mismatch_reason = "Intent trang hoặc SERP chưa đủ tín hiệu."

    combined_conf = round(min(1.0, (page_conf + serp_conf) / 2), 2)
    if not mismatch:
        status = "PASS" if combined_conf >= 0.55 else "WARNING"
    elif combined_conf < 0.45:
        status = "WARNING"
    else:
        status = "WARNING"  # accuracy-first: never hard FAIL on intent alone

    return {
        "dominant_intent": serp_intent,
        "page_intent": pi,
        "serp_intent": serp_intent,
        "confidence": combined_conf,
        "serp_confidence": serp_conf,
        "page_confidence": round(page_conf, 2),
        "intent_distribution": dist,
        "serp_sample_size": sample,
        "page_type": ptype,
        "mismatch": mismatch,
        "mismatch_reason": mismatch_reason or "—",
        "status": status,
        "evidence": {
            "keyword": pk,
            "serp_dominant_type": serp_pkg.get("serp_dominant_type"),
            "serp_formats": serp_pkg.get("serp_formats"),
            "type_distribution": serp_pkg.get("type_distribution"),
            "explain": serp_pkg.get("explain"),
        },
    }
