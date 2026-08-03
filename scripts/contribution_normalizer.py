"""
Map raw attribution values to normalized contributions and percentage impact shares.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def normalize_contributions(
    raw: dict[str, float] | np.ndarray,
    feature_names: list[str],
    *,
    eps: float = 1e-9,
) -> dict[str, Any]:
    """
    ``raw`` may be a dict name→value or parallel array to ``feature_names``.

    Returns:
      - ``normalized``: each in [-1, 1] by dividing by max absolute (or vector L2)
      - ``percent_impact``: share of |value| (sums to ~1)
    """
    if isinstance(raw, dict):
        vals = np.array([float(raw.get(n, 0.0)) for n in feature_names], dtype=float)
    else:
        arr = np.asarray(raw, dtype=float).ravel()
        vals = arr[: len(feature_names)]
        if vals.shape[0] < len(feature_names):
            vals = np.pad(vals, (0, len(feature_names) - vals.shape[0]))

    m = float(np.max(np.abs(vals))) or 1.0
    norm = vals / m
    norm = np.clip(norm, -1.0, 1.0)

    denom = float(np.sum(np.abs(vals))) + eps
    pct = np.abs(vals) / denom

    return {
        "normalized": {feature_names[i]: round(float(norm[i]), 4) for i in range(len(feature_names))},
        "percent_impact": {feature_names[i]: round(float(pct[i]), 4) for i in range(len(feature_names))},
        "scale_max_abs": round(m, 6),
        "explain": "normalized = raw / max|raw|; percent_impact = |raw_i| / sum|raw|.",
    }


def merge_feature_contributions(
    normalized: dict[str, float],
) -> dict[str, float]:
    """Flat map for API output (contribution_score = normalized signed mass)."""
    return {k: round(float(v), 4) for k, v in normalized.items()}
