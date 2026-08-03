"""
Build URL×query ranking histories, volatility, and coarse trends from stored SERP snapshots.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any


def _parse_ts(s: str) -> float | None:
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs) or 1e-9
    return num / den


def _shannon_entropy(counts: dict[str, int]) -> float:
    tot = sum(counts.values())
    if tot <= 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / tot
        h -= p * math.log(p + 1e-12, 2)
    return h


def compute_serp_volatility_entropy(snapshots: list[dict[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    """
    Entropy-based volatility: at each rank slot 1..K, measure entropy of the domain
    observed across snapshots. High mean entropy ⇒ unstable winner mix.
    """
    if not snapshots:
        return {
            "mean_rank_slot_entropy": 0.0,
            "normalized_volatility": 0.0,
            "per_rank_entropy": [],
            "explain": "No snapshots — volatility undefined.",
        }

    from urllib.parse import urlparse

    def dom(url: str) -> str:
        try:
            h = (urlparse(url).hostname or "").lower()
            return h[4:] if h.startswith("www.") else h
        except Exception:
            return ""

    per_rank: list[dict[str, Any]] = []
    entropies: list[float] = []
    for r in range(1, top_k + 1):
        counts: dict[str, int] = defaultdict(int)
        for snap in snapshots:
            row = None
            for x in snap.get("results") or []:
                if int(x.get("rank") or 0) == r:
                    row = x
                    break
            if not row:
                counts["__empty__"] += 1
                continue
            d = dom(str(row.get("url") or "")) or "__unknown__"
            counts[d] += 1
        h = _shannon_entropy(dict(counts))
        entropies.append(h)
        per_rank.append({"rank": r, "entropy_bits": round(h, 4), "distinct_domains": len(counts)})

    mean_h = sum(entropies) / len(entropies)
    max_h = math.log(max(2, min(32, max(len(snapshots), 2))), 2)
    norm = round(min(1.0, mean_h / max_h), 4) if max_h > 0 else 0.0

    return {
        "mean_rank_slot_entropy": round(mean_h, 4),
        "normalized_volatility": norm,
        "per_rank_entropy": per_rank,
        "explain": (
            "For each rank 1..K, Shannon entropy (bits) of domain identity across snapshots; "
            "normalized_volatility scales mean entropy by log2(min(32, num_snapshots))."
        ),
    }


def build_ranking_history_bundle(
    snapshots: list[dict[str, Any]],
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """
    Input: normalized snapshots (``results`` with ``rank``, ``url``).

    Output includes per-URL history, per-URL volatility (std of ranks), and trend label.
    """
    q = (query or (snapshots[0].get("query") if snapshots else "") or "").strip()

    series: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for snap in snapshots:
        ts = str(snap.get("timestamp") or "")
        for row in snap.get("results") or []:
            u = str(row.get("url") or "").strip()
            if not u:
                continue
            series[u].append((ts, int(row.get("rank") or 999)))

    items: list[dict[str, Any]] = []
    for url, hist in series.items():
        hist_sorted = sorted(hist, key=lambda t: t[0])
        ranks_only = [p for _, p in hist_sorted]
        xs = [_parse_ts(t) or float(i) for i, (t, _) in enumerate(hist_sorted)]
        ys = [float(p) for p in ranks_only]

        vol = 0.0
        if len(ranks_only) >= 2:
            try:
                vol = float(statistics.pstdev(ranks_only))
            except statistics.StatisticsError:
                vol = 0.0
        vol_norm = round(min(1.0, vol / 25.0), 4)

        slope = _linear_slope(xs, ys)
        trend = "stable"
        if len(hist_sorted) >= 2:
            if slope < -0.02:
                trend = "up"
            elif slope > 0.02:
                trend = "down"

        items.append(
            {
                "url": url,
                "query": q,
                "ranking_history": [{"date": t, "position": p} for t, p in hist_sorted],
                "volatility_score": vol_norm,
                "volatility_rank_std": round(vol, 4),
                "trend": trend,
                "trend_slope": round(slope, 6),
                "explain": (
                    "trend uses OLS slope of numeric time vs rank (lower rank is better): "
                    "negative slope ⇒ improving average position; volatility_score scales std dev of ranks."
                ),
            }
        )

    items.sort(key=lambda x: (x["volatility_score"], len(x["ranking_history"])), reverse=True)

    return {
        "query": q,
        "urls_tracked": len(items),
        "by_url": items[:200],
        "explain": "Built from chronological snapshots; capped at 200 URLs in output.",
    }
