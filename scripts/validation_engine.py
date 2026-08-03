"""
Validation plans tied to Ground Truth snapshots + optional before/after rank deltas.
"""

from __future__ import annotations

from typing import Any

from app.services.ground_truth_store import iter_snapshots_for_query
from app.services.serp_fetcher import normalize_serp_url


def build_validation_plan(
    prioritized_actions: list[dict[str, Any]],
    *,
    queries: list[str],
    monitored_url: str,
    ground_truth_bundle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Each entry prescribes **which metric** to read from stored SERP snapshots after deploy.
    """
    gt = dict(ground_truth_bundle or {})
    val = dict(gt.get("validation") or {})
    base_rank = val.get("actual_best_rank")
    dt = dict(gt.get("data_trust") or {})
    q0 = (queries[0] if queries else "").strip()
    mu = normalize_serp_url((monitored_url or "").strip())

    plans: list[dict[str, Any]] = []
    for a in prioritized_actions[:18]:
        plans.append(
            {
                "action_id": a.get("action_id"),
                "issue_type": a.get("issue_type"),
                "predicted_impact_delta_prob": a.get("expected_impact_delta_prob"),
                "primary_query": q0,
                "queries_to_snapshot": [x for x in queries[:8] if str(x).strip()],
                "monitored_url": mu,
                "metric": "organic_rank_in_ground_truth_snapshots",
                "baseline": {
                    "actual_best_rank": base_rank,
                    "data_trust": dt,
                    "normalized_volatility": (gt.get("volatility") or {}).get("normalized_volatility"),
                },
                "procedure": (
                    "After deploy: re-run ``build_seo_ground_truth_bundle`` for the same queries without changing "
                    "provider/geo; compare ``validation.actual_best_rank`` and ``data_trust`` vs this baseline."
                ),
                "success_criteria": (
                    "Rank improves by ≥2 positions OR (rank within ±1 AND data_trust.fetch_success_rate "
                    "does not decrease)."
                ),
                "scheduled_window_days": 7,
            }
        )
    return plans


def _rank_in_snapshot(snap: dict[str, Any], url: str) -> int | None:
    tu = normalize_serp_url(url)
    for row in snap.get("results") or []:
        if normalize_serp_url(str(row.get("url") or "")) == tu:
            r = int(row.get("rank") or 0)
            return r if r > 0 else None
    return None


def evaluate_action_outcome(
    *,
    query: str,
    monitored_url: str,
    predicted_impact_delta_prob: float,
) -> dict[str, Any]:
    """
    Compare **oldest vs newest** stored snapshot rank for (query, url).

    ``actual_impact`` is mapped to a crude probability delta proxy from rank delta.
    """
    snaps = iter_snapshots_for_query(query)
    if len(snaps) < 2:
        return {
            "predicted_impact": predicted_impact_delta_prob,
            "actual_impact": None,
            "success": False,
            "explain": "Need at least two persisted snapshots to validate rank movement.",
        }

    r_old = _rank_in_snapshot(snaps[0], monitored_url)
    r_new = _rank_in_snapshot(snaps[-1], monitored_url)
    if r_old is None or r_new is None:
        return {
            "predicted_impact": predicted_impact_delta_prob,
            "actual_impact": None,
            "success": False,
            "explain": "URL missing from first or last snapshot — widen top_n or verify URL canonicalization.",
            "r_old": r_old,
            "r_new": r_new,
        }

    delta = float(r_old - r_new)
    # Map rank improvement (positive delta) to rough probability mass proxy
    actual_proxy = round(max(-0.15, min(0.2, delta * 0.012)), 4)
    success = delta >= 2.0 or (abs(delta) <= 1.0 and r_new <= 15)

    return {
        "predicted_impact": predicted_impact_delta_prob,
        "actual_impact": actual_proxy,
        "success": bool(success),
        "rank_before": r_old,
        "rank_after": r_new,
        "explain": "actual_impact is a conservative proxy from rank delta ×0.012 (not a calibrated production metric).",
    }
