"""Chuẩn hóa kết quả Technical SEO cho panel Chatbot."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.technical_output_normalizer import build_saas_technical_payload


def _safe_dict(val: Any) -> dict[str, Any]:
    return dict(val) if isinstance(val, dict) else {}


def _safe_list(val: Any) -> list[Any]:
    return list(val) if isinstance(val, list) else []


def _severity_bucket(sev: str) -> str:
    s = str(sev or "").strip().lower()
    if s in ("critical", "high"):
        return "critical"
    if s in ("medium",):
        return "warning"
    return "suggestion"


def _issue_item(iss: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(iss.get("id") or iss.get("type") or ""),
        "title": str(iss.get("title") or iss.get("type") or "Vấn đề technical"),
        "message": str(iss.get("message") or iss.get("explanation") or ""),
        "suggestion": str(
            iss.get("remediation")
            or iss.get("suggested_fix")
            or iss.get("fix")
            or iss.get("suggestion")
            or ""
        ),
    }


def _bucket_legacy_issues(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    critical: list[dict[str, str]] = []
    warning: list[dict[str, str]] = []
    suggestion: list[dict[str, str]] = []
    for iss in issues or []:
        if not isinstance(iss, dict):
            continue
        item = _issue_item(iss)
        bucket = _severity_bucket(str(iss.get("severity") or "low"))
        if bucket == "critical":
            critical.append(item)
        elif bucket == "warning":
            warning.append(item)
        else:
            suggestion.append(item)
    return {
        "critical": critical[:25],
        "warning": warning[:25],
        "suggestion": suggestion[:15],
    }


def _pick_primary_page(audit: dict[str, Any], url: str) -> dict[str, Any]:
    target = str(url or "").strip().rstrip("/")
    for row in _safe_list(audit.get("page_audits")):
        if not isinstance(row, dict):
            continue
        ru = str(row.get("url") or "").strip().rstrip("/")
        if ru == target:
            return row
    pages = _safe_list(audit.get("pages"))
    for row in pages:
        if not isinstance(row, dict):
            continue
        ru = str(row.get("url") or "").strip().rstrip("/")
        if ru == target:
            return row
    if audit.get("page_audits"):
        first = audit["page_audits"][0]
        return first if isinstance(first, dict) else {}
    if pages:
        first = pages[0]
        return first if isinstance(first, dict) else {}
    return {}


def _indexability_label(page_row: dict[str, Any], audit: dict[str, Any]) -> str:
    decision = _safe_dict(page_row.get("decision"))
    if decision.get("indexable") is True:
        return "Có thể index"
    if decision.get("indexable") is False:
        reasons = _safe_list(decision.get("blocking_reasons"))
        if reasons:
            return "; ".join(str(r) for r in reasons[:3])
        return "Không index được"
    core = _safe_dict(audit.get("seo_intelligence_core"))
    idx = _safe_dict(core.get("indexability"))
    ratio = idx.get("indexable_ratio")
    if ratio is not None:
        try:
            pct = round(float(ratio) * 100, 1)
            return f"Tỷ lệ indexable: {pct}%"
        except (TypeError, ValueError):
            pass
    return "—"


def _robots_meta_label(page_row: dict[str, Any]) -> str:
    parsed = _safe_dict(page_row.get("parsed"))
    robots = str(parsed.get("robots_meta") or parsed.get("meta_robots") or "").strip()
    if robots:
        return robots
    sim = _safe_dict(page_row.get("simulation"))
    if sim.get("blocked_by_robots"):
        return "Blocked by robots.txt"
    return "—"


def _sitemap_label(audit: dict[str, Any]) -> str:
    sm = _safe_dict(audit.get("sitemap"))
    status = int(sm.get("status") or 0)
    urls = _safe_list(sm.get("urls"))
    if status == 200 and urls:
        return f"OK — {len(urls)} URL trong sitemap"
    if status == 200:
        return "Sitemap trống hoặc không parse được URL"
    if status:
        return f"HTTP {status}"
    return "Không truy cập được sitemap"


def _speed_label(page_row: dict[str, Any], audit: dict[str, Any]) -> str:
    perf = _safe_dict(page_row.get("performance"))
    if perf.get("lcp_ms") is not None:
        return f"LCP ~{perf.get('lcp_ms')}ms"
    ts = _safe_dict(audit.get("technical_summary"))
    if ts.get("avg_ttfb_ms") is not None:
        return f"TTFB ~{ts.get('avg_ttfb_ms')}ms"
    return "—"


def _headings_from_page(page_row: dict[str, Any]) -> dict[str, list[str]]:
    parsed = _safe_dict(page_row.get("parsed"))
    headings = _safe_dict(parsed.get("headings"))
    if headings:
        return {
            "h1": [str(x) for x in _safe_list(headings.get("h1"))[:6]],
            "h2": [str(x) for x in _safe_list(headings.get("h2"))[:8]],
            "h3": [str(x) for x in _safe_list(headings.get("h3"))[:8]],
        }
    return {
        "h1": [str(x) for x in _safe_list(parsed.get("h1_list"))[:6]],
        "h2": [str(x) for x in _safe_list(parsed.get("h2_list"))[:8]],
        "h3": [str(x) for x in _safe_list(parsed.get("h3_list"))[:8]],
    }


def build_chatbot_technical_report(
    audit: dict[str, Any] | None,
    *,
    mode: str,
    url: str,
) -> dict[str, Any]:
    """Map raw technical audit dict → chatbot panel report."""
    raw = _safe_dict(audit)
    saas = build_saas_technical_payload(raw)
    health = _safe_dict(saas.get("health"))
    health_score = int(round(float(health.get("health_score") or 0)))
    page_row = _pick_primary_page(raw, url)
    parsed = _safe_dict(page_row.get("parsed"))
    ts = _safe_dict(raw.get("technical_summary"))

    merged_issues = _safe_list(saas.get("issues"))
    if merged_issues:
        buckets = {"critical": [], "warning": [], "suggestion": []}
        for iss in merged_issues:
            if not isinstance(iss, dict):
                continue
            item = _issue_item(iss)
            buckets[_severity_bucket(str(iss.get("severity") or "low"))].append(item)
        issues = {
            "critical": buckets["critical"][:25],
            "warning": buckets["warning"][:25],
            "suggestion": buckets["suggestion"][:15],
        }
    else:
        legacy = []
        for iss in _safe_list(raw.get("issues")):
            if hasattr(iss, "model_dump"):
                legacy.append(iss.model_dump())
            elif isinstance(iss, dict):
                legacy.append(iss)
        issues = _bucket_legacy_issues(legacy)

    headings = _headings_from_page(page_row)
    broken = int(ts.get("broken_internal_links") or len(_safe_list(raw.get("broken_internal_links"))) or 0)
    redirects = int(ts.get("redirect_chains") or len(_safe_list(raw.get("redirect_chains"))) or 0)
    images_missing = int(parsed.get("images_missing_alt") or page_row.get("images_missing_alt") or 0)

    overview = {
        "http_status": str(page_row.get("status") or parsed.get("status") or "—"),
        "indexability": _indexability_label(page_row, raw),
        "canonical": str(parsed.get("canonical") or page_row.get("canonical") or "—"),
        "robots_meta": _robots_meta_label(page_row),
        "sitemap": _sitemap_label(raw),
        "title": str(parsed.get("title") or page_row.get("title") or "—"),
        "meta_description": str(parsed.get("meta_description") or page_row.get("meta_description") or "—"),
        "headings": headings,
        "broken_links": broken,
        "redirects": redirects,
        "images_missing_alt": images_missing,
        "page_speed": _speed_label(page_row, raw),
    }

    domain = str(raw.get("domain") or "").strip()
    if not domain and url:
        domain = urlparse(url).netloc

    return {
        "mode": str(mode or "quick"),
        "url": str(url or raw.get("start_url") or ""),
        "domain": domain,
        "health_score": health_score,
        "pages_scanned": int(raw.get("pages_scanned") or ts.get("internal_pages") or 0),
        "passed": health_score >= 60,
        "grade_label": (
            "Tốt" if health_score >= 80 else "Khá" if health_score >= 60 else "Cần cải thiện" if health_score >= 40 else "Yếu"
        ),
        "overview": overview,
        "issues": issues,
        "audit_id": raw.get("audit_id"),
        "issue_counts": {
            "critical": len(issues["critical"]),
            "warning": len(issues["warning"]),
            "suggestion": len(issues["suggestion"]),
        },
    }
