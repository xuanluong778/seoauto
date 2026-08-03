"""SQL-backed per-user API keys (encrypted at rest)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.models.user_api_key import UserApiKey
from app.services.api_key_fingerprint import api_key_fingerprint
from app.services.api_keys_store import MAX_KEYS, PROVIDERS


def _mask(value: str) -> str:
    s = str(value or "")
    if len(s) <= 8:
        return "•" * len(s)
    return s[:6] + "•" * 16 + s[-3:]


def _public(entry: dict[str, Any], *, reveal_key: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": entry["id"],
        "name": entry["name"],
        "provider": entry["provider"],
        "provider_label": PROVIDERS.get(entry["provider"], entry["provider"]),
        "api_key_masked": _mask(entry.get("api_key", "")),
        "daily_limit": entry["daily_limit"],
        "priority": entry["priority"],
        "enabled": entry["enabled"],
        "status": entry["status"],
        "used_today": entry["used_today"],
        "errors_today": entry["errors_today"],
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
        "last_used_at": entry["last_used_at"],
    }
    if reveal_key:
        out["api_key"] = entry.get("api_key", "")
    return out

KEYS_FILE = Path("data/api_keys.json")


def _row_to_entry(row: UserApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "provider": row.provider,
        "api_key": decrypt_secret(row.api_key_encrypted),
        "daily_limit": row.daily_limit,
        "priority": row.priority,
        "enabled": row.enabled,
        "status": row.status,
        "used_today": row.used_today,
        "errors_today": row.errors_today,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "last_used_at": row.last_used_at or "",
    }


def import_legacy_json_keys(db: Session) -> int:
    """One-time import from data/api_keys.json into user_api_keys."""
    if not KEYS_FILE.exists():
        return 0
    try:
        raw = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(raw, list):
        return 0
    imported = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            uid = int(item.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            continue
        kid = str(item.get("id") or uuid.uuid4())
        if db.get(UserApiKey, kid):
            continue
        plain = decrypt_secret(str(item.get("api_key") or ""))
        if not plain:
            continue
        provider = str(item.get("provider") or "openai").strip().lower()
        if provider not in PROVIDERS:
            provider = "openai"
        row = UserApiKey(
            id=kid,
            user_id=uid,
            name=str(item.get("name") or "").strip(),
            provider=provider,
            api_key_encrypted=encrypt_secret(plain),
            key_fingerprint=api_key_fingerprint(plain),
            daily_limit=int(item.get("daily_limit") or 0),
            priority=max(1, min(10, int(item.get("priority") or 1))),
            enabled=bool(item.get("enabled", True)),
            status=str(item.get("status") or "healthy"),
            used_today=int(item.get("used_today") or 0),
            errors_today=int(item.get("errors_today") or 0),
            last_used_at=str(item.get("last_used_at") or ""),
        )
        db.add(row)
        imported += 1
    if imported:
        db.commit()
    return imported


def list_keys_db(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(UserApiKey)
        .filter(UserApiKey.user_id == int(user_id))
        .order_by(UserApiKey.priority.asc(), UserApiKey.created_at.asc())
        .all()
    )
    return [_public(_row_to_entry(r)) for r in rows]


def list_enabled_keys_db(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(UserApiKey)
        .filter(UserApiKey.user_id == int(user_id), UserApiKey.enabled.is_(True))
        .order_by(UserApiKey.priority.asc(), UserApiKey.created_at.asc())
        .all()
    )
    out = [_row_to_entry(r) for r in rows]
    return [x for x in out if str(x.get("api_key") or "").strip()]


def get_stats_db(db: Session, *, user_id: int) -> dict[str, int]:
    rows = db.query(UserApiKey).filter(UserApiKey.user_id == int(user_id)).all()
    total = len(rows)
    active = sum(1 for r in rows if r.enabled)
    used_today = sum(int(r.used_today or 0) for r in rows)
    errors = sum(1 for r in rows if (r.status or "") == "error" or int(r.errors_today or 0) > 0)
    return {
        "total_keys": total,
        "active_keys": active,
        "requests_today": used_today,
        "error_keys": errors,
    }


def create_key_db(db: Session, payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    count = db.query(UserApiKey).filter(UserApiKey.user_id == int(user_id)).count()
    if count >= MAX_KEYS:
        raise ValueError(f"Tối đa {MAX_KEYS} khóa API.")
    name = str(payload.get("name") or "").strip()
    plain = str(payload.get("api_key") or "").strip()
    if not name:
        raise ValueError("name is required")
    if not plain:
        raise ValueError("api_key is required")
    provider = str(payload.get("provider") or "openai").strip().lower()
    if provider not in PROVIDERS:
        provider = "openai"
    try:
        priority = int(payload.get("priority") or 1)
    except (TypeError, ValueError):
        priority = 1
    priority = max(1, min(10, priority))
    try:
        daily_limit = int(payload.get("daily_limit") or 0)
    except (TypeError, ValueError):
        daily_limit = 0
    row = UserApiKey(
        id=str(uuid.uuid4()),
        user_id=int(user_id),
        name=name,
        provider=provider,
        api_key_encrypted=encrypt_secret(plain),
        key_fingerprint=api_key_fingerprint(plain),
        daily_limit=max(0, daily_limit),
        priority=priority,
        enabled=bool(payload.get("enabled", True)),
        status="healthy",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _public(_row_to_entry(row), reveal_key=True)


def update_key_db(db: Session, key_id: str, patch: dict[str, Any], *, user_id: int) -> dict[str, Any] | None:
    row = (
        db.query(UserApiKey)
        .filter(UserApiKey.id == str(key_id), UserApiKey.user_id == int(user_id))
        .first()
    )
    if not row:
        return None
    if patch.get("name") is not None:
        row.name = str(patch["name"]).strip()
    if patch.get("provider") is not None:
        p = str(patch["provider"]).strip().lower()
        if p in PROVIDERS:
            row.provider = p
    if patch.get("api_key") is not None:
        plain = str(patch["api_key"]).strip()
        if plain:
            row.api_key_encrypted = encrypt_secret(plain)
            row.key_fingerprint = api_key_fingerprint(plain)
    if patch.get("daily_limit") is not None:
        row.daily_limit = max(0, int(patch["daily_limit"]))
    if patch.get("priority") is not None:
        row.priority = max(1, min(10, int(patch["priority"])))
    if patch.get("enabled") is not None:
        row.enabled = bool(patch["enabled"])
    if patch.get("status") is not None:
        row.status = str(patch["status"]).strip().lower() or "healthy"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    reveal = bool(patch.get("api_key"))
    return _public(_row_to_entry(row), reveal_key=reveal)


def delete_key_db(db: Session, key_id: str, *, user_id: int) -> bool:
    row = (
        db.query(UserApiKey)
        .filter(UserApiKey.id == str(key_id), UserApiKey.user_id == int(user_id))
        .first()
    )
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def get_key_db(db: Session, key_id: str, *, user_id: int, reveal_key: bool = False) -> dict[str, Any] | None:
    row = (
        db.query(UserApiKey)
        .filter(UserApiKey.id == str(key_id), UserApiKey.user_id == int(user_id))
        .first()
    )
    if not row:
        return None
    return _public(_row_to_entry(row), reveal_key=reveal_key)
