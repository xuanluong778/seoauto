"""Content AI LLM provider routing: auto pick, fallback, user-facing catalog."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from dotenv import dotenv_values

from app.services.content_ai_llm_admin_config import USER_PROVIDER_IDS, read_config
from app.services.llm_content_writer import (
    LlmConfig,
    OPENROUTER_BASE_URL,
    _getenv,
    _llm_temperature,
    _openai_request_headers,
    openai_compatible_chat_url,
)

_LOG = logging.getLogger(__name__)

_BRIEF_FIELDS = frozenset(
    {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
    }
)

_PROVIDER_LABELS: dict[str, dict[str, str]] = {
    "auto": {
        "label": "Tự động – Khuyên dùng",
        "description": "Hệ thống chọn AI phù hợp theo loại bài, số từ, tốc độ và chi phí.",
    },
    "openai": {
        "label": "OpenAI GPT",
        "description": "Chất lượng toàn diện, phù hợp đa dạng loại bài SEO.",
    },
    "gemini": {
        "label": "Google Gemini",
        "description": "Phù hợp bài dài, xử lý ngữ cảnh rộng.",
    },
    "anthropic": {
        "label": "Claude",
        "description": "Văn phong tự nhiên, mạch lạc.",
    },
    "deepseek": {
        "label": "DeepSeek",
        "description": "Tiết kiệm chi phí, tốc độ ổn định.",
    },
    "qwen": {
        "label": "Qwen",
        "description": "Mô hình đa ngôn ngữ, phù hợp nội dung tiếng Việt.",
    },
}

_ENV_MODEL_KEYS = {
    "openai": "CONTENT_AI_MODEL_OPENAI",
    "gemini": "CONTENT_AI_MODEL_GEMINI",
    "anthropic": "CONTENT_AI_MODEL_ANTHROPIC",
    "deepseek": "CONTENT_AI_MODEL_DEEPSEEK",
    "qwen": "CONTENT_AI_MODEL_QWEN",
}

_OPENROUTER_MODEL_DEFAULTS = {
    "openai": "openai/gpt-4o-mini",
    "gemini": "google/gemini-2.5-flash",
    "anthropic": "anthropic/claude-sonnet-4",
    "deepseek": "deepseek/deepseek-chat",
    "qwen": "qwen/qwen-2.5-72b-instruct",
}

_DIRECT_OPENAI_DEFAULTS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-20250514",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
}


def _read_env_local() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    if not env_file.exists():
        return {}
    raw = dotenv_values(env_file)
    return {str(k): str(v or "") for k, v in (raw or {}).items() if k}


def normalize_ai_provider(value: str | None) -> str:
    pid = str(value or "auto").strip().lower()
    if pid in USER_PROVIDER_IDS:
        return pid
    aliases = {
        "gpt": "openai",
        "claude": "anthropic",
        "google": "gemini",
        "google_gemini": "gemini",
    }
    return aliases.get(pid, "auto")


def _admin_provider_row(provider_id: str) -> dict[str, Any]:
    cfg = read_config()
    providers = cfg.get("providers") or {}
    row = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(row, dict):
        return {"enabled": True, "model": "", "credit_multiplier": 1.0, "priority": 0}
    return row


def provider_credit_multiplier(provider_id: str) -> float:
    if provider_id == "auto":
        return 1.0
    try:
        return max(0.1, min(5.0, float(_admin_provider_row(provider_id).get("credit_multiplier") or 1.0)))
    except (TypeError, ValueError):
        return 1.0


def _provider_enabled(provider_id: str) -> bool:
    if provider_id == "auto":
        return True
    return bool(_admin_provider_row(provider_id).get("enabled", True))


def _env_keys(env_local: dict[str, str]) -> dict[str, str]:
    return {
        "openai": _getenv("OPENAI_API_KEY", env_local),
        "anthropic": _getenv("ANTHROPIC_API_KEY", env_local),
        "openrouter": _getenv("OPENROUTER_API_KEY", env_local),
        "gemini": _getenv("GOOGLE_GEMINI_API_KEY", env_local) or _getenv("GEMINI_API_KEY", env_local),
        "deepseek": _getenv("DEEPSEEK_API_KEY", env_local),
        "qwen": _getenv("QWEN_API_KEY", env_local) or _getenv("DASHSCOPE_API_KEY", env_local),
    }


def _stored_keys_for_admin() -> dict[str, str]:
    try:
        from app.db import SessionLocal
        from app.models.user import User
        from app.services.api_keys_store import list_enabled_keys_for_user
        from sqlalchemy import func

        db = SessionLocal()
        try:
            admin = (
                db.query(User)
                .filter(func.lower(User.role) == "admin")
                .order_by(User.id.asc())
                .first()
            )
            if not admin:
                return {}
            out: dict[str, str] = {}
            mapping = {
                "openai": "openai",
                "custom_openai": "openai",
                "openrouter": "openrouter",
                "google_gemini": "gemini",
                "custom_anthropic": "anthropic",
            }
            for row in list_enabled_keys_for_user(int(admin.id)):
                pid = str(row.get("provider") or "")
                key = str(row.get("api_key") or "").strip()
                if not key:
                    continue
                logical = mapping.get(pid)
                if logical and logical not in out:
                    out[logical] = key
            return out
        finally:
            db.close()
    except Exception:
        return {}


def provider_is_available(provider_id: str) -> bool:
    if provider_id == "auto":
        return any(provider_is_available(p) for p in USER_PROVIDER_IDS if p != "auto")
    if not _provider_enabled(provider_id):
        return False
    env_local = _read_env_local()
    keys = _env_keys(env_local)
    stored = _stored_keys_for_admin()
    if provider_id == "openai":
        return bool(keys["openai"] or keys["openrouter"] or stored.get("openai") or stored.get("openrouter"))
    if provider_id == "anthropic":
        return bool(keys["anthropic"] or keys["openrouter"] or stored.get("anthropic") or stored.get("openrouter"))
    if provider_id == "gemini":
        return bool(keys["gemini"] or keys["openrouter"] or stored.get("gemini") or stored.get("openrouter"))
    if provider_id == "deepseek":
        return bool(keys["deepseek"] or keys["openrouter"] or stored.get("openrouter"))
    if provider_id == "qwen":
        return bool(keys["qwen"] or keys["openrouter"] or stored.get("openrouter"))
    return False


def _resolve_model(provider_id: str, env_local: dict[str, str]) -> str:
    admin_model = str(_admin_provider_row(provider_id).get("model") or "").strip()
    if admin_model:
        return admin_model
    env_key = _ENV_MODEL_KEYS.get(provider_id)
    if env_key:
        m = _getenv(env_key, env_local)
        if m:
            return m
    return _OPENROUTER_MODEL_DEFAULTS.get(provider_id) or _DIRECT_OPENAI_DEFAULTS.get(provider_id) or "gpt-4o-mini"


def build_llm_config_for_provider(provider_id: str) -> LlmConfig | None:
    """Resolve runtime LlmConfig for a user-facing provider id (not auto)."""
    pid = normalize_ai_provider(provider_id)
    if pid == "auto":
        pid = "openai"
    if not provider_is_available(pid):
        return None

    env_local = _read_env_local()
    keys = _env_keys(env_local)
    stored = _stored_keys_for_admin()
    model = _resolve_model(pid, env_local)
    temperature = _llm_temperature(env_local)

    if pid == "openai":
        api_key = keys["openai"] or stored.get("openai") or keys["openrouter"] or stored.get("openrouter")
        if not api_key:
            return None
        use_or = bool((not keys["openai"] and not stored.get("openai")) and (keys["openrouter"] or stored.get("openrouter")))
        if use_or:
            return LlmConfig(
                provider="openai",
                api_key=keys["openrouter"] or stored.get("openrouter") or api_key,
                model=model if "/" in model else _OPENROUTER_MODEL_DEFAULTS["openai"],
                temperature=temperature,
                api_base_url=OPENROUTER_BASE_URL,
                logical_provider="openai",
            )
        return LlmConfig(
            provider="openai",
            api_key=api_key,
            model=model if "/" not in model else _DIRECT_OPENAI_DEFAULTS["openai"],
            temperature=temperature,
            api_base_url=_getenv("OPENAI_BASE_URL", env_local) or None,
            logical_provider="openai",
        )

    if pid == "anthropic":
        api_key = keys["anthropic"] or stored.get("anthropic") or keys["openrouter"] or stored.get("openrouter")
        if not api_key:
            return None
        use_or = bool((not keys["anthropic"] and not stored.get("anthropic")) and (keys["openrouter"] or stored.get("openrouter")))
        if use_or:
            return LlmConfig(
                provider="openai",
                api_key=keys["openrouter"] or stored.get("openrouter") or api_key,
                model=model if "/" in model else _OPENROUTER_MODEL_DEFAULTS["anthropic"],
                temperature=temperature,
                api_base_url=OPENROUTER_BASE_URL,
                logical_provider="anthropic",
            )
        return LlmConfig(
            provider="anthropic",
            api_key=api_key,
            model=model if "/" not in model else _DIRECT_OPENAI_DEFAULTS["anthropic"],
            temperature=temperature,
            api_base_url=None,
            logical_provider="anthropic",
        )

    if pid == "gemini":
        gemini_key = keys["gemini"] or stored.get("gemini")
        or_key = keys["openrouter"] or stored.get("openrouter")
        if gemini_key:
            return LlmConfig(
                provider="gemini",
                api_key=gemini_key,
                model=model if "/" not in model else _DIRECT_OPENAI_DEFAULTS["gemini"],
                temperature=temperature,
                api_base_url=None,
                logical_provider="gemini",
            )
        if or_key:
            return LlmConfig(
                provider="openai",
                api_key=or_key,
                model=model if "/" in model else _OPENROUTER_MODEL_DEFAULTS["gemini"],
                temperature=temperature,
                api_base_url=OPENROUTER_BASE_URL,
                logical_provider="gemini",
            )
        return None

    if pid == "deepseek":
        ds_key = keys["deepseek"]
        or_key = keys["openrouter"] or stored.get("openrouter")
        if ds_key:
            base = _getenv("DEEPSEEK_BASE_URL", env_local) or "https://api.deepseek.com"
            return LlmConfig(
                provider="openai",
                api_key=ds_key,
                model=model if "/" not in model else _DIRECT_OPENAI_DEFAULTS["deepseek"],
                temperature=temperature,
                api_base_url=base.rstrip("/"),
                logical_provider="deepseek",
            )
        if or_key:
            return LlmConfig(
                provider="openai",
                api_key=or_key,
                model=model if "/" in model else _OPENROUTER_MODEL_DEFAULTS["deepseek"],
                temperature=temperature,
                api_base_url=OPENROUTER_BASE_URL,
                logical_provider="deepseek",
            )
        return None

    if pid == "qwen":
        qwen_key = keys["qwen"]
        or_key = keys["openrouter"] or stored.get("openrouter")
        if qwen_key:
            base = _getenv("QWEN_BASE_URL", env_local) or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            return LlmConfig(
                provider="openai",
                api_key=qwen_key,
                model=model if "/" not in model else _DIRECT_OPENAI_DEFAULTS["qwen"],
                temperature=temperature,
                api_base_url=base.rstrip("/"),
                logical_provider="qwen",
            )
        if or_key:
            return LlmConfig(
                provider="openai",
                api_key=or_key,
                model=model if "/" in model else _OPENROUTER_MODEL_DEFAULTS["qwen"],
                temperature=temperature,
                api_base_url=OPENROUTER_BASE_URL,
                logical_provider="qwen",
            )
        return None

    return None


def openai_direct_available() -> bool:
    """True when OpenAI API key is configured (not OpenRouter-only)."""
    env_local = _read_env_local()
    keys = _env_keys(env_local)
    stored = _stored_keys_for_admin()
    return bool(keys["openai"] or stored.get("openai"))


def resolve_suggest_brief_chain() -> list[str]:
    """Gợi ý brief: chỉ OpenAI direct, không fallback OpenRouter."""
    if openai_direct_available():
        return ["openai"]
    chain = resolve_provider_chain(ai_provider="openai", field="title", target_word_count=None)
    direct: list[str] = []
    for pid in chain:
        if pid != "openai":
            continue
        cfg = build_llm_config_for_provider(pid)
        if cfg is None:
            continue
        base = str(cfg.api_base_url or "").lower()
        if base and "openrouter" in base:
            continue
        direct.append(pid)
    return direct


def pick_auto_provider(*, field: str, target_word_count: int | None = None) -> str:
    cfg = read_config()
    f = str(field or "").strip().lower()
    wc = int(target_word_count or 1000)

    if f in _BRIEF_FIELDS:
        order = list(cfg.get("brief_field_priority") or [])
    elif f in {"content", "outline_content"} and wc >= int(cfg.get("long_content_word_threshold") or 1500):
        order = list(cfg.get("long_content_priority") or [])
    else:
        order = list(cfg.get("auto_priority") or [])

    for pid in order:
        if provider_is_available(pid):
            return pid
    for pid in USER_PROVIDER_IDS:
        if pid != "auto" and provider_is_available(pid):
            return pid
    return "openai"


def resolve_provider_chain(
    *,
    ai_provider: str | None,
    field: str,
    target_word_count: int | None = None,
) -> list[str]:
    requested = normalize_ai_provider(ai_provider)
    cfg = read_config()
    if requested == "auto":
        primary = pick_auto_provider(field=field, target_word_count=target_word_count)
    else:
        primary = requested

    fallback = [primary]
    for pid in cfg.get("fallback_order") or []:
        p = str(pid).strip().lower()
        if p and p not in fallback and p != "auto":
            fallback.append(p)
    return [p for p in fallback if provider_is_available(p)]


def providers_allowed_for_plan(plan_slug: str | None) -> set[str]:
    cfg = read_config()
    plans = cfg.get("plan_providers") or {}
    slug = str(plan_slug or "default").strip().lower()
    if isinstance(plans, dict):
        for key in (slug, "default"):
            items = plans.get(key)
            if isinstance(items, list) and items:
                return {normalize_ai_provider(x) for x in items}
    return set(USER_PROVIDER_IDS)


def coerce_user_ai_provider(value: str | None, *, plan_slug: str | None = None) -> str:
    """Normalize user choice; disabled/unavailable/not-in-plan providers become auto."""
    pid = normalize_ai_provider(value)
    allowed = providers_allowed_for_plan(plan_slug)
    if pid not in allowed:
        return "auto"
    if pid != "auto" and (not _provider_enabled(pid) or not provider_is_available(pid)):
        return "auto"
    return pid


def list_user_provider_choices(*, plan_slug: str | None = None) -> list[dict[str, Any]]:
    allowed = providers_allowed_for_plan(plan_slug)
    out: list[dict[str, Any]] = []
    for pid in USER_PROVIDER_IDS:
        if pid not in allowed:
            continue
        meta = _PROVIDER_LABELS[pid]
        if pid == "auto":
            selectable = provider_is_available("auto")
        else:
            selectable = _provider_enabled(pid) and provider_is_available(pid)
        out.append(
            {
                "id": pid,
                "label": meta["label"],
                "description": meta["description"],
                "selectable": selectable,
            }
        )
    if not any(c["id"] == "auto" for c in out):
        out.insert(
            0,
            {
                "id": "auto",
                "label": _PROVIDER_LABELS["auto"]["label"],
                "description": _PROVIDER_LABELS["auto"]["description"],
                "selectable": True,
            },
        )
    return out


def gate_llm_config_for_request(
    *,
    ai_provider: str | None,
    field: str,
    target_word_count: int | None = None,
) -> LlmConfig | None:
    """LlmConfig for cost gate — matches first provider in the user's routing chain."""
    requested = normalize_ai_provider(ai_provider)
    chain = resolve_provider_chain(
        ai_provider=requested,
        field=field,
        target_word_count=target_word_count,
    )
    for pid in chain:
        cfg = build_llm_config_for_provider(pid)
        if cfg is not None:
            return cfg
    return None


