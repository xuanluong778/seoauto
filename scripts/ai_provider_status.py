from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from app.services.ai_provider_prefs import read_prefs
from app.services.api_keys_store import PROVIDERS as STORE_PROVIDERS, list_enabled_keys_for_user
from app.services.llm_content_writer import load_llm_config


def _env_file() -> Path:
    return Path(__file__).resolve().parents[2] / "env.local"


def _read_env_local() -> dict[str, str]:
    env_file = _env_file()
    if not env_file.exists():
        return {}
    raw = dotenv_values(env_file)
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if not k:
            continue
        out[str(k)] = str(v or "")
    return out


def _getenv(name: str, env_local: dict[str, str]) -> str:
    return str((os.getenv(name) or env_local.get(name) or "")).strip()


def _providers_with_stored_keys(*, user_id: int | None = None) -> set[str]:
    if user_id is None:
        return set()
    out: set[str] = set()
    for k in list_enabled_keys_for_user(int(user_id)):
        p = k.get("provider")
        if isinstance(p, str) and p in STORE_PROVIDERS and str(k.get("api_key") or "").strip():
            out.add(p)
    return out


def _vertex_env_configured(env_local: dict[str, str]) -> bool:
    cred = _getenv("GOOGLE_APPLICATION_CREDENTIALS", env_local)
    if cred and Path(cred).expanduser().is_file():
        return True
    return bool(_getenv("VERTEX_AI_PROJECT", env_local) and _getenv("VERTEX_AI_LOCATION", env_local))


def build_provider_snapshot(*, user_id: int) -> dict:
    env_local = _read_env_local()
    stored = _providers_with_stored_keys(user_id=user_id)
    prefs = read_prefs(user_id=user_id)

    def has_openai() -> bool:
        return "openai" in stored

    def has_custom_openai() -> bool:
        return "custom_openai" in stored

    def has_gemini() -> bool:
        return "google_gemini" in stored

    flags = {
        "openai": has_openai(),
        "google_gemini": has_gemini(),
        "vertex_ai": "vertex_ai" in stored,
        "openrouter": "openrouter" in stored,
        "custom_openai": has_custom_openai(),
        "custom_anthropic": "custom_anthropic" in stored,
    }

    configured_ids = {pid for pid, ok in flags.items() if ok}
    fallback_ready = len(configured_ids) >= 2

    llm = load_llm_config(user_id=user_id)
    active: str | None = None
    if llm is not None:
        if llm.provider == "openai":
            active = "openai"
        elif llm.provider == "anthropic":
            active = "custom_anthropic"

    cards_meta = [
        {
            "id": "openai",
            "title": "OpenAI",
            "description": "Use OpenAI only and rotate across OpenAI keys.",
        },
        {
            "id": "google_gemini",
            "title": "Gemini",
            "description": "Use Google Gemini and rotate across Gemini keys.",
        },
        {
            "id": "vertex_ai",
            "title": "Vertex AI",
            "description": "Run models on Google Cloud Vertex AI.",
        },
        {
            "id": "openrouter",
            "title": "OpenRouter",
            "description": "Access 300+ models through OpenRouter.",
        },
        {
            "id": "custom_openai",
            "title": "Custom OpenAI",
            "description": "OpenAI-compatible: Ollama, LiteLLM, vLLM…",
        },
        {
            "id": "custom_anthropic",
            "title": "Custom Anthropic",
            "description": "Claude API / Anthropic-compatible endpoint.",
        },
        {
            "id": "fallback",
            "title": "Fallback",
            "description": "Switch providers automatically on failure or quota.",
        },
    ]

    cards = []
    for m in cards_meta:
        pid = m["id"]
        if pid == "fallback":
            if fallback_ready:
                status = ""
                status_kind = "ok"
            else:
                status = "At least 2 providers with API keys are required"
                status_kind = "warn"
            has_key = fallback_ready
        else:
            has_key = bool(flags.get(pid))
            if has_key:
                status = ""
                status_kind = "ok"
            else:
                status = "No API key"
                status_kind = "missing"

        cards.append(
            {
                **m,
                "has_key": has_key,
                "status": status,
                "status_kind": status_kind,
            }
        )

    return {
        "pipeline_multi_model": bool(prefs.get("pipeline_multi_model")),
        "active_provider_id": active,
        "llm_resolved": bool(llm is not None),
        "cards": cards,
    }
