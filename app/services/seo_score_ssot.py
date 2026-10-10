"""
SEO Score SSOT — single authoritative score from 10 groups (weights sum to 100).

Legacy 12-pillar / 15-checklist scores are informational only and MUST NOT
feed the main total.
"""

from __future__ import annotations

from typing import Any

SCORING_VERSION = "2.0.0"

GROUP_WEIGHTS: dict[str, float] = {
    "indexability": 15.0,
    "title_meta_slug": 12.0,
    "heading": 8.0,
    "keyword_semantic": 12.0,
    "search_intent": 12.0,
    "content_quality": 12.0,
    "links": 8.0,
    "image_seo": 6.0,
    "schema": 7.0,
    "ux_mobile_speed": 8.0,
}

GROUP_LABELS: dict[str, str] = {
    "indexability": "Indexability",
    "title_meta_slug": "Title / Meta / Slug",
    "heading": "Heading",
    "keyword_semantic": "Keyword / Semantic",
    "search_intent": "Search Intent",
    "content_quality": "Content Quality",
    "links": "Internal / External Link",
    "image_seo": "Image SEO",
    "schema": "Schema",
    "ux_mobile_speed": "UX / Mobile / Speed",
}

_STATUS_LEGACY_MAP = {
    "PASS": "passed",
    "WARNING": "warning",
    "FAIL": "failed",
    "UNKNOWN": "warning",
}


def normalize_check_status(raw: str) -> str:
    s = str(raw or "").strip().upper()
    if s in ("PASS", "PASSED", "OK", "SUCCESS"):
        return "PASS"
    if s in ("WARN", "WARNING"):
        return "WARNING"
    if s in ("FAIL", "FAILED", "ERROR"):
        return "FAIL"
    if s in ("UNKNOWN", "N/A", "NA", "MISSING"):
        return "UNKNOWN"
    # legacy lowercase
    low = s.lower()
    if low == "passed":
        return "PASS"
    if low == "warning":
        return "WARNING"
    if low == "failed":
        return "FAIL"
    return "UNKNOWN"


def make_check(
    *,
    check_id: str,
    title: str,
    status: str,
    score: float,
    max_score: float,
    confidence: float = 1.0,
    evidence: dict[str, Any] | None = None,
    problem: str = "",
    impact: str = "",
    recommendation: str = "",
    fix: str = "",
) -> dict[str, Any]:
    """Build a normalized check row for SSOT scoring."""
    st = normalize_check_status(status)
    conf = max(0.0, min(1.0, float(confidence)))
    # Low confidence must not hard-fail
    if conf < 0.45 and st == "FAIL":
        st = "WARNING"
    rec = (recommendation or fix or "").strip() or "—"
    earned = round(max(0.0, min(float(max_score), float(score))), 1)
    return {
        "id": check_id,
        "title": title,
        "status": st,
        "status_legacy": _STATUS_LEGACY_MAP.get(st, "warning"),
        "score": earned,
        "max_score": round(float(max_score), 1),
        "confidence": round(conf, 2),
        "evidence": dict(evidence or {}),
        "problem": problem or "—",
        "impact": impact or "—",
        "recommendation": rec,
        "fix": rec,
    }


def group_score_from_checks(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 0.0
    earned = sum(float(c.get("score") or 0) for c in checks)
    max_total = sum(float(c.get("max_score") or 0) for c in checks)
    if max_total <= 0:
        return 0.0
    return round(min(100.0, earned / max_total * 100.0), 1)


def compute_ssot_total(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic main score from 10-group weighted contributions."""
    weight_sum = sum(GROUP_WEIGHTS.values())
    group_scores: dict[str, float] = {}
    weighted_total = 0.0
    for g in groups:
        gid = str(g.get("id") or "")
        gscore = round(float(g.get("score") or 0), 1)
        w = float(GROUP_WEIGHTS.get(gid) or g.get("weight") or 0)
        wp = round(gscore * w / 100.0, 2)
        group_scores[gid] = gscore
        weighted_total += wp
    total = round(max(0.0, min(100.0, weighted_total)), 1)
    return {
        "total_score": total,
        "group_scores": group_scores,
        "weighted_total": round(weighted_total, 2),
        "weights": GROUP_WEIGHTS,
        "weight_sum": weight_sum,
        "scoring_version": SCORING_VERSION,
    }


def count_checks_by_status(checks: list[dict[str, Any]]) -> dict[str, int]:
    out = {"pass": 0, "warning": 0, "fail": 0, "unknown": 0}
    for c in checks:
        st = normalize_check_status(str(c.get("status") or c.get("status_legacy") or ""))
        if st == "PASS":
            out["pass"] += 1
        elif st == "WARNING":
            out["warning"] += 1
        elif st == "FAIL":
            out["fail"] += 1
        else:
            out["unknown"] += 1
    return out
