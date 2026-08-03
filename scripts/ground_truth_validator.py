"""
Compare site-level ``ranking_decision_v3`` style payloads with observed SERP positions.

This does not claim causal attribution; it measures **alignment** between a coarse
probability and URL-level SERP reality for monitoring and calibration.
"""

from __future__ import annotations

from typing import Any

from app.services.serp_fetcher import normalize_serp_url


def _expected_strength_from_rank(rank: int | None) -> float:
    if rank is None:
        return 0.12
    if rank <= 3:
        return 0.9
    if rank <= 10:
        return 0.72
    if rank <= 20:
        return 0.55
    if rank <= 50:
        return 0.35
    return 0.18


def validate_ranking_decision_vs_serp(
    ranking_decision: dict[str, Any] | None,
    *,
    target_url: str | None,
    serp_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    ``ranking_decision``: output of ``build_site_ranking_decision_v3`` (or compatible dict).

    ``serp_results``: normalized organic rows with ``rank`` + ``url``.

    Returns ``prediction_error``, ``ranking_accuracy`` (heuristic 0/1), ``misalignment_reasons``.
    """
    if not ranking_decision:
        return {
            "prediction_error": None,
            "ranking_accuracy": None,
            "misalignment_reasons": ["no_ranking_decision_provided"],
            "actual_best_rank": None,
            "explain": "Validator skipped — no model decision payload.",
        }

    prob = float(ranking_decision.get("ranking_probability") or 0.0)
    will_rank = bool(ranking_decision.get("will_rank"))

    tu = normalize_serp_url(str(target_url or "").strip()) if target_url else ""
    rank: int | None = None
    if tu:
        for row in serp_results:
            if normalize_serp_url(str(row.get("url") or "")) == tu:
                rank = int(row.get("rank") or 999)
                break
        if rank and rank >= 999:
            rank = None
    else:
        rank = None

    exp = _expected_strength_from_rank(rank)
    prediction_error = round(abs(prob - exp), 4)

    reasons: list[str] = []
    acc = 1
    if tu:
        if will_rank and rank is None:
            acc = 0
            reasons.append("Model predicts viable ranking surface but monitored URL not in captured SERP depth.")
        elif will_rank and rank and rank > 40:
            acc = 0
            reasons.append("Model optimistic (will_rank) vs deep rank for monitored URL.")
        elif (not will_rank) and rank and rank <= 8:
            acc = 0
            reasons.append("Model conservative (not will_rank) but monitored URL ranks top 8 — possible niche/geo slice.")
        if rank and rank > 20 and float(ranking_decision.get("components", {}).get("mean_serp_alignment") or 0) > 0.65:
            reasons.append("High declared SERP alignment vs mediocre observed rank for URL — check SERP sample / intent drift.")
        if rank is None and prob > 0.62:
            reasons.append("High ranking_probability but URL absent — verify indexation, query match, or SERP provider coverage.")
    else:
        reasons.append("No target_url — URL-level accuracy not evaluated; site-level decision only noted.")
        acc = None

    return {
        "prediction_error": prediction_error,
        "ranking_accuracy": acc,
        "misalignment_reasons": reasons[:8] or ["no_material_misalignment_detected"],
        "actual_best_rank": rank,
        "expected_strength_from_serp": exp,
        "explain": (
            "prediction_error = |ranking_probability - expected_strength_from_serp(rank)| "
            "where expected_strength is a monotone mapping from observed best rank; "
            "ranking_accuracy is a coarse 0/1 heuristic when target_url is provided."
        ),
    }
