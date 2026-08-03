"""
Technical Analysis output normalizer — crawl + GSC → unified SaaS payload.

Pure transformation layer: does not mutate upstream audit responses.
Safe fallbacks when fields are missing; crawl-only works without GSC.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from app.seo_pipeline.constants import CHECKLIST_TITLE_VI, TECH_CHECKLIST_BY_TYPE

# Normalized category slugs (SaaS / API contract)
NORMALIZED_CATEGORIES: tuple[str, ...] = (
    "gsc_indexing",
    "website",
    "sitemap",
    "robots",
    "schema",
    "images",
    "video",
    "site_speed",
    "https",
    "response_code",
    "onpage",
    "mobile",
    "international",
    "other",
)

NORMALIZED_SEVERITIES: tuple[str, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "passed",
)

NORMALIZED_STATUSES: tuple[str, ...] = (
    "failed",
    "warning",
    "passed",
    "unknown",
)

# Health score budget (must sum to 100)
HEALTH_WEIGHTS: dict[str, float] = {
    "gsc_indexing": 25.0,
    "crawlability": 20.0,
    "response_security": 20.0,
    "onpage": 15.0,
    "mobile_speed": 15.0,
    "semantic": 5.0,
}

# Map normalized issue category → health bucket
_CATEGORY_TO_HEALTH_BUCKET: dict[str, str] = {
    "gsc_indexing": "gsc_indexing",
    "website": "crawlability",
    "sitemap": "crawlability",
    "robots": "crawlability",
    "https": "response_security",
    "response_code": "response_security",
    "onpage": "onpage",
    "mobile": "mobile_speed",
    "site_speed": "mobile_speed",
    "schema": "semantic",
    "images": "semantic",
    "video": "semantic",
    "international": "semantic",
    "other": "semantic",
}

# Issue types forced to critical severity
_CRITICAL_TYPES: frozenset[str] = frozenset(
    {
        "robots_disallow_all",
        "indexability_blocked",
        "robots_meta_noindex_contradiction",
        "broken_internal_http_error",
        "crawl_page_non_200",
        "http_status_non_200",
        "https_not_used",
        "cloaking_risk_advanced",
        "cloaking_heuristic",
    }
)

# Types typically high (not critical unless traffic/GSC confirms)
_HIGH_TYPES: frozenset[str] = frozenset(
    {
        "sitemap_unreachable",
        "sitemap_empty",
        "robots_unreachable",
        "canonical_cross_host",
        "canonical_self_mismatch",
        "canonical_points_to_non_indexable",
        "google_may_ignore_canonical",
        "broken_internal_link",
        "redirect_chain",
        "indexability_signal_conflict",
        "page_unlikely_indexed",
        "robots_noindex",
        "soft_404_heuristic",
    }
)

_MEDIUM_TYPES: frozenset[str] = frozenset(
    {
        "duplicate_title",
        "missing_meta_description",
        "missing_h1",
        "multiple_h1",
        "missing_canonical",
        "title_too_long",
        "thin_content",
        "images_missing_alt",
        "js_seo_risk_high",
        "js_seo_risk_medium",
        "js_shell_missing_critical",
        "weak_heading_structure",
        "canonical_missing_high_value",
        "canonical_low_similarity_mismatch",
        "robots_missing_sitemap_line",
        "robots_sitemap_unreachable",
    }
)

_LOW_TYPES: frozenset[str] = frozenset(
    {
        "missing_favicon",
        "pagination_missing_rel_next",
        "link_check_truncated",
        "crawl_data_low_trust",
        "robots_wordpress_standard_blocks",
        "robots_disallow_broad_querystring",
    }
)

_SEVERITY_PENALTY: dict[str, float] = {
    "critical": 1.0,
    "high": 0.65,
    "medium": 0.35,
    "low": 0.15,
    "passed": 0.0,
}

_IMPACT_BY_CATEGORY: dict[str, list[str]] = {
    "gsc_indexing": ["indexing", "organic_traffic"],
    "website": ["crawl", "internal_links"],
    "sitemap": ["discovery", "indexing"],
    "robots": ["crawl", "indexing"],
    "schema": ["rich_results", "serp"],
    "images": ["image_search", "accessibility"],
    "video": ["video_search"],
    "site_speed": ["core_web_vitals", "ranking"],
    "https": ["security", "trust"],
    "response_code": ["crawl", "user_experience"],
    "onpage": ["serp", "relevance"],
    "mobile": ["mobile_ux", "ranking"],
    "international": ["hreflang", "geo_targeting"],
    "other": ["general"],
}

_WHY_IT_MATTERS: dict[str, str] = {
    "gsc_indexing": "Ảnh hưởng trực tiếp khả năng URL xuất hiện trên Google và nhận traffic organic.",
    "website": "Cấu trúc site và liên kết nội bộ quyết định bot crawl và phân phối PageRank.",
    "sitemap": "Sitemap giúp Google khám phá URL mới và ưu tiên crawl đúng tập trang.",
    "robots": "robots.txt điều phối crawl — sai cấu hình có thể chặn toàn site hoặc section quan trọng.",
    "schema": "Structured data hỗ trợ rich results và hiểu ngữ cảnh nội dung.",
    "images": "Alt và tối ưu ảnh ảnh hưởng image search và accessibility.",
    "video": "Video markup và sitemap giúp index video content.",
    "site_speed": "Tốc độ và CWV là tín hiệu ranking và trải nghiệm người dùng.",
    "https": "HTTPS là yêu cầu nền tảng cho trust, indexing và browser security.",
    "response_code": "Mã HTTP sai gây mất crawl budget, 404/5xx và chuỗi redirect dài.",
    "onpage": "Title, meta, heading và canonical ảnh hưởng CTR và khớp intent SERP.",
    "mobile": "Mobile-first indexing ưu tiên phiên bản mobile của trang.",
    "international": "hreflang/lang sai gây trùng lặp hoặc phục vụ sai thị trường.",
    "other": "Các tín hiệu kỹ thuật phụ trợ ảnh hưởng chất lượng crawl tổng thể.",
}

# Catalog pillars for passed-check inference
_CATALOG_CHECK_KEYS: list[tuple[str, str, list[str]]] = [
    ("robots", "robots_txt", ["robots_unreachable", "robots_disallow_all"]),
    ("sitemap", "sitemap_xml", ["sitemap_unreachable", "sitemap_empty"]),
    ("https", "https_protocol", ["https_not_used"]),
    ("gsc_indexing", "internal_links", ["broken_internal_link", "broken_internal_http_error"]),
    ("response_code", "http_status", ["crawl_page_non_200", "http_status_error", "http_status_non_200"]),
    ("onpage", "title_meta", ["missing_title", "missing_meta_description", "duplicate_title"]),
    ("images", "image_alt", ["images_missing_alt"]),
    ("international", "html_lang", ["missing_html_lang"]),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            return {}
    return {}


def _safe_list(obj: Any) -> list[Any]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return []


def _issue_type(raw: dict[str, Any]) -> str:
    return str(raw.get("type") or raw.get("issue_type") or "unknown_issue").strip()


def _normalize_legacy_severity(raw: dict[str, Any]) -> str:
    """Map crawl severity (high/medium/low) + type heuristics → normalized severity."""
    if raw.get("severity") == "passed" or raw.get("status") == "passed":
        return "passed"
    legacy = str(raw.get("severity") or "medium").lower()
    itype = _issue_type(raw)
    if itype in _CRITICAL_TYPES or legacy == "critical":
        return "critical"
    if itype in _HIGH_TYPES or legacy == "high":
        return "high"
    if itype in _LOW_TYPES or legacy == "low":
        return "low"
    if itype in _MEDIUM_TYPES or legacy == "medium":
        return "medium"
    if legacy in NORMALIZED_SEVERITIES:
        return legacy
    return "medium"


def _severity_to_status(severity: str) -> str:
    if severity == "passed":
        return "passed"
    if severity == "critical":
        return "failed"
    if severity in ("high", "medium"):
        return "warning"
    if severity == "low":
        return "warning"
    return "unknown"


def _map_checklist_group_to_category(group: str, issue_type: str) -> str:
    g = (group or "").strip()
    t = issue_type.lower()
    if g == "Sitemap" or t.startswith("sitemap_"):
        return "sitemap"
    if g == "Robots" or t.startswith("robots_"):
        return "robots"
    if g == "Images" or "image" in t or "alt" in t:
        return "images"
    if g == "Video" or t.startswith("video_"):
        return "video"
    if g == "Mobile":
        return "mobile"
    if g == "International":
        return "international"
    if g == "Speed" or "pagespeed" in t or "cwv" in t:
        return "site_speed"
    if g == "Security" or t == "https_not_used":
        return "https"
    if t in ("crawl_page_non_200", "http_status_error", "http_status_non_200"):
        return "response_code"
    if g == "Onpage" or t.startswith("schema_"):
        if t.startswith("schema_"):
            return "schema"
        return "onpage"
    if re.match(r"^js_seo_|^js_shell_", t):
        return "website"
    if g == "GSC":
        if t in ("broken_internal_link", "broken_internal_http_error"):
            return "website"
        return "gsc_indexing"
    if g in ("General", "Crawl quality") or t in ("link_check_truncated", "crawl_data_low_trust"):
        return "other"
    return "other"


def _resolve_category(raw: dict[str, Any]) -> str:
    explicit = raw.get("category")
    if explicit and str(explicit) in NORMALIZED_CATEGORIES:
        return str(explicit)
    group = str(
        raw.get("checklist_group")
        or raw.get("group")
        or TECH_CHECKLIST_BY_TYPE.get(_issue_type(raw), "General")
    )
    return _map_checklist_group_to_category(group, _issue_type(raw))


def _make_issue_id(issue_type: str, url: str | None, source: str) -> str:
    base = f"{issue_type}|{url or ''}|{source}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "_", issue_type.lower()).strip("_")[:40] or "issue"
    return f"{slug}_{digest}"


def _confidence_value(raw: dict[str, Any]) -> float:
    c = raw.get("confidence")
    if c is None or c == "":
        sev = _normalize_legacy_severity(raw)
        defaults = {"critical": 0.9, "high": 0.82, "medium": 0.72, "low": 0.58, "passed": 1.0}
        return defaults.get(sev, 0.7)
    try:
        return max(0.0, min(1.0, float(c)))
    except (TypeError, ValueError):
        return 0.7


def _how_to_fix(raw: dict[str, Any]) -> str:
    for key in ("how_to_fix", "suggested_fix", "remediation"):
        val = raw.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def _normalize_single_issue(
    raw: dict[str, Any],
    *,
    source: str = "crawl",
    detected_at: str | None = None,
) -> dict[str, Any]:
    """Transform one raw issue dict into normalized SaaS issue object."""
    raw = _safe_dict(raw)
    itype = _issue_type(raw)
    url = str(raw.get("url") or raw.get("inspection_url") or "").strip() or None
    severity = _normalize_legacy_severity(raw)
    category = _resolve_category(raw)
    title = (
        str(raw.get("title") or "").strip()
        or CHECKLIST_TITLE_VI.get(itype)
        or itype.replace("_", " ").title()
    )
    description = str(raw.get("description") or raw.get("message") or "").strip()
    affected = _safe_list(raw.get("affected_urls"))
    if url and url not in affected:
        affected = [url] + affected
    sample = _safe_list(raw.get("sample_urls")) or affected[:5]

    badge = raw.get("gsc_badge")
    if source == "gsc" and not badge:
        badge = "gsc_confirmed"
    if source == "hybrid" and not badge:
        badge = raw.get("gsc_badge") or "gsc_confirmed"

    out: dict[str, Any] = {
        "id": str(raw.get("id") or _make_issue_id(itype, url, source)),
        "category": category,
        "title": title,
        "description": description,
        "source": source if source in ("crawl", "gsc", "hybrid", "manual") else "crawl",
        "severity": severity,
        "status": _severity_to_status(severity),
        "count": int(raw.get("count") or len(affected) or (1 if url else 0)),
        "affected_urls": affected,
        "sample_urls": sample[:5],
        "impact_area": list(_IMPACT_BY_CATEGORY.get(category, ["general"])),
        "why_it_matters": str(raw.get("why_it_matters") or _WHY_IT_MATTERS.get(category, "")),
        "how_to_fix": _how_to_fix(raw),
        "priority_score": int(raw.get("priority_score") or 0),
        "confidence": _confidence_value(raw),
        "gsc_badge": badge,
        "gsc_clicks": raw.get("gsc_clicks"),
        "gsc_impressions": raw.get("gsc_impressions"),
        "gsc_ctr": raw.get("gsc_ctr"),
        "gsc_position": raw.get("gsc_position"),
        "gsc_index_verdict": raw.get("gsc_index_verdict"),
        "detected_at": str(raw.get("detected_at") or detected_at or _utc_now_iso()),
        "_issue_type": itype,
    }
    if not out["priority_score"]:
        out["priority_score"] = int(round(calculate_priority_score(out)))
    return out


def normalize_crawl_issues(
    raw_issues: list[dict[str, Any]] | None,
    page_audits: list[dict[str, Any]] | None = None,
    technical_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize crawl/rule-engine issues. Ignores suppressed items."""
    _ = page_audits, technical_summary  # reserved for future enrichment
    out: list[dict[str, Any]] = []
    for raw in _safe_list(raw_issues):
        if not isinstance(raw, dict):
            continue
        if raw.get("suppressed"):
            continue
        out.append(_normalize_single_issue(raw, source="crawl"))
    return out


