"""CAU modal snapshot listing (user-scoped). Uses content_auto_update backup JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services import content_backup as _cau_backup_store
from app.services.content_backup import get_backup
from app.services.user_scope import belongs_to_user


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _read_list() -> list[dict[str, Any]]:
    return _read_json_list(Path(_cau_backup_store.BACKUPS_FILE))


def list_modal_snapshots(
    user_id: int,
    *,
    wp_id: int | None = None,
    site_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    items = [b for b in _read_list() if belongs_to_user(b, user_id)]
    if wp_id is not None and int(wp_id) > 0:
        items = [b for b in items if int(b.get("wp_id") or 0) == int(wp_id)]
    if site_id:
        items = [b for b in items if str(b.get("site_id") or "") == str(site_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    out: list[dict[str, Any]] = []
    for b in items[: max(1, min(int(limit or 50), 200))]:
        out.append({
            "id": b.get("id"),
            "user_id": b.get("user_id"),
            "created_at": b.get("created_at"),
            "session_id": b.get("session_id"),
            "site_id": b.get("site_id"),
            "wp_id": b.get("wp_id"),
            "post_type": b.get("post_type"),
            "post_url": b.get("post_url"),
            "old_title": b.get("old_title"),
            "old_status": b.get("old_status"),
            "old_excerpt": (str(b.get("old_excerpt") or ""))[:500],
            "content_preview": (str(b.get("old_content") or ""))[:800],
        })
    return out


def get_modal_snapshot_detail(snapshot_id: str, user_id: int) -> dict[str, Any] | None:
    b = get_backup(snapshot_id, user_id)
    if not b:
        return None
    return {
        "id": b.get("id"),
        "user_id": b.get("user_id"),
        "created_at": b.get("created_at"),
        "session_id": b.get("session_id"),
        "site_id": b.get("site_id"),
        "wp_id": b.get("wp_id"),
        "post_type": b.get("post_type"),
        "post_url": b.get("post_url"),
        "old_title": b.get("old_title"),
        "old_status": b.get("old_status"),
        "old_excerpt": b.get("old_excerpt") or "",
        "old_content": b.get("old_content") or "",
    }


def list_modal_action_history(
    user_id: int,
    *,
    wp_id: int | None = None,
    site_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """History rows for modal ops including patches (user-scoped)."""
    items = [h for h in _read_json_list(Path(_cau_backup_store.HISTORY_FILE)) if belongs_to_user(h, user_id)]
    if wp_id is not None and int(wp_id) > 0:
        items = [h for h in items if int(h.get("wp_id") or 0) == int(wp_id)]
    if site_id:
        items = [h for h in items if str(h.get("site_id") or "") == str(site_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    allow = (
        "id", "user_id", "created_at", "action", "status", "session_id", "backup_id",
        "site_id", "wp_id", "post_url", "title", "mode", "link", "job_id",
        "seo_before_score", "seo_after_score", "seo_delta", "message",
        "patches", "patches_count", "operator", "actor_user_id", "wp_modified_before",
    )
    out = []
    for h in items[: max(1, min(int(limit or 50), 200))]:
        out.append({k: h[k] for k in allow if k in h})
    return out
