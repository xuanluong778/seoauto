from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFS_FILE = Path("data/ai_provider_prefs.json")


def _defaults() -> dict[str, Any]:
    return {"pipeline_multi_model": False}


def _read_raw() -> dict[str, Any]:
    if not PREFS_FILE.exists():
        return {}
    try:
        raw = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_raw(data: dict[str, Any]) -> None:
    PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_prefs(*, user_id: int) -> dict[str, Any]:
    raw = _read_raw()
    users = raw.get("users")
    if isinstance(users, dict):
        row = users.get(str(int(user_id)))
        if isinstance(row, dict):
            out = _defaults()
            if isinstance(row.get("pipeline_multi_model"), bool):
                out["pipeline_multi_model"] = row["pipeline_multi_model"]
            return out
    return _defaults()


def write_prefs(prefs: dict[str, Any], *, user_id: int) -> None:
    raw = _read_raw()
    users = raw.get("users")
    if not isinstance(users, dict):
        users = {}
    merged = _defaults()
    merged.update(prefs)
    users[str(int(user_id))] = merged
    raw["users"] = users
    _write_raw(raw)
