"""Runtime Facebook Login for Business configuration (config_id)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CONFIG_FILE = Path("data/facebook_oauth_app_config.json")
_CONFIG_ID_RE = re.compile(r"^\d{10,20}$")


def _read_file() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_file(data: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_runtime_config_id() -> str:
    return str(_read_file().get("login_config_id") or "").strip()


def _validate_config_id(config_id: str) -> str:
    cid = str(config_id or "").strip()
    if not cid:
        return ""
    if not _CONFIG_ID_RE.match(cid):
        raise ValueError("Configuration ID phải là số (10–20 chữ số).")
    app_id = str(os.getenv("FACEBOOK_APP_ID", "")).strip()
    if app_id and cid == app_id:
        raise ValueError("Configuration ID không được trùng FACEBOOK_APP_ID.")
    return cid


def save_runtime_config_id(config_id: str) -> str:
    cid = _validate_config_id(config_id)
    data = _read_file()
    if cid:
        data["login_config_id"] = cid
    else:
        data.pop("login_config_id", None)
    _write_file(data)
    return cid


def effective_login_config_id() -> str:
    env_id = _validate_config_id(str(os.getenv("FACEBOOK_LOGIN_CONFIG_ID", "")).strip()) if os.getenv("FACEBOOK_LOGIN_CONFIG_ID") else ""
    if env_id:
        return env_id
    try:
        return _validate_config_id(get_runtime_config_id())
    except ValueError:
        return ""
