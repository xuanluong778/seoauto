"""
GSC-aware priority scoring for hybrid technical audit.

Combines crawl severity + GSC traffic signals + URL Inspection index risk.
"""

from __future__ import annotations

import math
from typing import Any

# Issue types with high business impact (index, canonical, robots, HTTP errors)
HIGH_IMPACT_TYPES: frozenset[str] = frozenset(
    {
        "indexability_blocked",
        "indexability_signal_conflict",
        "robots_meta_noindex_contradiction",
        "canonical_cross_host",
        "canonical_self_mismatch",
        "canonical_points_to_non_indexable",
        "google_may_ignore_canonical",
        "page_unlikely_indexed",
        "broken_internal_link",
        "broken_internal_http_error",
        "crawl_page_non_200",
        "crawl_http_4xx",
        "crawl_http_5xx",
        "crawl_timeout",
        "meta_robots_noindex",
        "x_robots_tag_noindex",
        "http_status_error",
        "http_status_non_200",
        "https_not_used",
        "mixed_content",
        "robots_unreachable",
        "robots_disallow_all",
        "sitemap_unreachable",
        "redirect_chain",
    }
)

# Index conclusions must not be stated without URL Inspection
INDEX_INFERENCE_TYPES: frozenset[str] = frozenset(
    {
        "indexability_blocked",
        "indexability_signal_conflict",
        "robots_meta_noindex_contradiction",
        "canonical_points_to_non_indexable",
        "google_may_ignore_canonical",
        "page_unlikely_indexed",
    }
)

LOW_TRAFFIC_DOWNGRADE_TYPES: frozenset[str] = frozenset(
    {
        "images_missing_alt",
        "missing_meta_description",
        "title_too_long",
        "missing_favicon",
        "pagination_missing_rel_next",
        "weak_heading_structure",
    }
)

GSC_DISCLAIMER = "Không thể xác nhận bằng GSC (chưa có URL Inspection API cho URL này)."

SEVERITY_BASE: dict[str, float] = {"high": 72.0, "medium": 48.0, "low": 22.0}

# Multiplicative priority model (0–1 factors → score 0–100)
SEVERITY_FACTOR: dict[str, float] = {
    "critical": 1.0,
    "high": 0.92,
    "medium": 0.68,
    "low": 0.40,
}

SEO_IMPACT_HIGH: float = 1.0
SEO_IMPACT_DEFAULT: float = 0.78
SEO_IMPACT_LOW: float = 0.55

PAGE_TYPE_FACTOR: dict[str, float] = {
    "homepage": 1.12,
    "landing": 1.08,
    "category": 1.05,
    "article": 1.02,
    "unknown": 1.0,
}

PAGE_TYPE_BOOST: dict[str, float] = {
    "homepage": 18.0,
    "landing": 14.0,
    "category": 10.0,
    "article": 6.0,
    "unknown": 0.0,
}

PRIORITY_TIER_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("P0", 80.0),
    ("P1", 60.0),
    ("P2", 35.0),
    ("P3", 0.0),
)


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def traffic_boost(impressions: int, clicks: int, position: float) -> float:
    """0–28 points from GSC performance."""
    if impressions <= 0 and clicks <= 0:
        return 0.0
    imp_score = min(14.0, math.log10(max(impressions, 1) + 1) * 4.5)
    click_score = min(10.0, math.log10(max(clicks, 1) + 1) * 5.0)
    pos_score = 0.0
    if position and position > 0:
        # Better positions (lower number) get slight boost for high-impression URLs
        if position <= 10:
            pos_score = 4.0
        elif position <= 20:
            pos_score = 2.0
    return imp_score + click_score + pos_score


