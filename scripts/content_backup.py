"""Backup snapshots before Content Auto Update publish."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.services.user_scope import belongs_to_user

BACKUPS_FILE = Path("data/content_auto_update_backups.json")
SESSIONS_FILE = Path("data/content_auto_update_sessions.json")
HISTORY_FILE = Path("data/content_auto_update_history.json")
MAX_BACKUPS_PER_USER = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _write_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def save_session(user_id: int, session: dict[str, Any]) -> dict[str, Any]:
    all_s = _read_list(SESSIONS_FILE)
    session = dict(session)
    session["user_id"] = int(user_id)
    session["updated_at"] = _now()
    if not session.get("id"):
        session["id"] = str(uuid.uuid4())
        session["created_at"] = _now()
    replaced = False
    for i, row in enumerate(all_s):
        if belongs_to_user(row, user_id) and str(row.get("id")) == str(session["id"]):
            all_s[i] = session
            replaced = True
            break
    if not replaced:
        all_s.append(session)
    _write_list(SESSIONS_FILE, all_s)
    return session


def get_session(session_id: str, user_id: int) -> dict[str, Any] | None:
    for row in _read_list(SESSIONS_FILE):
        if str(row.get("id")) == str(session_id) and belongs_to_user(row, user_id):
            return row
    return None


def create_backup(
    *,
    user_id: int,
    session_id: str,
    site_id: str,
    wp_id: int,
    post_type: str,
    post_url: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """snapshot: old_title, old_content, old_excerpt, old_status"""
    required = ("old_title", "old_content", "old_excerpt", "old_status")
    for k in required:
        if k not in snapshot:
            raise HTTPException(status_code=400, detail=f"Thiếu {k} trong backup.")

    all_b = _read_list(BACKUPS_FILE)
    user_count = sum(1 for b in all_b if belongs_to_user(b, user_id))
    if user_count >= MAX_BACKUPS_PER_USER:
        oldest = sorted(
            [b for b in all_b if belongs_to_user(b, user_id)],
            key=lambda x: str(x.get("created_at") or ""),
        )[:1]
        if oldest:
            drop_id = oldest[0].get("id")
            all_b = [b for b in all_b if b.get("id") != drop_id]

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "session_id": str(session_id),
        "site_id": str(site_id),
        "wp_id": int(wp_id),
        "post_type": str(post_type),
        "post_url": str(post_url),
        "old_title": str(snapshot.get("old_title") or ""),
        "old_content": str(snapshot.get("old_content") or ""),
        "old_excerpt": str(snapshot.get("old_excerpt") or ""),
        "old_status": str(snapshot.get("old_status") or "draft"),
        "created_at": _now(),
    }
    all_b.append(entry)
    _write_list(BACKUPS_FILE, all_b)

    sess = get_session(session_id, user_id)
    if sess:
        sess = dict(sess)
        sess["backup_id"] = entry["id"]
        save_session(user_id, sess)
    return entry


def get_backup(backup_id: str, user_id: int) -> dict[str, Any] | None:
    for b in _read_list(BACKUPS_FILE):
        if str(b.get("id")) == str(backup_id) and belongs_to_user(b, user_id):
            return b
    return None


def append_history(user_id: int, record: dict[str, Any]) -> dict[str, Any]:
    all_h = _read_list(HISTORY_FILE)
    entry = dict(record)
    entry["id"] = str(uuid.uuid4())
    entry["user_id"] = int(user_id)
    entry["created_at"] = _now()
    all_h.append(entry)
    _write_list(HISTORY_FILE, all_h)
    return entry


def list_history(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    items = [h for h in _read_list(HISTORY_FILE) if belongs_to_user(h, user_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return [_public_history_row(h) for h in items[: max(1, min(limit, 200))]]


def _public_history_row(row: dict[str, Any]) -> dict[str, Any]:
    """Không trả field nhạy cảm."""
    allow = (
        "id", "user_id", "created_at", "action", "status", "session_id", "backup_id",
        "site_id", "wp_id", "post_url", "title", "mode", "link", "job_id",
        "seo_before_score", "seo_after_score", "seo_delta", "message",
    )
    return {k: row[k] for k in allow if k in row}
