"""
Keyword-level intent using SERP Ground Truth when enabled; else lexical fallback.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.search_intent import classify_search_intent


def classify_keyword_intent(
    keyword: str,
    *,
    brand_terms: set[str] | None = None,
    use_serp_ground_truth: bool | None = None,
) -> dict[str, Any]:
    """
    ``use_serp_ground_truth``: defaults from env ``KEYWORD_INTENT_USE_SERP_GT`` (1 = on).

    When on, runs a single (non-persisted) ground-truth bundle for ``keyword`` and uses
    ``intent_truth.dominant_intent`` as primary label.
    """
    kw = (keyword or "").strip()
    if not kw:
        return {"keyword": "", "intent": "informational", "confidence": 0.0, "source": "empty"}

    serp_on = use_serp_ground_truth
    if serp_on is None:
        serp_on = os.getenv("KEYWORD_INTENT_USE_SERP_GT", "1").lower() in ("1", "true", "yes")

    if serp_on:
        try:
            from app.services.seo_ground_truth_bundle import build_seo_ground_truth_bundle

            gt = build_seo_ground_truth_bundle(
                kw,
                target_url=None,
                ranking_decision_v3=None,
                persist=False,
                redundancy=False,
            )
            it = dict(gt.get("intent_truth") or {})
            dom = str(it.get("dominant_intent") or "").strip()
            stab = float(it.get("intent_stability_score") or 0.5)
            if dom:
                return {
                    "keyword": kw,
                    "intent": dom,
                    "confidence": round(max(0.35, min(0.92, 0.45 + 0.5 * stab)), 3),
                    "source": "serp_ground_truth",
                    "intent_distribution": it.get("intent_distribution"),
                    "explain": "Dominant intent from SERP-derived ``intent_truth`` (top organic rows), not query-only guess.",
                }
        except Exception:
            pass

    pkg = classify_search_intent(kw, brand_terms=brand_terms)
    return {
        "keyword": kw,
        "intent": str(pkg.get("intent") or "informational"),
        "confidence": float(pkg.get("confidence") or 0.5),
        "source": "nlp_fallback",
        "explain": "; ".join(pkg.get("reasoning") or [])[:400],
    }


def classify_keywords_batch(
    keywords: list[str],
    *,
    brand_terms: set[str] | None = None,
    max_serp_gt: int | None = None,
) -> list[dict[str, Any]]:
    """
    Applies SERP GT to the first ``max_serp_gt`` keywords (default env or 10), rest NLP-only (latency).
    """
    lim = max_serp_gt if max_serp_gt is not None else int(os.getenv("KEYWORD_INTENT_MAX_SERP_GT", "10"))
    out: list[dict[str, Any]] = []
    for i, kw in enumerate(keywords):
        use_gt = i < lim
        out.append(
            classify_keyword_intent(
                kw,
                brand_terms=brand_terms,
                use_serp_ground_truth=use_gt,
            )
        )
    return out
