"""
Hybrid Technical Audit — enrich crawl results with Google Search Console data.

crawl_data + Search Analytics + URL Inspection → higher-confidence audit output.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from app.services.gsc_client import (
    GscClient,
    GscClientError,
    GscNotConnectedError,
    GscPermissionError,
    GscQuotaError,
    resolve_gsc_date_range,
)
from app.services.gsc_priority import (
    append_gsc_disclaimer_if_needed,
    compute_priority_components,
    detect_ctr_opportunities,
    detect_high_impression_technical_issues,
    detect_traffic_drop_opportunities,
    gsc_evidence_badge,
    score_urls_for_inspection,
)
from app.services.seo_normalize import normalize_url_safe

_LOG = logging.getLogger(__name__)


def _url_key(raw: str) -> str:
    if not raw:
        return ""
    try:
        return normalize_url_safe(raw).rstrip("/")
    except Exception:
        return str(raw).strip().rstrip("/")


def _build_url_lookup(metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map normalized URL → best matching GSC page row."""
    out: dict[str, dict[str, Any]] = {}
    for row in metrics:
        page = str(row.get("page") or "").strip()
        if not page:
            continue
        key = _url_key(page)
        prev = out.get(key)
        if not prev or int(row.get("impressions") or 0) > int(prev.get("impressions") or 0):
            out[key] = dict(row)
        # Also index without www variant
        try:
            p = urlparse(page)
            host = (p.netloc or "").lower()
            if host.startswith("www."):
                alt = _url_key(page.replace("://www.", "://", 1))
                if alt and alt not in out:
                    out[alt] = dict(row)
        except Exception:
            pass
    return out


def _page_type_for_url(url: str, page_audits: list[dict[str, Any]]) -> str:
    for pa in page_audits:
        if _url_key(str(pa.get("url") or "")) == _url_key(url):
            dec = pa.get("decision") or pa.get("decision_audit") or {}
            return str(dec.get("page_type") or pa.get("page_type") or "unknown")
    return "unknown"


