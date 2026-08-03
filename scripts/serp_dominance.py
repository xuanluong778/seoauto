"""
SERP dominance and volatility: how strongly one content type wins, and how stable the mix is.
"""

from __future__ import annotations

import math
from typing import Any


def compute_serp_dominance(serp_classifier_pkg: dict[str, Any] | None) -> dict[str, Any]:
    """
    High ``serp_dominance_score`` → strong constraint (winners look alike).
    High ``serp_volatility`` → heterogeneous SERP → lower confidence in single template.
    """
    pkg = dict(serp_classifier_pkg or {})
    tdist = dict(pkg.get("type_distribution") or {})
    if not tdist:
        return {
            "serp_dominance_score": 0.45,
            "dominant_type": str(pkg.get("serp_dominant_type") or "blog"),
            "serp_volatility": 0.55,
            "explain": "No SERP type distribution — neutral prior.",
        }

    total = sum(float(v) for v in tdist.values()) or 1.0
    shares = {k: float(v) / total for k, v in tdist.items()}
    dom_share = max(shares.values()) if shares else 0.0
    dominance = round(min(1.0, 0.35 + 0.85 * dom_share), 4)

    # Normalized entropy of type mix → volatility
    h = 0.0
    for p in shares.values():
        if p > 1e-9:
            h -= p * math.log(p + 1e-12)
    h_max = math.log(max(2, len(shares)))
    ent_norm = h / h_max if h_max > 0 else 0.0
    volatility = round(min(1.0, ent_norm * 0.95 + 0.05 * (1.0 - dom_share)), 4)

    dom_type = max(shares, key=lambda k: shares[k]) if shares else str(pkg.get("serp_dominant_type") or "blog")

    return {
        "serp_dominance_score": dominance,
        "dominant_type": dom_type,
        "serp_volatility": volatility,
        "type_shares": {k: round(v, 3) for k, v in shares.items()},
        "explain": "Dominance from max type share; volatility from entropy + anti-dominance.",
    }
