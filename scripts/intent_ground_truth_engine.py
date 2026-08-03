"""
SERP-derived dominant intent: classify top organic rows, weighted vote, stability over time.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.serp_intent_classifier import _classify_one_result


def _kl(p: dict[str, float], q: dict[str, float]) -> float:
    keys = set(p) | set(q)
    s = 0.0
    for k in keys:
        pk = float(p.get(k, 1e-6))
        qk = float(q.get(k, 1e-6))
        s += pk * math.log((pk + 1e-12) / (qk + 1e-12), 2)
    return max(0.0, s)


def _js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    m = {k: 0.5 * (float(p.get(k, 0)) + float(q.get(k, 0))) for k in set(p) | set(q)}
    pp = {k: float(p.get(k, 0)) for k in m}
    qq = {k: float(q.get(k, 0)) for k in m}
    totp = sum(pp.values()) or 1.0
    totq = sum(qq.values()) or 1.0
    pp = {k: v / totp for k, v in pp.items()}
    qq = {k: v / totq for k, v in qq.items()}
    mm = {k: max(1e-9, 0.5 * (pp.get(k, 0) + qq.get(k, 0))) for k in m}
    return 0.5 * _kl(pp, mm) + 0.5 * _kl(qq, mm)


def _weighted_intent_distribution(rows: list[dict[str, Any]], *, top_n: int = 10) -> dict[str, float]:
    votes: dict[str, float] = {}
    for r in rows[:top_n]:
        w = 1.0 / max(1, int(r.get("rank") or 1))
        row = {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("snippet")}
        one = _classify_one_result(row)
        intent = str(one.get("intent") or "informational")
        votes[intent] = votes.get(intent, 0.0) + w

    s = sum(votes.values()) or 1.0
    return {k: round(v / s, 4) for k, v in votes.items()}


def build_intent_truth_from_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Returns dominant intent + distribution for latest snapshot and stability vs history.
    """
    if not snapshots:
        return {
            "query": "",
            "dominant_intent": "informational",
            "intent_distribution": {},
            "intent_stability_score": 0.0,
            "serp_type_distribution": {},
            "explain": "No snapshots.",
        }

    q = str(snapshots[-1].get("query") or "").strip()
    latest = snapshots[-1]
    rows = list(latest.get("results") or [])
    dist = _weighted_intent_distribution(rows, top_n=top_n)
    dominant = max(dist, key=lambda k: dist[k]) if dist else "informational"

    type_dist: dict[str, float] = {}
    for r in rows[:top_n]:
        ct = str(r.get("content_type") or "blog")
        type_dist[ct] = type_dist.get(ct, 0.0) + 1.0
    tt = sum(type_dist.values()) or 1.0
    type_dist = {k: round(v / tt, 4) for k, v in type_dist.items()}

    js_scores: list[float] = []
    prev: dict[str, float] | None = None
    for snap in snapshots:
        d = _weighted_intent_distribution(list(snap.get("results") or []), top_n=top_n)
        if prev is not None and d and prev:
            js_scores.append(_js_divergence(prev, d))
        prev = d

    mean_js = sum(js_scores) / len(js_scores) if js_scores else 0.0
    if len(snapshots) < 2:
        stability = 0.0
    else:
        stability = round(max(0.0, min(1.0, 1.0 - min(1.0, mean_js))), 4)

    return {
        "query": q,
        "dominant_intent": dominant,
        "intent_distribution": dist,
        "intent_stability_score": stability,
        "serp_type_distribution": type_dist,
        "explain": (
            "Each snapshot: top-N rows classified via ``_classify_one_result`` on URL/title/snippet, "
            "weighted by 1/rank; dominant_intent from latest; stability = 1 - mean JS divergence "
            "between successive snapshot intent distributions (capped at 1)."
        ),
    }