def _collect_inspection_candidates(
    *,
    start_url: str,
    pages: list[dict[str, Any]],
    sitemap: dict[str, Any],
    issues: list[dict[str, Any]],
    page_audits: list[dict[str, Any]],
    page_metrics_by_url: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score URLs for URL Inspection quota."""
    crawl_urls = {_url_key(str(p.get("url") or "")) for p in pages if p.get("url")}
    sitemap_urls = {_url_key(u) for u in (sitemap.get("urls") or []) if u}
    candidates: dict[str, dict[str, Any]] = {}

    def add(url: str, score: float, reason: str) -> None:
        u = str(url or "").strip()
        if not u:
            return
        key = _url_key(u)
        prev = candidates.get(key)
        if not prev or score > (prev.get("priority_score") or 0):
            candidates[key] = {"url": u, "priority_score": score, "reason": reason}

    # Homepage / start URL
    add(start_url, 95.0, "start_url")
    if pages:
        add(pages[0].get("url") or "", 90.0, "crawl_entry")

    # High GSC traffic pages
    for key, pm in page_metrics_by_url.items():
        imp = int(pm.get("impressions") or 0)
        clicks = int(pm.get("clicks") or 0)
        if imp >= 50 or clicks >= 5:
            add(pm.get("page") or key, 70.0 + min(20.0, imp / 100.0), "gsc_traffic")

    # High severity issues
    for issue in issues:
        if str(issue.get("severity") or "").lower() != "high":
            continue
        url = str(issue.get("url") or "").strip()
        if url:
            add(url, 82.0, "high_severity_issue")

    # Canonical / noindex / index risk
    index_risk_types = {
        "indexability_blocked",
        "indexability_signal_conflict",
        "robots_meta_noindex_contradiction",
        "canonical_cross_host",
        "canonical_self_mismatch",
        "google_may_ignore_canonical",
        "page_unlikely_indexed",
    }
    for issue in issues:
        if str(issue.get("type") or "") in index_risk_types:
            url = str(issue.get("url") or "").strip()
            if url:
                add(url, 88.0, "index_canonical_risk")

    # Important page types
    for pa in page_audits:
        url = str(pa.get("url") or "").strip()
        if not url:
            continue
        pt = _page_type_for_url(url, page_audits)
        if pt in ("homepage", "category", "landing"):
            add(url, 75.0, f"page_type_{pt}")

    # Sitemap ↔ crawl mismatches
    for su in sitemap_urls - crawl_urls:
        if su:
            add(su, 68.0, "in_sitemap_not_crawled")
    for cu in crawl_urls - sitemap_urls:
        if cu:
            add(cu, 62.0, "crawled_not_in_sitemap")

    return list(candidates.values())


def enrich_technical_audit_with_gsc(
    *,
    user_id: int,
    gsc_property: str,
    gsc_date_range: str = "28d",
    gsc_start_date: str | None = None,
    gsc_end_date: str | None = None,
    url_inspection_limit: int = 10,
    start_url: str,
    pages: list[dict[str, Any]],
    sitemap: dict[str, Any],
    issues: list[dict[str, Any]],
    page_audits: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run GSC enrichment. Never raises to caller for API failures — returns status in gsc_summary.
    Mutates issues in place (priority_score, gsc_*, badges).
    """
    empty: dict[str, Any] = {
        "gsc_summary": {
            "enabled": False,
            "connected": False,
            "property": None,
            "message": "GSC enrichment không được bật.",
        },
        "gsc_enriched_pages": [],
        "gsc_confirmed_issues": [],
        "gsc_opportunities": [],
        "url_inspection_results": [],
        "confidence_overall": None,
        "issues": issues,
        "partial_data": False,
        "errors": [],
    }

    site_url = (gsc_property or "").strip()
    if not site_url:
        empty["gsc_summary"]["message"] = "Chưa chọn property GSC."
        return empty

    client = GscClient.for_user(user_id)
    if not client:
        empty["gsc_summary"]["message"] = (
            "Kết nối Google Search Console để xác thực trạng thái index, canonical và traffic thật."
        )
        _apply_no_gsc_disclaimers(issues)
        return empty

    start_d, end_d = resolve_gsc_date_range(gsc_date_range, start_date=gsc_start_date, end_date=gsc_end_date)
    errors: list[str] = []
    partial = False
    quota_hit = False

    page_metrics: list[dict[str, Any]] = []
    prior_metrics: list[dict[str, Any]] = []
    try:
        page_metrics = client.fetch_page_performance(
            site_url=site_url,
            start_date=start_d,
            end_date=end_d,
            row_limit=5000,
        )
    except GscPermissionError as exc:
        errors.append(str(exc))
        empty["gsc_summary"] = {
            "enabled": True,
            "connected": False,
            "property": site_url,
            "partial_data": True,
            "quota_exceeded": False,
            "errors": errors,
            "message": f"Không đủ quyền GSC — audit crawl tiếp tục: {exc}",
        }
        _apply_no_gsc_disclaimers(issues)
        empty["errors"] = errors
        empty["issues"] = issues
        empty["partial_data"] = True
        return empty
    except GscQuotaError as exc:
        errors.append(str(exc))
        partial = True
        quota_hit = True
    except GscClientError as exc:
        errors.append(str(exc))
        partial = True

    # Prior period for traffic drop (same length, immediately before current window)
    try:
        sd = date.fromisoformat(start_d)
        ed = date.fromisoformat(end_d)
        span = (ed - sd).days + 1
        prior_end = sd - timedelta(days=1)
        prior_start = prior_end - timedelta(days=span - 1)
        prior_metrics = client.fetch_page_performance(
            site_url=site_url,
            start_date=prior_start.isoformat(),
            end_date=prior_end.isoformat(),
            row_limit=3000,
        )
    except GscQuotaError as exc:
        errors.append(str(exc))
        partial = True
        quota_hit = True
    except Exception as exc:
        _LOG.debug("prior period GSC fetch skipped: %s", exc)

    page_metrics_by_url = _build_url_lookup(page_metrics)
    prior_by_url = _build_url_lookup(prior_metrics)

    # URL Inspection (quota-limited)
    inspection_limit = max(0, min(int(url_inspection_limit or 0), 50))
    inspection_results: list[dict[str, Any]] = []
    inspections_by_url: dict[str, dict[str, Any]] = {}

    if inspection_limit > 0:
        candidates = _collect_inspection_candidates(
            start_url=start_url,
            pages=pages,
            sitemap=sitemap,
            issues=issues,
            page_audits=page_audits,
            page_metrics_by_url=page_metrics_by_url,
        )
        urls_to_inspect = score_urls_for_inspection(candidates, limit=inspection_limit)
        for insp_url in urls_to_inspect:
            try:
                result = client.inspect_url(site_url=site_url, inspection_url=insp_url)
                result["status"] = "ok"
                inspection_results.append(result)
                inspections_by_url[_url_key(insp_url)] = result
            except GscQuotaError as exc:
                errors.append(str(exc))
                partial = True
                quota_hit = True
                break
            except GscClientError as exc:
                errors.append(f"{insp_url}: {exc}")
                partial = True
                inspection_results.append(
                    {
                        "inspection_url": insp_url,
                        "status": "error",
                        "error": str(exc),
                    }
                )

    # Enrich issues
    gsc_confirmed: list[dict[str, Any]] = []
    for issue in issues:
        url = str(issue.get("url") or "").strip()
        key = _url_key(url)
        pm = page_metrics_by_url.get(key) or {}
        insp = inspections_by_url.get(key)
        if not issue.get("page_type"):
            issue["page_type"] = _page_type_for_url(url, page_audits) if url else None

        confirmed = bool(insp and gsc_evidence_badge(issue, inspection=insp) == "gsc_confirmed")
        badge = gsc_evidence_badge(issue, inspection=insp, gsc_confirmed=confirmed)
        issue["gsc_badge"] = badge
        if badge == "gsc_confirmed":
            issue["source"] = "hybrid"
        elif str(issue.get("source") or "").lower() not in ("gsc", "hybrid", "crawl", "crux", "pagespeed"):
            issue["source"] = "crawl"
        components = compute_priority_components(
            issue,
            page_metrics=pm,
            inspection=insp,
            has_gsc=True,
            affected_url_count=1 if url else None,
            confidence=issue.get("confidence"),
        )
        issue["priority_score"] = components["priority_score"]
        issue["priority_tier"] = components["priority_tier"]
        if pm:
            issue["gsc_clicks"] = int(pm.get("clicks") or 0)
            issue["gsc_impressions"] = int(pm.get("impressions") or 0)
            issue["gsc_ctr"] = float(pm.get("ctr") or 0.0)
            issue["gsc_position"] = float(pm.get("position") or 0.0)
        if insp and insp.get("status") != "error":
            issue["gsc_index_verdict"] = insp.get("index_verdict")
            issue["gsc_coverage_state"] = insp.get("coverage_state")
            issue["gsc_user_canonical"] = insp.get("user_canonical")
            issue["gsc_google_canonical"] = insp.get("google_canonical")
            issue["gsc_last_crawl_time"] = insp.get("last_crawl_time")
        append_gsc_disclaimer_if_needed(issue, has_inspection=bool(insp))

        if badge == "gsc_confirmed":
            gsc_confirmed.append(
                {
                    "type": issue.get("type"),
                    "url": url,
                    "severity": issue.get("severity"),
                    "message": issue.get("message"),
                    "index_verdict": (insp or {}).get("index_verdict"),
                    "coverage_state": (insp or {}).get("coverage_state"),
                }
            )

    # Sort issues by priority_score descending (stable for equal scores)
    issues.sort(key=lambda i: (-(i.get("priority_score") or 0), str(i.get("type") or "")))

    # Enriched pages list
    enriched_pages: list[dict[str, Any]] = []
    for key, pm in sorted(page_metrics_by_url.items(), key=lambda x: -(x[1].get("impressions") or 0))[:100]:
        insp = inspections_by_url.get(key)
        enriched_pages.append(
            {
                "page": pm.get("page") or key,
                "clicks": int(pm.get("clicks") or 0),
                "impressions": int(pm.get("impressions") or 0),
                "ctr": float(pm.get("ctr") or 0.0),
                "position": float(pm.get("position") or 0.0),
                "inspection": {
                    "index_verdict": (insp or {}).get("index_verdict"),
                    "coverage_state": (insp or {}).get("coverage_state"),
                    "user_canonical": (insp or {}).get("user_canonical"),
                    "google_canonical": (insp or {}).get("google_canonical"),
                    "last_crawl_time": (insp or {}).get("last_crawl_time"),
                }
                if insp
                else None,
            }
        )

    # Opportunities
    opportunities: list[dict[str, Any]] = []
    opportunities.extend(detect_high_impression_technical_issues(issues, page_metrics_by_url))
    opportunities.extend(detect_ctr_opportunities(page_metrics_by_url))
    if prior_by_url:
        opportunities.extend(detect_traffic_drop_opportunities(page_metrics_by_url, prior_by_url))

    # Summary aggregates
    total_clicks = sum(int(r.get("clicks") or 0) for r in page_metrics)
    total_impressions = sum(int(r.get("impressions") or 0) for r in page_metrics)
    avg_ctr = (total_clicks / total_impressions) if total_impressions else 0.0
    positions = [float(r.get("position") or 0) for r in page_metrics if r.get("position")]
    avg_position = sum(positions) / len(positions) if positions else 0.0
    canonical_mismatches = sum(
        1
        for ir in inspection_results
        if ir.get("user_canonical")
        and ir.get("google_canonical")
        and _url_key(str(ir["user_canonical"])) != _url_key(str(ir["google_canonical"]))
    )
    high_imp_tech = len([o for o in opportunities if o.get("type") == "high_impression_technical_issue"])

    confidence = _compute_confidence_overall(
        issues=issues,
        inspection_count=len([r for r in inspection_results if r.get("status") != "error"]),
        page_metrics_count=len(page_metrics),
        partial=partial,
    )

    gsc_summary = {
        "enabled": True,
        "connected": True,
        "property": site_url,
        "date_range": gsc_date_range,
        "start_date": start_d,
        "end_date": end_d,
        "clicks": total_clicks,
        "impressions": total_impressions,
        "avg_ctr": round(avg_ctr, 4),
        "avg_position": round(avg_position, 2),
        "pages_with_data": len(page_metrics),
        "urls_inspected": len([r for r in inspection_results if r.get("status") != "error"]),
        "urls_inspection_limit": inspection_limit,
        "canonical_mismatch_count": canonical_mismatches,
        "high_impression_technical_count": high_imp_tech,
        "quota_exceeded": quota_hit,
        "partial_data": partial,
        "errors": errors,
        "message": _status_message(errors, partial, quota_hit),
    }

    return {
        "gsc_summary": gsc_summary,
        "gsc_enriched_pages": enriched_pages,
        "gsc_confirmed_issues": gsc_confirmed,
        "gsc_opportunities": opportunities,
        "url_inspection_results": inspection_results,
        "confidence_overall": confidence,
        "issues": issues,
        "partial_data": partial,
        "errors": errors,
    }


def _apply_no_gsc_disclaimers(issues: list[dict[str, Any]]) -> None:
    from app.services.gsc_priority import INDEX_INFERENCE_TYPES

    for issue in issues:
        if str(issue.get("type") or "") in INDEX_INFERENCE_TYPES:
            append_gsc_disclaimer_if_needed(issue, has_inspection=False)
        issue["gsc_badge"] = issue.get("gsc_badge") or "crawl_detected"
        if str(issue.get("source") or "").lower() not in ("gsc", "hybrid", "crawl", "crux", "pagespeed"):
            issue["source"] = "crawl"
        if issue.get("priority_score") is None:
            components = compute_priority_components(
                issue,
                has_gsc=False,
                affected_url_count=1 if issue.get("url") else None,
                confidence=issue.get("confidence"),
            )
            issue["priority_score"] = components["priority_score"]
            issue["priority_tier"] = components["priority_tier"]


def _summary_shell(
    site_url: str,
    start_d: str,
    end_d: str,
    errors: list[str],
    *,
    partial: bool,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "connected": True,
        "property": site_url,
        "start_date": start_d,
        "end_date": end_d,
        "partial_data": partial,
        "errors": errors,
        "message": errors[0] if errors else "Không lấy được dữ liệu GSC.",
    }


def _status_message(errors: list[str], partial: bool, quota_hit: bool) -> str:
    if quota_hit:
        return "Audit hoàn tất với dữ liệu GSC một phần — quota URL Inspection đã hết."
    if partial and errors:
        return "Audit hoàn tất với dữ liệu GSC một phần: " + errors[0][:200]
    if errors:
        return errors[0][:300]
    return "Đã tích hợp Search Analytics và URL Inspection."


def _compute_confidence_overall(
    *,
    issues: list[dict[str, Any]],
    inspection_count: int,
    page_metrics_count: int,
    partial: bool,
) -> float:
    base = 0.55
    if page_metrics_count > 0:
        base += 0.15
    if inspection_count > 0:
        base += min(0.25, inspection_count * 0.025)
    gsc_confirmed = sum(1 for i in issues if i.get("gsc_badge") == "gsc_confirmed")
    base += min(0.1, gsc_confirmed * 0.02)
    if partial:
        base -= 0.08
    return round(max(0.35, min(0.98, base)), 3)