def inspection_index_risk(inspection: dict[str, Any] | None) -> float:
    """0–20 boost when GSC confirms index/canonical problems."""
    if not inspection:
        return 0.0
    verdict = str(inspection.get("index_verdict") or "").upper()
    coverage = str(inspection.get("coverage_state") or "").lower()
    boost = 0.0
    if verdict in ("FAIL", "PARTIAL"):
        boost += 14.0
    if "not indexed" in coverage or "excluded" in coverage or "error" in coverage:
        boost += 10.0
    user_c = (inspection.get("user_canonical") or "").strip()
    google_c = (inspection.get("google_canonical") or "").strip()
    if user_c and google_c and user_c.rstrip("/") != google_c.rstrip("/"):
        boost += 8.0
    return min(20.0, boost)


def priority_tier_from_score(score: float) -> str:
    """Map 0–100 score to P0–P3."""
    val = float(score or 0.0)
    for tier, minimum in PRIORITY_TIER_THRESHOLDS:
        if val >= minimum:
            return tier
    return "P3"


def _severity_factor(severity: str) -> float:
    sev = str(severity or "medium").lower()
    return SEVERITY_FACTOR.get(sev, SEVERITY_FACTOR["medium"])


def _seo_impact_factor(issue_type: str, page_type: str) -> float:
    itype = str(issue_type or "")
    base = SEO_IMPACT_HIGH if itype in HIGH_IMPACT_TYPES else SEO_IMPACT_DEFAULT
    if itype in LOW_TRAFFIC_DOWNGRADE_TYPES:
        base = SEO_IMPACT_LOW
    pt = str(page_type or "unknown").lower()
    return min(1.0, base * PAGE_TYPE_FACTOR.get(pt, 1.0))


def _affected_urls_factor(count: int | None) -> float:
    """Log-scaled URL spread — more affected URLs raise priority."""
    c = max(1, int(count or 1))
    return min(1.0, 0.55 + 0.45 * (math.log10(c + 1) / math.log10(501)))


def _confidence_factor(confidence: float | None) -> float:
    if confidence is None:
        return 0.85
    try:
        val = float(confidence)
    except (TypeError, ValueError):
        return 0.85
    return max(0.40, min(1.0, val))


def _gsc_impact_factor(
    *,
    has_gsc: bool,
    impressions: int,
    clicks: int,
    position: float,
    inspection: dict[str, Any] | None,
    issue_type: str,
) -> float:
    """0.72–1.0 multiplier from GSC traffic + URL Inspection signals."""
    base = 0.78 if has_gsc else 0.72
    tb = traffic_boost(impressions, clicks, position)
    insp = inspection_index_risk(inspection)
    factor = base + min(0.14, tb / 100.0 * 0.50) + min(0.12, insp / 100.0 * 0.60)
    itype = str(issue_type or "")
    if has_gsc and itype in LOW_TRAFFIC_DOWNGRADE_TYPES and impressions < 5 and clicks == 0:
        factor *= 0.82
    return min(1.0, factor)


