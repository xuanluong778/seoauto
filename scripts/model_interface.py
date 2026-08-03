"""
Ranking model interface: optional serialized sklearn model, or calibrated additive logit surrogate.

The surrogate is **explicit** (coefficients + intercept) so attributions can be audited without SHAP.
"""

from __future__ import annotations

import math
import os
import pickle
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


class RankingModelProtocol(Protocol):
    feature_names_in_: np.ndarray | list[str]  # type: ignore[misc]

    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...


# Surrogate weights loosely aligned with ``build_site_ranking_decision_v3`` signal mix (on-page + topical + trust).
_DEFAULT_COEF: dict[str, float] = {
    "content_quality": 2.35,
    "topical_authority": 2.05,
    "entity_match": 0.85,
    "intent_match": 1.95,
    "internal_linking": 1.15,
    "page_speed": 0.75,
    "serp_alignment": 1.85,
    "domain_authority_proxy": 1.05,
    "trust_score": 1.25,
    "indexability": 2.65,
    "technical_health": 1.45,
    "keyword_query_fit": 1.05,
    "historical_momentum": 0.55,
}
_SURROGATE_INTERCEPT = -3.35


@dataclass
class AdditiveLogitSurrogateModel:
    """Interpretable ``sigmoid(intercept + coef · x)`` with named features."""

    feature_names: list[str]
    coef_: np.ndarray
    intercept_: float

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        z = self.intercept_ + X @ self.coef_.reshape(-1, 1)
        z = np.clip(z, -22.0, 22.0)
        p = 1.0 / (1.0 + np.exp(-z))
        out = np.column_stack([1.0 - p, p])
        return np.asarray(out, dtype=float)


def build_default_surrogate(feature_order: list[str]) -> AdditiveLogitSurrogateModel:
    coefs = np.array([float(_DEFAULT_COEF.get(n, 0.5)) for n in feature_order], dtype=float)
    return AdditiveLogitSurrogateModel(
        feature_names=list(feature_order),
        coef_=coefs,
        intercept_=float(_SURROGATE_INTERCEPT),
    )


def load_ranking_model_from_path(path: str | None) -> Any | None:
    """
    Load ``pickle``/``joblib`` sklearn estimator with ``predict_proba`` and ``feature_names_in_``.

    Set ``RANKING_MODEL_PATH`` to enable; columns must match training order (caller aligns).
    """
    p = (path or os.getenv("RANKING_MODEL_PATH") or "").strip()
    if not p:
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        try:
            import joblib

            return joblib.load(p)
        except Exception:
            return None


def predict_proba_for_vector(model: Any, x_row: np.ndarray) -> float:
    """Positive class probability (ranking viability) for one row."""
    X = np.asarray(x_row, dtype=float).reshape(1, -1)
    if hasattr(model, "predict_proba"):
        pr = model.predict_proba(X)
        arr = np.asarray(pr, dtype=float)
        if arr.shape[1] >= 2:
            return float(arr[0, 1])
        return float(arr[0, 0])
    if hasattr(model, "decision_function"):
        df = float(np.asarray(model.decision_function(X), dtype=float).ravel()[0])
        return float(1.0 / (1.0 + math.exp(-np.clip(df, -22, 22))))
    raise TypeError("Model must implement predict_proba or decision_function")