def normalize_gsc_issues(
    gsc_summary: dict[str, Any] | None = None,
    gsc_enriched_pages: list[dict[str, Any]] | None = None,
    gsc_confirmed_issues: list[dict[str, Any]] | None = None,
    url_inspection_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build normalized issues from GSC Search Analytics + URL Inspection."""
    gs = _safe_dict(gsc_summary)
    if not gs.get("enabled") and not gsc_confirmed_issues and not url_inspection_results:
        return []

    detected_at = _utc_now_iso()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(raw: dict[str, Any], *, source: str = "gsc") -> None:
        norm = _normalize_single_issue(raw, source=source, detected_at=detected_at)
        key = f"{norm.get('_issue_type')}|{norm.get('sample_urls', [''])[0] if norm.get('sample_urls') else ''}"
        if key in seen:
            return
        seen.add(key)
        out.append(norm)

    for item in _safe_list(gsc_confirmed_issues):
        if not isinstance(item, dict):
            continue
        _add(
            {
                "type": item.get("issue_type") or item.get("type") or "gsc_confirmed_issue",
                "severity": item.get("severity") or "high",
                "message": item.get("message") or "Issue xác nhận bởi Google Search Console.",
                "url": item.get("url"),
                "category": "gsc_indexing",
                "gsc_index_verdict": item.get("index_verdict"),
                "gsc_badge": "gsc_confirmed",
                "checklist_group": "GSC",
            },
            source="gsc",
        )

    for insp in _safe_list(url_inspection_results):
        if not isinstance(insp, dict):
            continue
        if insp.get("status") == "error":
            continue
        url = str(insp.get("inspection_url") or "").strip()
        verdict = str(insp.get("index_verdict") or "").upper()
        coverage = str(insp.get("coverage_state") or "")
        user_c = str(insp.get("user_canonical") or "").strip()
        google_c = str(insp.get("google_canonical") or "").strip()
        canonical_mismatch = bool(user_c and google_c and user_c.rstrip("/") != google_c.rstrip("/"))

        if canonical_mismatch:
            _add(
                {
                    "type": "gsc_canonical_mismatch",
                    "severity": "high",
                    "message": f"Google chọn canonical khác user canonical cho {url}.",
                    "url": url,
                    "category": "gsc_indexing",
                    "gsc_user_canonical": user_c,
                    "gsc_google_canonical": google_c,
                    "gsc_index_verdict": verdict,
                    "gsc_badge": "gsc_confirmed",
                    "remediation": "Chuẩn hóa canonical một chiều; đồng bộ nội dung hoặc 301 gộp bản duplicate.",
                },
                source="gsc",
            )

        if verdict in ("FAIL", "PARTIAL") or "not indexed" in coverage.lower():
            _add(
                {
                    "type": "gsc_index_verdict_fail",
                    "severity": "critical" if verdict == "FAIL" else "high",
                    "message": f"URL Inspection: {coverage or verdict} — {url}",
                    "url": url,
                    "category": "gsc_indexing",
                    "gsc_index_verdict": verdict,
                    "gsc_coverage_state": coverage,
                    "gsc_badge": "gsc_confirmed",
                },
                source="gsc",
            )

    # High-impression pages with inspection hints (enriched pages)
    for page in _safe_list(gsc_enriched_pages):
        if not isinstance(page, dict):
            continue
        insp = _safe_dict(page.get("inspection"))
        if not insp:
            continue
        imp = int(page.get("impressions") or 0)
        if imp < 50:
            continue
        url = str(page.get("page") or "").strip()
        if not url:
            continue
        _add(
            {
                "type": "gsc_high_impression_page",
                "severity": "medium",
                "message": f"URL có {imp} impressions — kiểm tra index/canonical trong GSC.",
                "url": url,
                "category": "gsc_indexing",
                "gsc_impressions": imp,
                "gsc_clicks": page.get("clicks"),
                "gsc_ctr": page.get("ctr"),
                "gsc_position": page.get("position"),
                "gsc_index_verdict": insp.get("index_verdict"),
                "gsc_badge": "gsc_confirmed",
            },
            source="gsc",
        )

    if gs.get("partial_data") and not out:
        _add(
            {
                "type": "gsc_partial_data",
                "severity": "low",
                "message": gs.get("message") or "Dữ liệu GSC không đầy đủ (quota/permission).",
                "category": "gsc_indexing",
                "gsc_badge": "inferred_warning",
            },
            source="gsc",
        )

    return out


def merge_duplicate_issues(
    crawl_issues: list[dict[str, Any]] | None,
    gsc_issues: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge crawl + GSC issues; GSC confirms upgrade source to hybrid."""
    rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "passed": 1}
    merged: dict[str, dict[str, Any]] = {}

    for issue in _safe_list(crawl_issues) + _safe_list(gsc_issues):
        if not isinstance(issue, dict):
            continue
        itype = issue.get("_issue_type") or issue.get("id", "")
        cat = issue.get("category", "other")
        key = f"{cat}|{itype}"
        prev = merged.get(key)
        if not prev:
            merged[key] = dict(issue)
            continue
        # Merge URLs
        urls = list(dict.fromkeys(_safe_list(prev.get("affected_urls")) + _safe_list(issue.get("affected_urls"))))
        prev["affected_urls"] = urls
        prev["sample_urls"] = urls[:5]
        prev["count"] = max(int(prev.get("count") or 0), int(issue.get("count") or 0), len(urls))
        # Higher severity wins
        if rank.get(str(issue.get("severity")), 0) > rank.get(str(prev.get("severity")), 0):
            prev["severity"] = issue["severity"]
            prev["status"] = issue.get("status") or _severity_to_status(str(issue["severity"]))
        # GSC fields fill gaps
        for field in (
            "gsc_badge",
            "gsc_clicks",
            "gsc_impressions",
            "gsc_ctr",
            "gsc_position",
            "gsc_index_verdict",
            "how_to_fix",
        ):
            if prev.get(field) is None and issue.get(field) is not None:
                prev[field] = issue[field]
        # Source upgrade
        s0, s1 = prev.get("source"), issue.get("source")
        if s0 != s1 and {s0, s1} <= {"crawl", "gsc"}:
            prev["source"] = "hybrid"
            if prev.get("gsc_badge") == "crawl_detected" and issue.get("gsc_badge") == "gsc_confirmed":
                prev["gsc_badge"] = "gsc_confirmed"
        prev["priority_score"] = max(int(prev.get("priority_score") or 0), int(issue.get("priority_score") or 0))

    result = list(merged.values())
    for item in result:
        item.pop("_issue_type", None)
    result.sort(key=lambda x: (-(x.get("priority_score") or 0), x.get("category", "")))
    return result


