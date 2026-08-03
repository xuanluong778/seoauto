"""Slim / paginate large API payloads without breaking legacy field names."""

from __future__ import annotations

import copy
from typing import Any

_DEFAULT_URL_CAP = 5

_HEAVY_AUDIT_ARRAY_KEYS = (
    "gsc_enriched_pages",
    "url_inspection_results",
    "gsc_confirmed_issues",
    "gsc_opportunities",
    "broken_internal_links",
    "redirect_chains",
    "internal_link_structure",
    "page_audits",
    "ranking_priorities",
)


def _safe_list(val: object) -> list:
    return val if isinstance(val, list) else []


def _safe_dict(val: object) -> dict:
    return val if isinstance(val, dict) else {}


def paginate_list(items: list | None, page: int, page_size: int) -> tuple[list, int]:
    arr = _safe_list(items)
    total = len(arr)
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    start = (page - 1) * page_size
    end = start + page_size
    return arr[start:end], total


def slim_issue_urls(issue: dict, max_urls: int = _DEFAULT_URL_CAP) -> dict:
    if not isinstance(issue, dict):
        return {}
    out = dict(issue)
    urls = _safe_list(out.get("affected_urls"))
    if not urls:
        urls = _safe_list(out.get("sample_urls"))
    if not urls and out.get("url"):
        urls = [str(out.get("url"))]
    total = len(urls)
    if total > max_urls:
        out["affected_urls_total"] = total
        capped = urls[:max_urls]
        out["affected_urls"] = capped
        out["sample_urls"] = capped[: max_urls]
        out["_urls_truncated"] = True
    return out


def _slim_issues_list(issues: list | None, max_urls: int = _DEFAULT_URL_CAP) -> list[dict]:
    return [slim_issue_urls(i, max_urls=max_urls) for i in _safe_list(issues) if isinstance(i, dict)]


def slim_technical_dashboard_v2(dash: dict | None, max_urls: int = _DEFAULT_URL_CAP) -> dict | None:
    if not dash or not isinstance(dash, dict):
        return dash
    out = copy.deepcopy(dash)
    for key in ("issues", "priority_issues"):
        if key in out:
            out[key] = _slim_issues_list(out.get(key), max_urls=max_urls)
    return out


def collect_audit_issue_pool(run: dict) -> list[dict]:
    """Unified issue list for pagination — prefer normalized, then v2, then legacy."""
    norm = _safe_list(run.get("normalized_issues"))
    if norm:
        return [dict(i) for i in norm if isinstance(i, dict)]
    dash = _safe_dict(run.get("technical_dashboard_v2"))
    v2_issues = _safe_list(dash.get("issues"))
    if v2_issues:
        return [dict(i) for i in v2_issues if isinstance(i, dict)]
    legacy = _safe_list(run.get("issues"))
    return [dict(i) for i in legacy if isinstance(i, dict)]


def find_audit_issue(run: dict, issue_id: str) -> dict | None:
    needle = str(issue_id or "").strip()
    if not needle:
        return None
    for issue in collect_audit_issue_pool(run):
        for key in ("issue_id", "id", "type", "issue_type", "_issue_type"):
            val = issue.get(key)
            if val is not None and str(val) == needle:
                return issue
    return None


