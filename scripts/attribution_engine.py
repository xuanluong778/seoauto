"""
Feature attribution: SHAP TreeExplainer when available, else exact surrogate gradient or permutation.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from app.services.model_interface import AdditiveLogitSurrogateModel, predict_proba_for_vector

_LOG = logging.getLogger(__name__)


def _sigmoid(z: float) -> float:
    return float(1.0 / (1.0 + math.exp(-np.clip(z, -22.0, 22.0))))


def _tree_shap_values(model: Any, X: np.ndarray) -> np.ndarray | None:
    try:
        import shap  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X)
        if hasattr(sv, "values"):
            sv = sv.values
        if isinstance(sv, list):
            sv = sv[1] if len(sv) > 1 else sv[0]
        arr = np.asarray(sv, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr[0]
    except Exception as exc:
        _LOG.debug("TreeExplainer failed: %s", exc)
        return None


def permutation_attributions(
    model: Any,
    x: np.ndarray,
    baseline: np.ndarray,
    *,
    n_repeat: int = 20,
) -> np.ndarray:
    """
    Positive value ⇒ restoring feature from baseline toward ``x`` **increases** ``p`` (helps ranking probability).
    """
    x = np.asarray(x, dtype=float).ravel()
    b = np.asarray(baseline, dtype=float).ravel()
    d = x.shape[0]
    px = predict_proba_for_vector(model, x)
    out = np.zeros(d, dtype=float)
    for i in range(d):
        acc = 0.0
        for _ in range(max(3, n_repeat)):
            xb = x.copy()
            xb[i] = b[i]
            pi = predict_proba_for_vector(model, xb)
            acc += px - pi
        out[i] = acc / max(3, n_repeat)
    return out


def surrogate_linear_shap(
    model: AdditiveLogitSurrogateModel,
    x: np.ndarray,
    baseline: np.ndarray,
) -> np.ndarray:
    """
    Exact linear SHAP for logistic link on affine score: ``phi_i ≈ w_i (x_i - b_i) * p(1-p)``
    evaluated at ``x`` (local explanation — sum approximates delta logit contribution).
    """
    x = np.asarray(x, dtype=float).ravel()
    b = np.asarray(baseline, dtype=float).ravel()
    w = np.asarray(model.coef_, dtype=float).ravel()
    z = float(model.intercept_ + float(np.dot(w, x)))
    p = _sigmoid(z)
    g = p * (1.0 - p)
    return w * (x - b) * g


def compute_raw_attributions(
    model: Any,
    x_row: np.ndarray,
    *,
    baseline: np.ndarray | None = None,
    feature_names: list[str] | None = None,
    prefer_shap_tree: bool = True,
    n_perm: int = 24,
) -> dict[str, Any]:
    """
    Returns ``{ "raw": np.ndarray, "method": str, "baseline": np.ndarray }``.
    """
    x_row = np.asarray(x_row, dtype=float).ravel()
    d = x_row.shape[0]
    base = np.asarray(baseline if baseline is not None else np.full(d, 0.5), dtype=float).ravel()

    if prefer_shap_tree:
        sv = _tree_shap_values(model, x_row.reshape(1, -1))
        if sv is not None and sv.shape[0] == d:
            return {"raw": sv.astype(float), "method": "shap_tree", "baseline": base}

    if isinstance(model, AdditiveLogitSurrogateModel):
        raw = surrogate_linear_shap(model, x_row, base)
        return {"raw": raw, "method": "surrogate_linear_local", "baseline": base}

    raw = permutation_attributions(model, x_row, base, n_repeat=n_perm)
    return {"raw": raw, "method": "permutation", "baseline": base}