def compute_priority_components(
    issue: dict[str, Any],
    *,
    page_metrics: dict[str, Any] | None = None,
    inspection: dict[str, Any] | None = None,
    has_gsc: bool = False,
    affected_url_count: int | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """
    Deterministic priority: Severity × SEO Impact × Affected URLs × Confidence × GSC Impact.
    Returns factors (0–1), priority_score (0–100), priority_tier (P0–P3).
    """
    sev = str(issue.get("severity") or "medium").lower()
    itype = str(issue.get("type") or issue.get("issue_type") or "")
    page_type = str(issue.get("page_type") or "unknown").lower()
    pm = page_metrics or {}
    impressions = int(pm.get("impressions") or 0)
    clicks = int(pm.get("clicks") or 0)
    position = float(pm.get("position") or 0.0)

    sev_f = _severity_factor(sev)
    seo_f = _seo_impact_factor(itype, page_type)
    url_f = _affected_urls_factor(affected_url_count)
    conf_raw = confidence if confidence is not None else issue.get("confidence")
    conf_f = _confidence_factor(conf_raw)
    gsc_f = _gsc_impact_factor(
        has_gsc=has_gsc,
        impressions=impressions,
        clicks=clicks,
        position=position,
        inspection=inspection,
        issue_type=itype,
    )

    score = 100.0 * sev_f * seo_f * url_f * conf_f * gsc_f
    score = round(_clamp(score), 1)
    return {
        "severity_factor": round(sev_f, 4),
        "seo_impact_factor": round(seo_f, 4),
        "affected_urls_factor": round(url_f, 4),
        "confidence_factor": round(conf_f, 4),
        "gsc_impact_factor": round(gsc_f, 4),
        "priority_score": score,
        "priority_tier": priority_tier_from_score(score),
    }


def compute_issue_priority_score(
    issue: dict[str, Any],
    *,
    page_metrics: dict[str, Any] | None = None,
    inspection: dict[str, Any] | None = None,
    has_gsc: bool = False,
    affected_url_count: int | None = None,
    confidence: float | None = None,
) -> float:
    """
    Priority score 0–100 for remediation ordering.
    High-traffic URLs with severe technical issues rank highest.
    """
    return compute_priority_components(
        issue,
        page_metrics=page_metrics,
        inspection=inspection,
        has_gsc=has_gsc,
        affected_url_count=affected_url_count,
        confidence=confidence,
    )["priority_score"]


def gsc_evidence_badge(
    issue: dict[str, Any],
    *,
    inspection: dict[str, Any] | None,
    gsc_confirmed: bool = False,
) -> str:
    """
    Returns: gsc_confirmed | crawl_detected | inferred_warning
    """
    itype = str(issue.get("type") or "")
    if gsc_confirmed or (inspection and _inspection_confirms_issue(issue, inspection)):
        return "gsc_confirmed"
    if itype in INDEX_INFERENCE_TYPES and not inspection:
        return "inferred_warning"
    return "crawl_detected"


def _inspection_confirms_issue(issue: dict[str, Any], inspection: dict[str, Any]) -> bool:
    itype = str(issue.get("type") or "")
    verdict = str(inspection.get("index_verdict") or "").upper()
    coverage = str(inspection.get("coverage_state") or "").lower()
    user_c = (inspection.get("user_canonical") or "").strip()
    google_c = (inspection.get("google_canonical") or "").strip()
    canonical_mismatch = bool(user_c and google_c and user_c.rstrip("/") != google_c.rstrip("/"))

    if itype in ("canonical_cross_host", "canonical_self_mismatch", "google_may_ignore_canonical"):
        return canonical_mismatch
    if itype in INDEX_INFERENCE_TYPES:
        if verdict in ("FAIL", "PARTIAL"):
            return True
        if "not indexed" in coverage or "excluded" in coverage:
            return True
    if itype in (
        "broken_internal_link",
        "broken_internal_http_error",
        "crawl_page_non_200",
        "crawl_http_4xx",
        "crawl_http_5xx",
        "http_status_non_200",
    ):
        fetch = str(inspection.get("page_fetch_state") or "").upper()
        if fetch in ("SOFT_404", "NOT_FOUND", "SERVER_ERROR", "REDIRECT_ERROR"):
            return True
    if itype in ("meta_robots_noindex", "x_robots_tag_noindex"):
        indexing = str(inspection.get("indexing_state") or "").upper()
        return "META_TAG" in indexing or "HTTP_HEADER" in indexing or "NOINDEX" in indexing
    if itype == "crawled_url_robots_blocked":
        robots = str(inspection.get("robots_txt_state") or "").upper()
        indexing = str(inspection.get("indexing_state") or "").upper()
        fetch = str(inspection.get("page_fetch_state") or "").upper()
        return (
            "DISALLOWED" in robots
            or "BLOCKED_BY_ROBOTS" in indexing
            or "BLOCKED_ROBOTS" in fetch
        )
    return False


def append_gsc_disclaimer_if_needed(issue: dict[str, Any], *, has_inspection: bool) -> None:
    """Mutate issue explanation — never claim index status without inspection."""
    itype = str(issue.get("type") or "")
    if itype not in INDEX_INFERENCE_TYPES:
        return
    if has_inspection:
        return
    expl = str(issue.get("explanation") or "").strip()
    if GSC_DISCLAIMER in expl:
        return
    issue["explanation"] = (expl + " " + GSC_DISCLAIMER).strip() if expl else GSC_DISCLAIMER


def detect_high_impression_technical_issues(
    issues: list[dict[str, Any]],
    page_metrics_by_url: dict[str, dict[str, Any]],
    *,
    impression_threshold: int = 100,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for issue in issues:
        url = str(issue.get("url") or "").strip()
        if not url:
            continue
        pm = page_metrics_by_url.get(url) or {}
        imp = int(pm.get("impressions") or 0)
        if imp < impression_threshold:
            continue
        if str(issue.get("severity") or "").lower() not in ("high", "medium"):
            continue
        out.append(
            {
                "type": "high_impression_technical_issue",
                "url": url,
                "issue_type": issue.get("type"),
                "severity": issue.get("severity"),
                "impressions": imp,
                "clicks": int(pm.get("clicks") or 0),
                "message": f"URL có {imp} impressions nhưng có lỗi {issue.get('type')}.",
                "priority_score": issue.get("priority_score"),
            }
        )
    out.sort(key=lambda x: -(x.get("impressions") or 0))
    return out[:30]


def detect_ctr_opportunities(
    page_metrics_by_url: dict[str, dict[str, Any]],
    *,
    impression_threshold: int = 200,
    ctr_threshold: float = 0.02,
    position_max: float = 15.0,
) -> list[dict[str, Any]]:
    """High impressions + low CTR + decent position → snippet/title opportunity."""
    out: list[dict[str, Any]] = []
    for url, pm in page_metrics_by_url.items():
        imp = int(pm.get("impressions") or 0)
        ctr = float(pm.get("ctr") or 0.0)
        pos = float(pm.get("position") or 0.0)
        if imp < impression_threshold:
            continue
        if ctr >= ctr_threshold:
            continue
        if pos > position_max or pos <= 0:
            continue
        out.append(
            {
                "type": "ctr_opportunity",
                "url": url,
                "impressions": imp,
                "clicks": int(pm.get("clicks") or 0),
                "ctr": round(ctr, 4),
                "position": round(pos, 1),
                "message": f"CTR thấp ({ctr * 100:.2f}%) dù có {imp} impressions — tối ưu title/meta snippet.",
            }
        )
    out.sort(key=lambda x: -(x.get("impressions") or 0))
    return out[:20]


def detect_traffic_drop_opportunities(
    current_by_url: dict[str, dict[str, Any]],
    prior_by_url: dict[str, dict[str, Any]],
    *,
    min_prior_clicks: int = 10,
    drop_ratio: float = 0.4,
) -> list[dict[str, Any]]:
    """Compare prior period clicks vs current (requires two analytics pulls)."""
    out: list[dict[str, Any]] = []
    for url, prior in prior_by_url.items():
        prior_clicks = int(prior.get("clicks") or 0)
        if prior_clicks < min_prior_clicks:
            continue
        cur = current_by_url.get(url) or {}
        cur_clicks = int(cur.get("clicks") or 0)
        if prior_clicks <= 0:
            continue
        ratio = cur_clicks / prior_clicks
        if ratio > drop_ratio:
            continue
        out.append(
            {
                "type": "traffic_drop",
                "url": url,
                "clicks_prior": prior_clicks,
                "clicks_current": cur_clicks,
                "drop_pct": round((1 - ratio) * 100, 1),
                "message": f"Clicks giảm ~{round((1 - ratio) * 100)}% so với kỳ trước ({prior_clicks} → {cur_clicks}).",
            }
        )
    out.sort(key=lambda x: -(x.get("drop_pct") or 0))
    return out[:20]


def score_urls_for_inspection(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> list[str]:
    """Return top URL strings by priority_score."""
    ranked = sorted(candidates, key=lambda c: -(c.get("priority_score") or 0))
    seen: set[str] = set()
    out: list[str] = []
    for c in ranked:
        u = str(c.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out