def shape_audit_response(
    run: dict,
    *,
    lite: bool = False,
    issues_page: int | None = None,
    issues_page_size: int = 50,
    max_urls_per_issue: int = _DEFAULT_URL_CAP,
) -> dict:
    """
    Return audit dict safe for JSON — optional lite mode and issue pagination.
    Legacy field names preserved; empty arrays used instead of omitting keys.
    """
    out = copy.deepcopy(run)
    out["issues"] = _safe_list(out.get("issues"))
    out["normalized_issues"] = _safe_list(out.get("normalized_issues"))
    out["passed_checks"] = _safe_list(out.get("passed_checks"))
    out["priority_fixes"] = _safe_list(out.get("priority_fixes"))
    out["category_summaries"] = _safe_list(out.get("category_summaries"))

    if lite:
        for key in _HEAVY_AUDIT_ARRAY_KEYS:
            if key in out:
                out[key] = []
        out["issues"] = []
        out["normalized_issues"] = []
        dash = out.get("technical_dashboard_v2")
        if isinstance(dash, dict):
            out["technical_dashboard_v2"] = slim_technical_dashboard_v2(dash, max_urls=max_urls_per_issue)
        else:
            # Legacy audits: keep slimmed legacy issues inside v2-shaped path via normalized rebuild on client
            out["normalized_issues"] = _slim_issues_list(
                _safe_list(run.get("normalized_issues")) or _safe_list(run.get("issues")),
                max_urls=max_urls_per_issue,
            )
        out["_payload_mode"] = "lite"

    if issues_page is not None:
        pool = collect_audit_issue_pool(run)
        page_items, total = paginate_list(pool, issues_page, issues_page_size)
        slimmed = _slim_issues_list(page_items, max_urls=max_urls_per_issue if lite else 10_000)
        out["normalized_issues"] = slimmed
        out["issues"] = []
        out["issues_pagination"] = {
            "page": issues_page,
            "page_size": issues_page_size,
            "total": total,
            "has_more": issues_page * issues_page_size < total,
        }
        if lite and isinstance(out.get("technical_dashboard_v2"), dict):
            dash = dict(out["technical_dashboard_v2"])
            dash["issues"] = slimmed
            out["technical_dashboard_v2"] = dash

    return out


def shape_keyword_research_response(
    payload: dict,
    *,
    keywords_page: int | None = None,
    keywords_page_size: int = 100,
    clusters_page: int | None = None,
    clusters_page_size: int = 50,
    summary_only: bool = False,
) -> dict:
    out = copy.deepcopy(payload)
    keywords = _safe_list(out.get("keywords"))
    clusters = _safe_list(out.get("clusters"))
    meta = _safe_dict(out.get("meta"))

    if summary_only:
        return {
            "meta": meta,
            "keywords_total": len(keywords),
            "clusters_total": len(clusters),
            "keywords": keywords[: min(20, len(keywords))],
            "clusters": clusters[: min(5, len(clusters))],
            "_payload_mode": "summary",
            "_full_available": True,
        }

    if keywords_page is not None:
        page_items, total = paginate_list(keywords, keywords_page, keywords_page_size)
        out["keywords"] = page_items
        out["keywords_pagination"] = {
            "page": keywords_page,
            "page_size": keywords_page_size,
            "total": total,
            "has_more": keywords_page * keywords_page_size < total,
        }

    if clusters_page is not None:
        page_items, total = paginate_list(clusters, clusters_page, clusters_page_size)
        out["clusters"] = page_items
        out["clusters_pagination"] = {
            "page": clusters_page,
            "page_size": clusters_page_size,
            "total": total,
            "has_more": clusters_page * clusters_page_size < total,
        }

    return out


def shape_keyword_cluster_history_response(
    payload: dict,
    *,
    summary_only: bool = False,
) -> dict:
    if not summary_only:
        return payload
    result = _safe_dict(payload.get("result")) if "result" in payload else _safe_dict(payload)
    clusters = _safe_list(result.get("clusters"))
    keywords = _safe_list(payload.get("keywords"))
    return {
        "project": payload.get("project"),
        "keywords_total": len(keywords),
        "clusters_total": len(clusters),
        "result": {
            "meta": _safe_dict(result.get("meta")),
            "clusters": clusters[: min(5, len(clusters))],
            "content_plans": _safe_list(result.get("content_plans"))[:5],
            "_payload_mode": "summary",
            "_full_available": True,
        },
        "keywords": keywords[: min(30, len(keywords))],
    }


def shape_check_free_session(
    session: dict,
    *,
    items_page: int | None = None,
    items_page_size: int = 50,
) -> dict:
    if items_page is None:
        return session
    out = dict(session)
    items = _safe_list(out.get("items"))
    page_items, total = paginate_list(items, items_page, items_page_size)
    out["items"] = page_items
    out["items_pagination"] = {
        "page": items_page,
        "page_size": items_page_size,
        "total": total,
        "has_more": items_page * items_page_size < total,
    }
    return out
