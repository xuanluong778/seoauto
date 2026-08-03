"""
Keyword difficulty (KD) score 0–100 from allintitle proxy, competition, volume, CPC.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

_COMP_NUM: dict[str, float] = {"Low": 0.15, "Medium": 0.5, "High": 0.85, "Unknown": 0.0}


def estimate_allintitle(keyword: str) -> int | None:
    """Deterministic proxy when live allintitle is unavailable."""
    k = (keyword or "").strip().lower()
    if not k:
        return None
    h = int(hashlib.md5(k.encode(), usedforsecurity=False).hexdigest()[:8], 16)
    return 10 + (h % 980_000)


def compute_kd(
    *,
    allintitle: int | None,
    volume: int | None,
    cpc: float | None,
    competition_label: str,
) -> dict[str, Any]:
    """
    KD = 0.4*log(allintitle+1) + 0.3*competition + 0.2*log(volume+1) + 0.1*log(cpc+1)
    Normalized to 0–100. Returns N/A when competition unknown or insufficient inputs.
    """
    if competition_label == "Unknown" or competition_label not in _COMP_NUM:
        return {"kd": None, "kd_label": "N/A", "allintitle": allintitle}
    if volume is None or allintitle is None:
        return {"kd": None, "kd_label": "N/A", "allintitle": allintitle}

    ai = max(0, int(allintitle))
    v = max(0, int(volume))
    cp = max(0.0, float(cpc or 0))
    comp = _COMP_NUM[competition_label]

    raw = (
        0.4 * math.log1p(ai)
        + 0.3 * comp
        + 0.2 * math.log1p(v)
        + 0.1 * math.log1p(cp)
    )
    raw_max = (
        0.4 * math.log1p(10_000_000)
        + 0.3 * 1.0
        + 0.2 * math.log1p(10_000_000)
        + 0.1 * math.log1p(500.0)
    )
    kd = max(0.0, min(100.0, round(100.0 * raw / raw_max, 2)))

    if kd < 30:
        label = "Easy"
    elif kd < 60:
        label = "Medium"
    else:
        label = "Hard"

    return {"kd": kd, "kd_label": label, "allintitle": ai}
