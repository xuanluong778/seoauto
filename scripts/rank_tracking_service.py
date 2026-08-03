"""Rank Tracking business logic — SERP check, domain rank detection, summary."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from app.services import dataforseo_client
from app.services.rank_tracking_store import (
    append_result,
    get_project,
    latest_result_for_keyword,
    list_keywords,
    list_projects,
    previous_result_for_keyword,
)


def normalize_domain(domain: str) -> str:
    raw = str(domain or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.split("/")[0].split(":")[0]
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def domain_matches(candidate: str, target_domain: str) -> bool:
    cand = normalize_domain(candidate)
    target = normalize_domain(target_domain)
    if not cand or not target:
        return False
    return cand == target or cand.endswith("." + target) or target.endswith("." + cand)


def find_domain_rank(items: list[dict[str, Any]], domain: str) -> dict[str, Any] | None:
    """Return first organic match for target domain within SERP items."""
    target = normalize_domain(domain)
    if not target:
        return None
    for item in items or []:
        if str(item.get("type") or "").lower() != "organic":
            continue
        url = str(item.get("url") or "")
        item_domain = str(item.get("domain") or "") or urlparse(url).netloc
        if not domain_matches(item_domain, target):
            continue
        rank_abs = item.get("rank_absolute")
        rank_grp = item.get("rank_group")
        try:
            rank_abs_i = int(rank_abs) if rank_abs is not None else None
        except (TypeError, ValueError):
            rank_abs_i = None
        try:
            rank_grp_i = int(rank_grp) if rank_grp is not None else rank_abs_i
        except (TypeError, ValueError):
            rank_grp_i = rank_abs_i
        return {
            "rank_absolute": rank_abs_i,
            "rank_group": rank_grp_i,
            "url": url or None,
            "title": str(item.get("title") or "").strip() or None,
            "domain": normalize_domain(item_domain),
        }
    return None


def _compute_rank_change(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return int(previous) - int(current)


def check_keyword_now(user_id: int, keyword_id: str, *, depth: int = 100) -> dict[str, Any]:
    from app.services.rank_tracking_store import _find_keyword

    kw_row = _find_keyword(keyword_id, user_id)
    if not kw_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy keyword.")
    project = get_project(str(kw_row.get("project_id")), user_id)
    keyword = str(kw_row.get("keyword") or "")
    domain = str(project.get("domain") or "")

    serp = dataforseo_client.google_serp_live_advanced(
        keyword,
        location_name=str(project.get("location_name") or "Vietnam"),
        language_name=str(project.get("language_name") or "Vietnamese"),
        device=str(project.get("device") or "desktop"),
        depth=depth,
    )
    match = find_domain_rank(serp.get("items") or [], domain)
    prev = latest_result_for_keyword(keyword_id, user_id)
    prev_rank = prev.get("rank_absolute") if prev else None
    current_rank = match.get("rank_absolute") if match else None
    rank_change = _compute_rank_change(current_rank, prev_rank)

    result = append_result(
        user_id=user_id,
        project_id=str(project["id"]),
        keyword_id=keyword_id,
        keyword=keyword,
        domain=domain,
        rank_absolute=current_rank,
        rank_group=(match or {}).get("rank_group"),
        url=(match or {}).get("url"),
        title=(match or {}).get("title"),
        rank_change=rank_change,
        mock=bool(serp.get("mock")),
        serp_depth=depth,
    )
    return {
        "result": result,
        "previous_rank": prev_rank,
        "mock": bool(serp.get("mock")),
        "fallback_mock": bool(serp.get("fallback_mock")),
    }


def check_project_now(user_id: int, project_id: str, *, depth: int = 100) -> dict[str, Any]:
    get_project(project_id, user_id)
    keywords = list_keywords(user_id, project_id=project_id)
    if not keywords:
        raise HTTPException(status_code=400, detail="Project chưa có keyword nào.")
    checked: list[dict[str, Any]] = []
    errors: list[str] = []
    mock_used = False
    for kw in keywords:
        try:
            out = check_keyword_now(user_id, str(kw["id"]), depth=depth)
            if out.get("mock"):
                mock_used = True
            checked.append({"keyword_id": kw["id"], "keyword": kw["keyword"], "result": out["result"]})
        except HTTPException as exc:
            errors.append(f"{kw.get('keyword')}: {exc.detail}")
        except Exception as exc:
            errors.append(f"{kw.get('keyword')}: {exc}")
    return {
        "project_id": project_id,
        "checked_count": len(checked),
        "items": checked,
        "errors": errors,
        "mock": mock_used,
    }


def build_summary(user_id: int, project_id: str | None = None) -> dict[str, Any]:
    projects = list_projects(user_id)
    if project_id:
        projects = [p for p in projects if str(p.get("id")) == str(project_id)]
    keyword_rows = list_keywords(user_id, project_id=project_id) if project_id else list_keywords(user_id)
    latest_by_kw: dict[str, dict[str, Any]] = {}
    for kw in keyword_rows:
        kid = str(kw.get("id"))
        latest = latest_result_for_keyword(kid, user_id)
        if latest:
            latest_by_kw[kid] = latest

    ranked = [r for r in latest_by_kw.values() if r.get("rank_absolute") is not None]
    not_found = [r for r in latest_by_kw.values() if r.get("rank_absolute") is None]

    avg_rank = None
    if ranked:
        avg_rank = round(sum(int(r["rank_absolute"]) for r in ranked) / len(ranked), 1)

    improved = sum(1 for r in latest_by_kw.values() if isinstance(r.get("rank_change"), int) and r["rank_change"] > 0)
    declined = sum(1 for r in latest_by_kw.values() if isinstance(r.get("rank_change"), int) and r["rank_change"] < 0)

    return {
        "projects_count": len(projects),
        "keywords_count": len(keyword_rows),
        "tracked_count": len(latest_by_kw),
        "ranked_count": len(ranked),
        "not_found_count": len(not_found),
        "avg_rank": avg_rank,
        "improved_count": improved,
        "declined_count": declined,
        "dataforseo_enabled": dataforseo_client.is_dataforseo_enabled(),
        "mock_mode": not dataforseo_client.is_dataforseo_enabled()
        or dataforseo_client.get_basic_auth() is None,
    }


def keyword_dashboard_rows(user_id: int, project_id: str) -> list[dict[str, Any]]:
    get_project(project_id, user_id)
    rows: list[dict[str, Any]] = []
    for kw in list_keywords(user_id, project_id=project_id):
        kid = str(kw["id"])
        latest = latest_result_for_keyword(kid, user_id)
        previous = previous_result_for_keyword(kid, user_id)
        rows.append(
            {
                "id": kid,
                "keyword": kw.get("keyword"),
                "project_id": project_id,
                "current_rank": latest.get("rank_absolute") if latest else None,
                "rank_change": latest.get("rank_change") if latest else None,
                "best_url": latest.get("url") if latest else None,
                "title": latest.get("title") if latest else None,
                "last_checked": latest.get("checked_at") if latest else kw.get("last_checked_at"),
                "previous_rank": previous.get("rank_absolute") if previous else None,
                "found": bool(latest and latest.get("found")),
                "mock": bool(latest and latest.get("mock")),
            }
        )
    rows.sort(key=lambda x: (x["current_rank"] is None, x["current_rank"] or 9999, str(x.get("keyword") or "")))
    return rows
