"""Per-user system preferences (theme, language, processing)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SETTINGS_FILE = Path("data/user_system_settings.json")


def _defaults() -> dict[str, Any]:
    return {
        "theme": "dark",
        "language": "en",
        "launch_on_startup": False,
        "batch_size": 5,
        "max_retries": 3,
        "stuck_timeout_minutes": 30,
    }


def _read_raw() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_raw(data: dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def normalize_settings(patch: dict[str, Any] | None) -> dict[str, Any]:
    base = _defaults()
    if not patch:
        return base
    theme = str(patch.get("theme") or base["theme"]).strip().lower()
    if theme not in ("light", "dark", "system"):
        theme = base["theme"]
    lang = str(patch.get("language") or base["language"]).strip().lower()
    if lang not in ("vi", "en"):
        lang = base["language"]
    return {
        "theme": theme,
        "language": lang,
        "launch_on_startup": bool(patch.get("launch_on_startup", base["launch_on_startup"])),
        "batch_size": _clamp_int(patch.get("batch_size"), 1, 50, base["batch_size"]),
        "max_retries": _clamp_int(patch.get("max_retries"), 0, 20, base["max_retries"]),
        "stuck_timeout_minutes": _clamp_int(
            patch.get("stuck_timeout_minutes"), 5, 240, base["stuck_timeout_minutes"]
        ),
    }


def read_settings(*, user_id: int) -> dict[str, Any]:
    raw = _read_raw()
    users = raw.get("users")
    if isinstance(users, dict):
        row = users.get(str(int(user_id)))
        if isinstance(row, dict):
            return normalize_settings(row)
    return _defaults()


def write_settings(patch: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    merged = normalize_settings({**read_settings(user_id=user_id), **(patch or {})})
    raw = _read_raw()
    users = raw.get("users")
    if not isinstance(users, dict):
        users = {}
    users[str(int(user_id))] = merged
    raw["users"] = users
    _write_raw(raw)
    return merged


def processing_env_overrides(*, user_id: int) -> dict[str, int]:
    """Values for bulk/worker tuning (optional consumers)."""
    s = read_settings(user_id=user_id)
    return {
        "batch_size": int(s["batch_size"]),
        "max_retries": int(s["max_retries"]),
        "stuck_timeout_minutes": int(s["stuck_timeout_minutes"]),
    }