@contextmanager
def _cost_gate_overlay_for_cfg(cfg: LlmConfig) -> Iterator[None]:
    from app.services.cost_control.context import ActiveCostGate, get_active_cost_gate, reset_active_cost_gate, set_active_cost_gate
    from app.services.cost_control.module_gates import llm_provider_for_config

    cur = get_active_cost_gate()
    if cur is None:
        yield
        return
    need = llm_provider_for_config(cfg)
    if cur.provider == need:
        yield
        return
    overlay = ActiveCostGate(user_id=cur.user_id, provider=need, action=cur.action)
    token = set_active_cost_gate(overlay)
    try:
        yield
    finally:
        reset_active_cost_gate(token)


def fallback_notice_text(*, requested: str, used: str) -> str:
    req = normalize_ai_provider(requested)
    if req == used or req == "auto":
        return ""
    label = _PROVIDER_LABELS.get(used, {}).get("label") or used
    return f"AI {label} tạm thay thế do provider trước gặp sự cố."


@dataclass
class ContentAiLlmRouteResult:
    cfg: LlmConfig
    provider_requested: str
    provider_used: str
    fallback_applied: bool = False
    fallback_notice: str = ""


def resolve_llm_route(
    *,
    ai_provider: str | None,
    field: str,
    target_word_count: int | None = None,
    use_system_llm: bool = True,
    user_id: int | None = None,
) -> ContentAiLlmRouteResult | None:
    del use_system_llm, user_id
    requested = normalize_ai_provider(ai_provider)
    chain = resolve_provider_chain(
        ai_provider=requested,
        field=field,
        target_word_count=target_word_count,
    )
    if not chain:
        return None

    primary = chain[0]
    cfg = build_llm_config_for_provider(primary)
    if cfg is None:
        return None
    return ContentAiLlmRouteResult(
        cfg=cfg,
        provider_requested=requested,
        provider_used=primary,
        fallback_applied=False,
        fallback_notice="",
    )


