"""Social Auto — Facebook Fanpage connections, safety settings, API logs."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.user_scope import belongs_to_user

PAGES_FILE = Path("data/social_auto_facebook_pages.json")
SETTINGS_FILE = Path("data/social_auto_facebook_settings.json")
LOGS_FILE = Path("data/social_auto_facebook_logs.json")
MAX_LOGS_PER_USER = 200

DEFAULT_SETTINGS = {
    "max_posts_per_day": 4,
    "min_hours_between_posts": 3,
    "auto_stop_on_rate_limit": True,
    "auto_stop_on_permission_error": True,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_mock_mode() -> bool:
    if str(os.getenv("SOCIAL_AUTO_FACEBOOK_MOCK", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    app_id = str(os.getenv("FACEBOOK_APP_ID", "")).strip()
    app_secret = str(os.getenv("FACEBOOK_APP_SECRET", "")).strip()
    return not (app_id and app_secret)


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


def _read_settings_map() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_settings_map(data: dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_safety_settings(user_id: int) -> dict[str, Any]:
    raw = _read_settings_map()
    row = raw.get(str(int(user_id)))
    if not isinstance(row, dict):
        row = {}
    out = dict(DEFAULT_SETTINGS)
    out.update({k: row[k] for k in DEFAULT_SETTINGS if k in row})
    out["user_id"] = int(user_id)
    out["is_paused"] = bool(row.get("is_paused"))
    out["pause_reason"] = str(row.get("pause_reason") or "") or None
    out["updated_at"] = row.get("updated_at")
    return out


def save_safety_settings(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    raw = _read_settings_map()
    key = str(int(user_id))
    row = dict(raw.get(key) or {})
    for k in ("max_posts_per_day", "min_hours_between_posts"):
        if k in patch and patch[k] is not None:
            row[k] = max(1, min(int(patch[k]), 10 if k == "max_posts_per_day" else 12))
    for k in ("auto_stop_on_rate_limit", "auto_stop_on_permission_error"):
        if k in patch and patch[k] is not None:
            row[k] = bool(patch[k])
    if patch.get("clear_pause"):
        row["is_paused"] = False
        row["pause_reason"] = None
    row["updated_at"] = _now()
    raw[key] = row
    _write_settings_map(raw)
    return get_safety_settings(user_id)


def pause_user_posting(user_id: int, reason: str) -> None:
    raw = _read_settings_map()
    key = str(int(user_id))
    row = dict(raw.get(key) or {})
    row["is_paused"] = True
    row["pause_reason"] = (reason or "Tạm dừng tự động")[:500]
    row["updated_at"] = _now()
    raw[key] = row
    _write_settings_map(raw)


def save_facebook_oauth_meta(
    user_id: int,
    *,
    status: str,
    granted_permissions: list[str] | None = None,
    message: str | None = None,
) -> None:
    raw = _read_settings_map()
    key = str(int(user_id))
    row = dict(raw.get(key) or {})
    row["fb_oauth_status"] = status[:64]
    row["fb_oauth_granted"] = list(granted_permissions or [])
    row["fb_oauth_message"] = (message or "")[:500] or None
    row["fb_oauth_at"] = _now()
    row["updated_at"] = _now()
    raw[key] = row
    _write_settings_map(raw)


def get_facebook_oauth_meta(user_id: int) -> dict[str, Any]:
    raw = _read_settings_map()
    row = raw.get(str(int(user_id))) or {}
    if not isinstance(row, dict):
        return {}
    return {
        "status": str(row.get("fb_oauth_status") or "").strip() or None,
        "granted_permissions": row.get("fb_oauth_granted") or [],
        "message": row.get("fb_oauth_message"),
        "at": row.get("fb_oauth_at"),
    }


def clear_facebook_oauth_meta(user_id: int) -> None:
    raw = _read_settings_map()
    key = str(int(user_id))
    row = dict(raw.get(key) or {})
    for k in ("fb_oauth_status", "fb_oauth_granted", "fb_oauth_message", "fb_oauth_at"):
        row.pop(k, None)
    row["updated_at"] = _now()
    raw[key] = row
    _write_settings_map(raw)


def list_pages(user_id: int) -> list[dict[str, Any]]:
    items = [p for p in _read_list(PAGES_FILE) if belongs_to_user(p, user_id)]
    out = []
    for p in items:
        row = {k: v for k, v in p.items() if k != "page_access_token"}
        row["has_token"] = bool(p.get("page_access_token"))
        row["is_mock"] = bool(p.get("is_mock"))
        out.append(row)
    out.sort(key=lambda x: str(x.get("connected_at") or ""), reverse=True)
    return out


def _find_page(page_id: str, user_id: int) -> dict[str, Any] | None:
    for p in _read_list(PAGES_FILE):
        if str(p.get("page_id")) == str(page_id) and belongs_to_user(p, user_id):
            return p
    return None


def get_page_token(page_id: str, user_id: int) -> str | None:
    p = _find_page(page_id, user_id)
    if not p:
        return None
    tok = decrypt_secret(str(p.get("page_access_token") or "")).strip()
    return tok or None


def upsert_page(
    *,
    user_id: int,
    page_id: str,
    page_name: str,
    page_access_token: str,
    status: str = "connected",
    is_mock: bool = False,
) -> dict[str, Any]:
    all_p = _read_list(PAGES_FILE)
    entry = None
    for i, p in enumerate(all_p):
        if belongs_to_user(p, user_id) and str(p.get("page_id")) == str(page_id):
            entry = dict(p)
            entry["page_name"] = page_name[:200]
            entry["page_access_token"] = encrypt_secret(page_access_token)
            entry["status"] = status
            entry["is_mock"] = is_mock
            entry["connected_at"] = _now()
            all_p[i] = entry
            break
    if entry is None:
        entry = {
            "id": str(uuid.uuid4()),
            "user_id": int(user_id),
            "page_id": str(page_id),
            "page_name": page_name[:200],
            "page_access_token": encrypt_secret(page_access_token),
            "status": status,
            "is_mock": is_mock,
            "is_active": False,
            "connected_at": _now(),
        }
        all_p.append(entry)
    _write_list(PAGES_FILE, all_p)
    return {k: v for k, v in entry.items() if k != "page_access_token"}


def set_active_page(user_id: int, page_id: str) -> dict[str, Any]:
    all_p = _read_list(PAGES_FILE)
    found = None
    for i, p in enumerate(all_p):
        if not belongs_to_user(p, user_id):
            continue
        active = str(p.get("page_id")) == str(page_id)
        p = dict(p)
        p["is_active"] = active
        all_p[i] = p
        if active:
            found = p
    if not found:
        raise ValueError("Không tìm thấy Fanpage.")
    _write_list(PAGES_FILE, all_p)
    return {k: v for k, v in found.items() if k != "page_access_token"}


def get_active_page(user_id: int) -> dict[str, Any] | None:
    for p in _read_list(PAGES_FILE):
        if belongs_to_user(p, user_id) and p.get("is_active"):
            return {k: v for k, v in p.items() if k != "page_access_token"}
    pages = list_pages(user_id)
    return pages[0] if pages else None


def disconnect_page(user_id: int, page_id: str) -> bool:
    all_p = _read_list(PAGES_FILE)
    new_list = [
        p for p in all_p
        if not (belongs_to_user(p, user_id) and str(p.get("page_id")) == str(page_id))
    ]
    if len(new_list) == len(all_p):
        return False
    _write_list(PAGES_FILE, new_list)
    return True


def append_api_log(
    user_id: int,
    *,
    level: str,
    code: str,
    message: str,
    page_id: str | None = None,
    post_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "level": level[:16],
        "code": code[:64],
        "message": (message or "")[:1000],
        "page_id": page_id,
        "post_id": post_id,
        "meta": meta or {},
        "created_at": _now(),
    }
    all_logs = _read_list(LOGS_FILE)
    user_logs = [x for x in all_logs if belongs_to_user(x, user_id)]
    if len(user_logs) >= MAX_LOGS_PER_USER:
        drop = len(user_logs) - MAX_LOGS_PER_USER + 1
        remove_ids = {x.get("id") for x in sorted(user_logs, key=lambda z: z.get("created_at") or "")[:drop]}
        all_logs = [x for x in all_logs if x.get("id") not in remove_ids]
    all_logs.append(entry)
    _write_list(LOGS_FILE, all_logs)

    settings = get_safety_settings(user_id)
    if code in {"rate_limit", "permission_denied"}:
        if (code == "rate_limit" and settings.get("auto_stop_on_rate_limit")) or (
            code == "permission_denied" and settings.get("auto_stop_on_permission_error")
        ):
            pause_user_posting(user_id, message)
    return entry


def list_api_logs(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    items = [x for x in _read_list(LOGS_FILE) if belongs_to_user(x, user_id)]
    items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return items[: max(1, min(limit, 200))]
