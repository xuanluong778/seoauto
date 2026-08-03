"""Lưu refresh token Google (GSC + Analytics) theo user_id — file local, không commit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.secrets_crypto import decrypt_secret, encrypt_secret

_STORE = Path(__file__).resolve().parent.parent.parent / "data" / "google_oauth.json"


def _read_raw() -> dict:
    if not _STORE.exists():
        return {}
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_raw(data: dict) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_google_refresh_token(user_id: int, refresh_token: str) -> None:
    raw = _read_raw()
    raw[str(int(user_id))] = {
        "refresh_token": encrypt_secret(refresh_token),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_raw(raw)


def get_google_refresh_token(user_id: int) -> str | None:
    row = _read_raw().get(str(int(user_id)))
    if not isinstance(row, dict):
        return None
    rt = decrypt_secret(str(row.get("refresh_token") or "")).strip()
    return rt or None


def disconnect_google(user_id: int) -> bool:
    raw = _read_raw()
    key = str(int(user_id))
    if key not in raw:
        return False
    del raw[key]
    _write_raw(raw)
    return True


def has_google_connection(user_id: int) -> bool:
    return bool(get_google_refresh_token(user_id))
