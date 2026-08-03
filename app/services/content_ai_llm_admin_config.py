"""Admin configuration for Content AI LLM provider selection (JSON store)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "content_ai_llm_providers.json"

USER_PROVIDER_IDS = ("auto", "openai", "gemini", "anthropic", "deepseek", "qwen")


def _provider_defaults() -> dict[str, dict[str, Any]]:
    return {
        "openai": {
            "enabled": True,
            "model": "",
            "credit_multiplier": 1.0,
            "priority": 40,
        },
        "gemini": {
            "enabled": True,
            "model": "",
            "credit_multiplier": 0.95,
            "priority": 35,
        },
        "anthropic": {
            "enabled": True,
            "model": "",
            "credit_multiplier": 1.1,
            "priority": 30,
        },
        "deepseek": {
            "enabled": True,
            "model": "",
            "credit_multiplier": 0.75,
            "priority": 25,
        },
        "qwen": {
            "enabled": True,
            "model": "",
            "credit_multiplier": 0.8,
            "priority": 28,
        },
    }


def default_config() -> dict[str, Any]:
    return {
        "providers": _provider_defaults(),
        "fallback_order": ["openai", "gemini", "anthropic", "deepseek", "qwen"],
        "auto_priority": ["openai", "deepseek", "qwen", "gemini", "anthropic"],
        "long_content_word_threshold": 1500,
        "long_content_priority": ["gemini", "openai", "qwen", "anthropic", "deepseek"],
        "brief_field_priority": ["openai", "deepseek", "qwen", "anthropic", "gemini"],
        "plan_providers": {
            "default": list(USER_PROVIDER_IDS),
        },
    }


def _merge_providers(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    base = _provider_defaults()
    if not isinstance(raw, dict):
        return base
    for pid, row in raw.items():
        if pid not in base or not isinstance(row, dict):
            if pid == "qwen" and isinstance(row, dict):
                merged = {
                    "enabled": bool(row.get("enabled", True)),
                    "model": str(row.get("model") or "").strip(),
                    "credit_multiplier": 1.0,
                    "priority": 28,
                }
                try:
                    merged["credit_multiplier"] = max(0.1, min(5.0, float(row.get("credit_multiplier") or 1.0)))
                except (TypeError, ValueError):
                    pass
                base["qwen"] = merged
            continue
        merged = dict(base[pid])
        for key in ("enabled", "model", "credit_multiplier", "priority"):
            if key in row and row[key] is not None:
                merged[key] = row[key]
        if isinstance(merged.get("enabled"), bool):
            pass
        else:
            merged["enabled"] = bool(merged.get("enabled", True))
        try:
            merged["credit_multiplier"] = max(0.1, min(5.0, float(merged.get("credit_multiplier") or 1.0)))
        except (TypeError, ValueError):
            merged["credit_multiplier"] = 1.0
        try:
            merged["priority"] = int(merged.get("priority") or 0)
        except (TypeError, ValueError):
            merged["priority"] = 0
        merged["model"] = str(merged.get("model") or "").strip()
        base[pid] = merged
    return base


def read_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return default_config()
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    defaults = default_config()
    out = dict(defaults)
    out["providers"] = _merge_providers(raw.get("providers"))
    for key in (
        "fallback_order",
        "auto_priority",
        "long_content_priority",
        "brief_field_priority",
    ):
        val = raw.get(key)
        if isinstance(val, list) and val:
            cleaned = [str(x).strip().lower() for x in val if str(x).strip()]
            out[key] = [x for x in cleaned if x in USER_PROVIDER_IDS and x != "auto"] or defaults[key]
    try:
        out["long_content_word_threshold"] = max(
            400, int(raw.get("long_content_word_threshold") or defaults["long_content_word_threshold"])
        )
    except (TypeError, ValueError):
        out["long_content_word_threshold"] = defaults["long_content_word_threshold"]
    plan_raw = raw.get("plan_providers")
    if isinstance(plan_raw, dict):
        plans: dict[str, list[str]] = {}
        for plan, items in plan_raw.items():
            if not isinstance(items, list):
                continue
            cleaned = []
            for item in items:
                pid = str(item or "").strip().lower()
                if pid in USER_PROVIDER_IDS and pid not in cleaned:
                    cleaned.append(pid)
            if cleaned:
                plans[str(plan).strip().lower()] = cleaned
        if plans:
            out["plan_providers"] = plans
    return out


def write_config(patch: dict[str, Any]) -> dict[str, Any]:
    cur = read_config()
    if isinstance(patch.get("providers"), dict):
        cur["providers"] = _merge_providers({**cur.get("providers", {}), **patch["providers"]})
    for key in (
        "fallback_order",
        "auto_priority",
        "long_content_priority",
        "brief_field_priority",
        "long_content_word_threshold",
        "plan_providers",
    ):
        if key in patch and patch[key] is not None:
            cur[key] = patch[key]
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return read_config()