def calculate_priority_score(issue: dict[str, Any]) -> float:
    """
    Priority score 0–100 for remediation ordering.
    Uses existing GSC priority engine when possible.
    """
    issue = _safe_dict(issue)
    try:
        from app.services.gsc_priority import compute_issue_priority_score

        legacy = {
            "type": issue.get("_issue_type") or issue.get("id", ""),
            "severity": issue.get("severity") or "medium",
            "url": (issue.get("sample_urls") or issue.get("affected_urls") or [None])[0],
            "page_type": issue.get("page_type"),
            "gsc_badge": issue.get("gsc_badge"),
        }
        sev_map = {"critical": "high", "high": "high", "medium": "medium", "low": "low", "passed": "low"}
        legacy["severity"] = sev_map.get(str(legacy["severity"]), "medium")
        if str(issue.get("severity")) == "critical":
            base = compute_issue_priority_score(
                legacy,
                page_metrics={
                    "impressions": int(issue.get("gsc_impressions") or 0),
                    "clicks": int(issue.get("gsc_clicks") or 0),
                    "position": float(issue.get("gsc_position") or 0),
                },
                has_gsc=issue.get("gsc_impressions") is not None,
            )
            return round(min(100.0, base + 12.0), 1)
        return compute_issue_priority_score(
            legacy,
            page_metrics={
                "impressions": int(issue.get("gsc_impressions") or 0),
                "clicks": int(issue.get("gsc_clicks") or 0),
                "position": float(issue.get("gsc_position") or 0),
            },
            has_gsc=issue.get("gsc_impressions") is not None,
        )
    except Exception:
        pass

    sev = str(issue.get("severity") or "medium")
    base = {"critical": 88, "high": 72, "medium": 48, "low": 24, "passed": 0}.get(sev, 40)
    imp = int(issue.get("gsc_impressions") or 0)
    if imp > 0:
        base += min(15, imp // 100)
    if issue.get("gsc_badge") == "gsc_confirmed":
        base += 8
    return round(min(100.0, float(base)), 1)


def calculate_technical_health_score(
    normalized_issues: list[dict[str, Any]] | None,
    passed_checks: list[dict[str, Any]] | None = None,
    gsc_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Technical Health Score 0–100 with weighted category breakdown.
    """
    issues = [i for i in _safe_list(normalized_issues) if isinstance(i, dict) and i.get("severity") != "passed"]
    passed = _safe_list(passed_checks)
    gs = _safe_dict(gsc_summary)

    bucket_penalty: dict[str, float] = {k: 0.0 for k in HEALTH_WEIGHTS}
    bucket_issue_count: dict[str, int] = {k: 0 for k in HEALTH_WEIGHTS}

    for issue in issues:
        cat = str(issue.get("category") or "other")
        bucket = _CATEGORY_TO_HEALTH_BUCKET.get(cat, "semantic")
        sev = str(issue.get("severity") or "medium")
        bucket_penalty[bucket] = max(bucket_penalty[bucket], _SEVERITY_PENALTY.get(sev, 0.35))
        bucket_issue_count[bucket] += 1

    # Passed checks reduce penalty in matching buckets
    for chk in passed:
        if not isinstance(chk, dict) or chk.get("status") != "passed":
            continue
        bucket = _CATEGORY_TO_HEALTH_BUCKET.get(str(chk.get("category") or "other"), "semantic")
        bucket_penalty[bucket] *= 0.85

    breakdown: dict[str, Any] = {}
    total_score = 0.0
    for bucket, weight in HEALTH_WEIGHTS.items():
        penalty = min(1.0, bucket_penalty[bucket])
        bucket_score = round(weight * (1.0 - penalty), 2)
        breakdown[bucket] = {
            "weight": weight,
            "score": bucket_score,
            "penalty_ratio": round(penalty, 3),
            "issue_count": bucket_issue_count[bucket],
        }
        total_score += bucket_score

    # GSC partial data — slight confidence discount only, not fail
    partial = bool(gs.get("partial_data"))
    if partial:
        total_score = max(0.0, total_score - 2.0)

    return {
        "health_score": round(min(100.0, max(0.0, total_score)), 1),
        "breakdown": breakdown,
        "partial_data": partial,
        "gsc_enabled": bool(gs.get("enabled")),
    }


def build_top_priority_fixes(
    normalized_issues: list[dict[str, Any]] | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top N fixes sorted by priority_score."""
    issues = [i for i in _safe_list(normalized_issues) if isinstance(i, dict)]
    issues = [i for i in issues if i.get("severity") not in ("passed",) and i.get("status") != "passed"]
    for i in issues:
        if not i.get("priority_score"):
            i["priority_score"] = int(round(calculate_priority_score(i)))
    issues.sort(key=lambda x: (-(x.get("priority_score") or 0), x.get("severity", "")))
    top = issues[: max(1, int(limit))]
    return [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "category": t.get("category"),
            "severity": t.get("severity"),
            "priority_score": t.get("priority_score"),
            "how_to_fix": t.get("how_to_fix"),
            "sample_urls": t.get("sample_urls") or [],
            "source": t.get("source"),
        }
        for t in top
    ]


def build_passed_checks(raw_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Infer passed checks from robots/sitemap/technical_summary when no matching issue."""
    payload = _safe_dict(raw_payload)
    issues = _safe_list(payload.get("issues"))
    open_types = {_issue_type(i) for i in issues if isinstance(i, dict) and not i.get("suppressed")}

    ts = _safe_dict(payload.get("technical_summary"))
    robots = _safe_dict(payload.get("robots"))
    sitemap = _safe_dict(payload.get("sitemap"))
    passed: list[dict[str, Any]] = []

    def _passed_item(check_id: str, category: str, title: str, detail: str = "") -> dict[str, Any]:
        return {
            "id": check_id,
            "category": category,
            "title": title,
            "description": detail or f"Đã kiểm tra — không phát hiện lỗi cho {title}.",
            "source": "crawl",
            "severity": "passed",
            "status": "passed",
            "count": 0,
            "affected_urls": [],
            "sample_urls": [],
            "impact_area": _IMPACT_BY_CATEGORY.get(category, ["general"]),
            "why_it_matters": _WHY_IT_MATTERS.get(category, ""),
            "how_to_fix": "",
            "priority_score": 0,
            "confidence": 0.85,
            "gsc_badge": None,
            "gsc_clicks": None,
            "gsc_impressions": None,
            "gsc_ctr": None,
            "gsc_position": None,
            "gsc_index_verdict": None,
            "detected_at": _utc_now_iso(),
        }

    for category, check_id, blocking_types in _CATALOG_CHECK_KEYS:
        if any(t in open_types for t in blocking_types):
            continue
        if category == "robots" and int(robots.get("status") or 0) not in (0, 200):
            continue
        if category == "sitemap" and int(sitemap.get("status") or 0) not in (0, 200):
            continue
        titles = {
            "robots_txt": "Robots.txt truy cập được",
            "sitemap_xml": "Sitemap XML hợp lệ",
            "https_protocol": "HTTPS / giao thức",
            "internal_links": "Liên kết nội bộ (không 404 hàng loạt)",
            "http_status": "Mã phản hồi HTTP crawl",
            "title_meta": "Title & Meta cơ bản",
            "image_alt": "Thuộc tính ALT ảnh",
            "html_lang": "Thuộc tính lang HTML",
        }
        passed.append(_passed_item(check_id, category, titles.get(check_id, check_id)))

    if ts.get("health_score") is not None and not open_types:
        passed.append(
            _passed_item("overall_clean", "other", "Không phát hiện issue technical", "Quét không ghi nhận lỗi.")
        )

    return passed


def build_category_summaries(
    normalized_issues: list[dict[str, Any]] | None,
    passed_checks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-category counts and worst severity."""
    issues = [i for i in _safe_list(normalized_issues) if isinstance(i, dict)]
    passed = [p for p in _safe_list(passed_checks) if isinstance(p, dict)]
    rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "passed": 1}

    by_cat: dict[str, dict[str, Any]] = {}
    for cat in NORMALIZED_CATEGORIES:
        by_cat[cat] = {
            "category": cat,
            "issue_count": 0,
            "passed_count": 0,
            "worst_severity": "passed",
            "open_issues": 0,
        }

    for issue in issues:
        cat = str(issue.get("category") or "other")
        if cat not in by_cat:
            cat = "other"
        by_cat[cat]["issue_count"] += 1
        if issue.get("severity") != "passed":
            by_cat[cat]["open_issues"] += 1
        sev = str(issue.get("severity") or "medium")
        if rank.get(sev, 0) > rank.get(by_cat[cat]["worst_severity"], 0):
            by_cat[cat]["worst_severity"] = sev

    for chk in passed:
        cat = str(chk.get("category") or "other")
        if cat in by_cat:
            by_cat[cat]["passed_count"] += 1

    summaries = list(by_cat.values())
    summaries.sort(key=lambda s: (-rank.get(s["worst_severity"], 0), -s["open_issues"]))
    return summaries


def build_gsc_intelligence_summary(
    gsc_summary: dict[str, Any] | None = None,
    gsc_opportunities: list[dict[str, Any]] | None = None,
    url_inspection_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compact GSC intelligence block for SaaS payload."""
    gs = _safe_dict(gsc_summary)
    opps = [o for o in _safe_list(gsc_opportunities) if isinstance(o, dict)]
    inspections = [i for i in _safe_list(url_inspection_results) if isinstance(i, dict)]

    canonical_mismatch = 0
    for insp in inspections:
        if insp.get("status") == "error":
            continue
        u = str(insp.get("user_canonical") or "").strip()
        g = str(insp.get("google_canonical") or "").strip()
        if u and g and u.rstrip("/") != g.rstrip("/"):
            canonical_mismatch += 1

    return {
        "enabled": bool(gs.get("enabled")),
        "connected": bool(gs.get("connected", gs.get("enabled"))),
        "property": gs.get("property"),
        "date_range": gs.get("date_range"),
        "start_date": gs.get("start_date"),
        "end_date": gs.get("end_date"),
        "clicks": int(gs.get("clicks") or 0),
        "impressions": int(gs.get("impressions") or 0),
        "avg_ctr": float(gs.get("avg_ctr") or 0.0),
        "avg_position": float(gs.get("avg_position") or 0.0),
        "urls_inspected": int(
            gs.get("urls_inspected")
            or len([i for i in inspections if i.get("status") != "error"])
        ),
        "canonical_mismatch_count": int(gs.get("canonical_mismatch_count") or canonical_mismatch),
        "high_impression_technical_count": int(gs.get("high_impression_technical_count") or 0),
        "opportunity_count": len(opps),
        "opportunities_preview": opps[:5],
        "partial_data": bool(gs.get("partial_data")),
        "quota_exceeded": bool(gs.get("quota_exceeded")),
        "errors": _safe_list(gs.get("errors")),
        "message": gs.get("message") or "",
    }


def _resolve_scan_mode(raw_payload: dict[str, Any]) -> str:
    gs = _safe_dict(raw_payload.get("gsc_summary"))
    if not gs.get("enabled"):
        return "crawl_only"
    if gs.get("partial_data") or gs.get("quota_exceeded"):
        return "partial_gsc"
    return "hybrid_gsc"


def _build_disclaimers(saas: dict[str, Any], raw_payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    gs = _safe_dict(raw_payload.get("gsc_summary"))
    if not gs.get("enabled"):
        out.append(
            "Audit crawl-only — kết nối Google Search Console để xác thực index, canonical và traffic thật."
        )
    if gs.get("partial_data"):
        out.append(str(gs.get("message") or "Dữ liệu GSC một phần (quota/permission)."))
    for err in _safe_list(gs.get("errors")):
        if err:
            out.append(str(err))
    for issue in _safe_list(saas.get("issues")):
        if not isinstance(issue, dict):
            continue
        if issue.get("gsc_badge") == "inferred_warning":
            title = issue.get("title") or issue.get("id") or "Issue"
            out.append(f"{title}: Không thể xác nhận bằng GSC (chưa có URL Inspection).")
    # dedupe preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for line in out:
        if line not in seen:
            seen.add(line)
            deduped.append(line)
    return deduped[:20]


def empty_saas_api_extensions() -> dict[str, Any]:
    """Safe fallback when normalizer fails — legacy response unchanged."""
    return {
        "saas_summary": {
            "technical_score": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "passed_count": 0,
            "gsc_confidence": 0,
            "scan_mode": "crawl_only",
        },
        "priority_fixes": [],
        "category_summaries": [],
        "normalized_issues": [],
        "passed_checks": [],
        "gsc_intelligence_summary": {},
        "partial_data": False,
        "disclaimers": [],
    }


def build_saas_api_extensions(raw_payload: dict[str, Any] | None) -> dict[str, Any]:
    """
    Map full SaaS payload → API extension fields for POST /analyze/technical.

    Does not mutate raw_payload.
    """
    saas = build_saas_technical_payload(raw_payload)
    ic = _safe_dict(saas.get("issue_count"))
    health = _safe_dict(saas.get("health"))
    raw = _safe_dict(raw_payload)

    conf = raw.get("confidence_overall")
    try:
        gsc_conf = round(float(conf) * 100, 1) if conf is not None else 0.0
    except (TypeError, ValueError):
        gsc_conf = 0.0

    passed_checks = _safe_list(saas.get("passed_checks"))
    return {
        "saas_summary": {
            "technical_score": float(health.get("health_score") or 0),
            "critical_count": int(ic.get("critical") or 0),
            "high_count": int(ic.get("high") or 0),
            "medium_count": int(ic.get("medium") or 0),
            "low_count": int(ic.get("low") or 0),
            "passed_count": len(passed_checks),
            "gsc_confidence": gsc_conf,
            "scan_mode": _resolve_scan_mode(raw),
        },
        "priority_fixes": _safe_list(saas.get("top_priority_fixes")),
        "category_summaries": _safe_list(saas.get("category_summaries")),
        "normalized_issues": _safe_list(saas.get("issues")),
        "passed_checks": passed_checks,
        "gsc_intelligence_summary": _safe_dict(saas.get("gsc_intelligence")),
        "partial_data": bool(saas.get("partial_data")),
        "disclaimers": _build_disclaimers(saas, raw),
    }


def build_saas_technical_payload(raw_payload: dict[str, Any] | None) -> dict[str, Any]:
    """
    Main entry: raw TechnicalAnalyzeResponse dict → normalized SaaS output.

    Does not mutate raw_payload. Safe when GSC fields are absent.
    """
    payload = _safe_dict(raw_payload)
    crawl_norm = normalize_crawl_issues(
        payload.get("issues"),
        page_audits=payload.get("page_audits"),
        technical_summary=payload.get("technical_summary"),
    )
    gsc_norm = normalize_gsc_issues(
        gsc_summary=payload.get("gsc_summary"),
        gsc_enriched_pages=payload.get("gsc_enriched_pages"),
        gsc_confirmed_issues=payload.get("gsc_confirmed_issues"),
        url_inspection_results=payload.get("url_inspection_results"),
    )
    merged = merge_duplicate_issues(crawl_norm, gsc_norm)
    passed = build_passed_checks(payload)
    health = calculate_technical_health_score(
        merged,
        passed_checks=passed,
        gsc_summary=payload.get("gsc_summary"),
    )
    gsc_intel = build_gsc_intelligence_summary(
        gsc_summary=payload.get("gsc_summary"),
        gsc_opportunities=payload.get("gsc_opportunities"),
        url_inspection_results=payload.get("url_inspection_results"),
    )

    return {
        "schema_version": 1,
        "domain": payload.get("domain") or "",
        "pages_scanned": int(payload.get("pages_scanned") or 0),
        "audit_id": payload.get("audit_id"),
        "generated_at": _utc_now_iso(),
        "health": health,
        "confidence_overall": payload.get("confidence_overall"),
        "partial_data": bool(gsc_intel.get("partial_data")),
        "gsc_intelligence": gsc_intel,
        "issues": merged,
        "passed_checks": passed,
        "category_summaries": build_category_summaries(merged, passed),
        "top_priority_fixes": build_top_priority_fixes(merged, limit=5),
        "issue_count": {
            "total": len(merged),
            "critical": sum(1 for i in merged if i.get("severity") == "critical"),
            "high": sum(1 for i in merged if i.get("severity") == "high"),
            "medium": sum(1 for i in merged if i.get("severity") == "medium"),
            "low": sum(1 for i in merged if i.get("severity") == "low"),
        },
        "legacy": {
            "technical_summary": payload.get("technical_summary"),
            "has_legacy_issues": bool(payload.get("issues")),
        },
    }
