"""
Keyword difficulty (KD) score 0–100 from allintitle proxy, competition, volume, CPC.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

_COMP_NUM: dict[str, float] = {"Low": 0.15, "Medium": 0.5, "High": 0.85}


def estimate_allintitle(keyword: str) -> int:
    """Deterministic proxy when live allintitle is unavailable."""
    k = (keyword or "").strip().lower()
    if not k:
        return 0
    h = int(hashlib.md5(k.encode(), usedforsecurity=False).hexdigest()[:8], 16)
    return 10 + (h % 980_000)


def compute_kd(
    *,
    allintitle: int,
    volume: int,
    cpc: float,
    competition_label: str,
) -> dict[str, Any]:
    """
    KD = 0.4*log(allintitle+1) + 0.3*competition + 0.2*log(volume+1) + 0.1*log(cpc+1)
    Normalized to 0–100. Labels: Easy <30, Medium <60, Hard >=60.
    """
    ai = max(0, int(allintitle))
    v = max(0, int(volume))
    cp = max(0.0, float(cpc))
    comp = _COMP_NUM.get(competition_label, 0.5)

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
