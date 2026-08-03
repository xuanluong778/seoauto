"""
Unified SEO ground-truth bundle: SERP reality, history, intent, volatility, trust, validation.
"""

from __future__ import annotations

from typing import Any

from app.services.ground_truth_store import append_snapshot, append_validation_event, iter_snapshots_for_query
from app.services.ground_truth_validator import validate_ranking_decision_vs_serp
from app.services.feedback_loop_engine import run_feedback_loop
from app.services.intent_ground_truth_engine import build_intent_truth_from_snapshots
from app.services.ranking_history_engine import build_ranking_history_bundle, compute_serp_volatility_entropy
from app.services.serp_ground_truth_collector import collect_serp_ground_truth
from app.services.serp_normalizer import normalize_ground_truth_snapshot


def build_seo_ground_truth_bundle(
    query: str,
    *,
    target_url: str | None = None,
    ranking_decision_v3: dict[str, Any] | None = None,
    top_n: int | None = None,
    redundancy: bool | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    End-to-end orchestration returning:

    ``serp_truth``, ``ranking_history``, ``intent_truth``, ``volatility``,
    ``data_trust``, ``validation``, ``feedback``.
    """
    raw = collect_serp_ground_truth(query, top_n=top_n, redundancy=redundancy)
    normalized = normalize_ground_truth_snapshot(raw)

    if persist:
        append_snapshot(query, normalized)

    history_snaps = iter_snapshots_for_query(query)
    if not history_snaps:
        history_snaps = [normalized]

    ranking_history = build_ranking_history_bundle(history_snaps, query=query)
    intent_truth = build_intent_truth_from_snapshots(history_snaps, top_n=10)
    volatility = compute_serp_volatility_entropy(history_snaps, top_k=10)

    validation = validate_ranking_decision_vs_serp(
        ranking_decision_v3,
        target_url=target_url,
        serp_results=list(normalized.get("results") or []),
    )

    if persist and ranking_decision_v3 is not None:
        append_validation_event(
            {
                "query": query,
                "timestamp": normalized.get("timestamp"),
                "prediction_error": validation.get("prediction_error"),
                "ranking_accuracy": validation.get("ranking_accuracy"),
                "misalignment_reasons": validation.get("misalignment_reasons"),
                "target_url": target_url,
            }
        )

    feedback_loop = run_feedback_loop()

    serp_truth = {
        "latest": normalized,
        "historical_snapshots": len(history_snaps),
        "collector_meta": raw.get("collector_meta"),
        "explain": "latest = normalized SERP snapshot; history count from on-disk JSONL store.",
    }

    validation_out = dict(validation)
    validation_out["feedback_loop"] = feedback_loop

    return {
        "serp_truth": serp_truth,
        "ranking_history": ranking_history,
        "intent_truth": intent_truth,
        "volatility": volatility,
        "data_trust": raw.get("data_trust") or {},
        "validation": validation_out,
    }
