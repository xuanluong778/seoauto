"""Rank Tracking — JSON file store (per-user projects, keywords, results)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.services.user_scope import belongs_to_user

PROJECTS_FILE = Path("data/rank_tracking_projects.json")
KEYWORDS_FILE = Path("data/rank_tracking_keywords.json")
RESULTS_FILE = Path("data/rank_tracking_results.json")

MAX_PROJECTS = 50
MAX_KEYWORDS_PER_PROJECT = 500
MAX_RESULTS = 50000

DEVICES = frozenset({"desktop", "mobile", "tablet"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _write_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_project(project_id: str, user_id: int) -> dict[str, Any] | None:
    for row in _read_list(PROJECTS_FILE):
        if str(row.get("id")) == str(project_id) and belongs_to_user(row, user_id):
            return row
    return None


def _find_keyword(keyword_id: str, user_id: int) -> dict[str, Any] | None:
    for row in _read_list(KEYWORDS_FILE):
        if str(row.get("id")) == str(keyword_id) and belongs_to_user(row, user_id):
            return row
    return None


def list_projects(user_id: int) -> list[dict[str, Any]]:
    items = [p for p in _read_list(PROJECTS_FILE) if belongs_to_user(p, user_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return items


def get_project(project_id: str, user_id: int) -> dict[str, Any]:
    row = _find_project(project_id, user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy project.")
    return row


def create_project(
    *,
    user_id: int,
    name: str,
    domain: str,
    location_name: str = "Vietnam",
    language_name: str = "Vietnamese",
    device: str = "desktop",
) -> dict[str, Any]:
    all_rows = _read_list(PROJECTS_FILE)
    owned = [p for p in all_rows if belongs_to_user(p, user_id)]
    if len(owned) >= MAX_PROJECTS:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn project rank tracking.")
    dev = device if device in DEVICES else "desktop"
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "name": str(name or domain or "Project").strip()[:200],
        "domain": str(domain or "").strip().lower()[:253],
        "location_name": str(location_name or "Vietnam").strip()[:120],
        "language_name": str(language_name or "Vietnamese").strip()[:120],
        "device": dev,
        "created_at": _now(),
        "updated_at": _now(),
    }
    all_rows.append(entry)
    _write_list(PROJECTS_FILE, all_rows)
    return entry


def list_keywords(user_id: int, *, project_id: str | None = None) -> list[dict[str, Any]]:
    items = [k for k in _read_list(KEYWORDS_FILE) if belongs_to_user(k, user_id)]
    if project_id:
        items = [k for k in items if str(k.get("project_id")) == str(project_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return items


def create_keyword(*, user_id: int, project_id: str, keyword: str) -> dict[str, Any]:
    project = get_project(project_id, user_id)
    kw = str(keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="Keyword không được để trống.")
    if len(kw) > 200:
        raise HTTPException(status_code=400, detail="Keyword quá dài.")
    existing = list_keywords(user_id, project_id=project_id)
    if len(existing) >= MAX_KEYWORDS_PER_PROJECT:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn keyword cho project.")
    low = kw.lower()
    for row in existing:
        if str(row.get("keyword") or "").strip().lower() == low:
            raise HTTPException(status_code=400, detail="Keyword đã tồn tại trong project.")
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "project_id": str(project["id"]),
        "keyword": kw,
        "created_at": _now(),
        "updated_at": _now(),
    }
    all_rows = _read_list(KEYWORDS_FILE)
    all_rows.append(entry)
    _write_list(KEYWORDS_FILE, all_rows)
    return entry


def list_results(
    user_id: int,
    *,
    project_id: str | None = None,
    keyword_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    items = [r for r in _read_list(RESULTS_FILE) if belongs_to_user(r, user_id)]
    if project_id:
        items = [r for r in items if str(r.get("project_id")) == str(project_id)]
    if keyword_id:
        items = [r for r in items if str(r.get("keyword_id")) == str(keyword_id)]
    items.sort(key=lambda x: str(x.get("checked_at") or ""), reverse=True)
    return items[: max(1, min(int(limit or 200), 1000))]


def latest_result_for_keyword(keyword_id: str, user_id: int) -> dict[str, Any] | None:
    rows = list_results(user_id, keyword_id=keyword_id, limit=1)
    return rows[0] if rows else None


def previous_result_for_keyword(keyword_id: str, user_id: int) -> dict[str, Any] | None:
    rows = list_results(user_id, keyword_id=keyword_id, limit=2)
    return rows[1] if len(rows) > 1 else None


def append_result(
    *,
    user_id: int,
    project_id: str,
    keyword_id: str,
    keyword: str,
    domain: str,
    rank_absolute: int | None,
    rank_group: int | None,
    url: str | None,
    title: str | None,
    rank_change: int | None,
    mock: bool = False,
    serp_depth: int = 100,
) -> dict[str, Any]:
    all_rows = _read_list(RESULTS_FILE)
    if len(all_rows) >= MAX_RESULTS:
        all_rows = all_rows[-MAX_RESULTS + 1 :]
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "project_id": str(project_id),
        "keyword_id": str(keyword_id),
        "keyword": str(keyword),
        "domain": str(domain),
        "rank_absolute": rank_absolute,
        "rank_group": rank_group,
        "url": url,
        "title": title,
        "rank_change": rank_change,
        "found": rank_absolute is not None,
        "mock": bool(mock),
        "serp_depth": int(serp_depth),
        "checked_at": _now(),
    }
    all_rows.append(entry)
    _write_list(RESULTS_FILE, all_rows)

    kw_rows = _read_list(KEYWORDS_FILE)
    for i, row in enumerate(kw_rows):
        if str(row.get("id")) == str(keyword_id) and belongs_to_user(row, user_id):
            kw_rows[i] = {**row, "updated_at": _now(), "last_checked_at": entry["checked_at"]}
            break
    _write_list(KEYWORDS_FILE, kw_rows)

    proj_rows = _read_list(PROJECTS_FILE)
    for i, row in enumerate(proj_rows):
        if str(row.get("id")) == str(project_id) and belongs_to_user(row, user_id):
            proj_rows[i] = {**row, "updated_at": _now(), "last_checked_at": entry["checked_at"]}
            break
    _write_list(PROJECTS_FILE, proj_rows)
    return entry
