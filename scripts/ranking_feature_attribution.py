"""
End-to-end ranking feature attribution for (query, URL): probability, SHAP/perm drivers, SERP alignment.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.services.attribution_engine import compute_raw_attributions
from app.services.contribution_normalizer import merge_feature_contributions, normalize_contributions
from app.services.explanation_builder import (
    build_competitor_context,
    build_explanation_groups,
    detect_misleading_signals,
    resolve_actual_rank,
)
from app.services.feature_vector_builder import build_feature_vector, vector_to_array
from app.services.model_interface import (
    AdditiveLogitSurrogateModel,
    build_default_surrogate,
    load_ranking_model_from_path,
    predict_proba_for_vector,
)


def _predicted_range(p: float) -> list[int]:
    p = max(0.02, min(0.98, float(p)))
    mu = 1.0 + (1.0 - p) ** 1.35 * 88.0
    lo = max(1, int(round(mu - 6)))
    hi = min(100, int(round(mu + 7)))
    if lo > hi:
        lo, hi = hi, lo
    return [lo, hi]


def _confidence(
    *,
    missing: list[str],
    volatility: dict[str, Any] | None,
    data_trust: dict[str, Any] | None,
) -> float:
    vol = float((volatility or {}).get("normalized_volatility") or 0.0)
    dt = dict(data_trust or {})
    fs = float(dt.get("fetch_success_rate") or 0.85)
    rc = float(dt.get("render_completeness") or 0.85)
    dup = float(dt.get("duplication_rate") or 0.15)
    trust = max(0.2, min(1.0, fs * rc * (1.0 - 0.5 * dup)))
    c = trust * (1.0 - 0.35 * vol) * (1.0 - 0.04 * min(8, len(missing)))
    return round(max(0.18, min(0.94, c)), 4)


def _align_sklearn_vector(model: Any, feature_order: list[str], x_full: np.ndarray) -> tuple[np.ndarray, str | None]:
    names = getattr(model, "feature_names_in_", None)
    if names is None:
        exp = int(getattr(model, "n_features_in_", len(feature_order)))
        if exp == len(feature_order):
            return x_full, None
        return x_full[:exp], "model_n_features_mismatch_truncated"
    name_list = [str(n) for n in list(names)]
    idx = {n: i for i, n in enumerate(feature_order)}
    vec = []
    for n in name_list:
        if n in idx:
            vec.append(float(x_full[idx[n]]))
        else:
            vec.append(0.5)
    return np.array(vec, dtype=float), None if len(vec) == len(name_list) else "partial_feature_fill"


def build_ranking_attribution_report(
    *,
    query: str,
    target_url: str,
    page_row: dict[str, Any],
    topical_row: dict[str, Any] | None = None,
    query_signals: dict[str, Any] | None = None,
    historical_row: dict[str, Any] | None = None,
    serp_ground_truth: dict[str, Any] | None = None,
    volatility: dict[str, Any] | None = None,
    data_trust: dict[str, Any] | None = None,
    ranking_decision_v3: dict[str, Any] | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """
    ``serp_ground_truth``: output slice from ``build_seo_ground_truth_bundle`` (``serp_truth.latest`` or full bundle).

    Returns the contract object including ``attribution``, ``feature_contributions``, ``confidence``.
    """
    fv_pkg = build_feature_vector(
        query=query,
        target_url=target_url,
        page_row=page_row,
        topical_row=topical_row,
        query_signals=query_signals,
        historical_row=historical_row,
    )
    order = list(fv_pkg.get("feature_order") or [])
    x_full = np.array(vector_to_array(fv_pkg, order), dtype=float)

    serp_latest = None
    if serp_ground_truth:
        serp_latest = serp_ground_truth.get("latest") or serp_ground_truth.get("serp_truth", {}).get("latest")
        if serp_latest is None and serp_ground_truth.get("results"):
            serp_latest = serp_ground_truth
    actual_rank = resolve_actual_rank(str(fv_pkg.get("target_url") or target_url), serp_latest)
    if volatility is None and isinstance(serp_ground_truth, dict):
        volatility = serp_ground_truth.get("volatility")
    if data_trust is None and isinstance(serp_ground_truth, dict):
        data_trust = serp_ground_truth.get("data_trust")

    loaded = load_ranking_model_from_path(model_path)
    model: Any = loaded or build_default_surrogate(order)
    align_note: str | None = None
    x_use = x_full
    if loaded is not None:
        x_use, align_note = _align_sklearn_vector(loaded, order, x_full)
        if align_note and align_note.startswith("model_n_features"):
            model = build_default_surrogate(order)
            x_use = x_full
            align_note = "fell_back_to_surrogate_shape_mismatch"

    p = predict_proba_for_vector(model, x_use)
    base = np.full_like(x_use, 0.5)
    raw_pkg = compute_raw_attributions(model, x_use, baseline=base, n_perm=28)
    raw_vec = raw_pkg["raw"]
    if (
        loaded is not None
        and hasattr(loaded, "feature_names_in_")
        and int(raw_vec.shape[0]) == len(list(loaded.feature_names_in_))
    ):
        names_out = [str(n) for n in list(loaded.feature_names_in_)]
    else:
        names_out = order[: int(raw_vec.shape[0])]
    raw_dict = {names_out[i]: float(raw_vec[i]) for i in range(len(names_out))}

    norm_pkg = normalize_contributions(raw_dict, names_out)
    normalized = dict(norm_pkg["normalized"])
    feature_contributions = merge_feature_contributions(normalized)

    fv = dict(fv_pkg.get("feature_vector") or {})
    attribution = build_explanation_groups(
        feature_names=names_out,
        normalized=normalized,
        raw_signed=raw_dict,
        feature_values=fv,
        page_row=page_row,
        topical_row=topical_row,
        serp_latest=serp_latest,
        query=query,
        actual_rank=actual_rank,
        ranking_probability=p,
    )

    gap_analysis = None
    if topical_row:
        gap_analysis = topical_row.get("gap_analysis") if isinstance(topical_row.get("gap_analysis"), dict) else None
    competitor_context = build_competitor_context(
        serp_latest=serp_latest,
        page_row=page_row,
        gap_analysis=gap_analysis,
    )

    misleading = detect_misleading_signals(
        top_positive=list(attribution.get("top_positive") or []),
        actual_rank=actual_rank,
        normalized=normalized,
        feature_values=fv,
        ranking_probability=p,
    )

    rng = _predicted_range(p)
    aligned = True
    notes: list[str] = []
    if actual_rank is not None:
        if actual_rank < rng[0] - 3:
            aligned = False
            notes.append(f"Observed rank {actual_rank} is stronger than predicted band {rng} — model under-estimates this query/URL pair.")
        elif actual_rank > rng[1] + 5:
            aligned = False
            notes.append(f"Observed rank {actual_rank} is weaker than predicted band {rng} — check SERP volatility, query intent, or missing off-page signals.")
    else:
        notes.append("No actual_rank in ground-truth SERP payload — prediction_vs_reality is one-sided.")

    if ranking_decision_v3 is not None:
        ps = float(ranking_decision_v3.get("ranking_probability") or 0.0)
        notes.append(f"Site-level ranking_decision_v3.probability={ps:.3f} vs local attribution model p={p:.3f} (different scopes).")

    conf = _confidence(
        missing=list(fv_pkg.get("missing_inputs") or []),
        volatility=volatility,
        data_trust=data_trust,
    )

    return {
        "ranking_probability": round(p, 4),
        "actual_rank": actual_rank,
        "predicted_range": rng,
        "attribution": attribution,
        "feature_contributions": feature_contributions,
        "confidence": conf,
        "explanation_confidence": conf,
        "misleading_signals": misleading,
        "competitor_context": competitor_context,
        "prediction_vs_reality": {
            "aligned": aligned,
            "notes": notes[:6],
        },
        "meta": {
            "attribution_method": raw_pkg.get("method"),
            "model": (
                "sklearn_loaded"
                if loaded is not None and not isinstance(model, AdditiveLogitSurrogateModel)
                else "additive_logit_surrogate"
            ),
            "align_note": align_note,
            "feature_vector_explain": fv_pkg.get("explain"),
        },
    }