def call_with_provider_fallback(
    *,
    ai_provider: str | None,
    field: str,
    target_word_count: int | None,
    fn: Callable[[LlmConfig], str],
    chain_override: list[str] | None = None,
    allow_fallback: bool = True,
) -> tuple[str, ContentAiLlmRouteResult | None]:
    """Run LLM call; on failure try fallback providers without double-charging (caller charges once)."""
    requested = normalize_ai_provider(ai_provider)
    if chain_override is not None:
        chain = [str(p).strip().lower() for p in chain_override if str(p).strip()]
    else:
        chain = resolve_provider_chain(
            ai_provider=requested,
            field=field,
            target_word_count=target_word_count,
        )
    if not chain:
        raise RuntimeError("llm_not_configured")

    last_exc: Exception | None = None
    providers = chain if allow_fallback else chain[:1]
    for idx, pid in enumerate(providers):
        cfg = build_llm_config_for_provider(pid)
        if cfg is None:
            continue
        try:
            with _cost_gate_overlay_for_cfg(cfg):
                out = fn(cfg)
            if not str(out or "").strip():
                raise RuntimeError("llm_empty_output")
            route = ContentAiLlmRouteResult(
                cfg=cfg,
                provider_requested=requested,
                provider_used=pid,
                fallback_applied=idx > 0,
                fallback_notice=fallback_notice_text(requested=requested if idx > 0 else pid, used=pid)
                if idx > 0
                else "",
            )
            if idx > 0:
                _LOG.warning(
                    "content_ai provider fallback requested=%s used=%s field=%s",
                    requested,
                    pid,
                    field,
                )
            return out, route
        except Exception as exc:
            last_exc = exc
            _LOG.warning(
                "content_ai provider failed provider=%s field=%s err=%s",
                pid,
                field,
                str(exc)[:200],
            )
            continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("llm_not_configured")


def admin_public_config() -> dict[str, Any]:
    cfg = read_config()
    providers_out: dict[str, Any] = {}
    for pid in USER_PROVIDER_IDS:
        if pid == "auto":
            continue
        row = dict(_admin_provider_row(pid))
        row["available"] = provider_is_available(pid)
        providers_out[pid] = row
    return {
        "providers": providers_out,
        "fallback_order": cfg.get("fallback_order") or [],
        "auto_priority": cfg.get("auto_priority") or [],
        "long_content_priority": cfg.get("long_content_priority") or [],
        "brief_field_priority": cfg.get("brief_field_priority") or [],
        "long_content_word_threshold": cfg.get("long_content_word_threshold"),
        "plan_providers": cfg.get("plan_providers") or {},
    }
