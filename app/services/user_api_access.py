"""Per-user API access flags, custom-key policy, and shared admin LLM key pool."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.rbac import is_admin
from app.services.seoauto_pricing_catalog import SEOAUTO_PLAN_SLUG_ORDER

SYSTEM_API_NOT_CONFIGURED_MSG = "Hệ thống chưa cấu hình API. Vui lòng liên hệ admin."
CUSTOM_API_FORBIDDEN_MSG = "Chỉ quản trị viên được cấu hình API hệ thống."


def api_access_enabled_for(user: User) -> bool:
    """Legacy BYOK flag — still grants custom-key management when True."""
    if is_admin(user):
        return True
    return bool(getattr(user, "api_access_enabled", False))


def use_admin_api_pool_for(user: User) -> bool:
    if is_admin(user):
        return True
    return bool(getattr(user, "use_admin_api_pool", False))


def _resolve_subscription_plan_slug(db: Session, user: User) -> str | None:
    from app.services import plan_service, subscription_service

    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None or not subscription_service.is_subscription_active(sub):
        return None
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    slug = str(plan.slug if plan else "").strip().lower()
    return slug or None


def resolve_effective_ai_plan_slug(db: Session, user: User) -> str | None:
    """Plan/trial slug — subscription paid ưu tiên hơn trial_3d."""
    if is_admin(user):
        return "admin"
    from app.services.free_usage_service import has_active_free_usage
    from app.services.saas_trial_service import TRIAL_PLAN_SLUG, is_saas_trial_active

    slug = _resolve_subscription_plan_slug(db, user)
    if slug and slug not in {TRIAL_PLAN_SLUG, "free_trial_5d"}:
        return slug
    if has_active_free_usage(db, user.id) and slug is None:
        return "free_usage"
    if is_saas_trial_active(user):
        return TRIAL_PLAN_SLUG
    if slug == TRIAL_PLAN_SLUG:
        return TRIAL_PLAN_SLUG if is_saas_trial_active(user) else None
    if has_active_free_usage(db, user.id):
        return "free_usage"
    return slug


def may_manage_custom_api_keys(db: Session, user: User) -> bool:
    """Chỉ admin/super_admin cấu hình API hệ thống trong Cài đặt."""
    return is_admin(user)


def assert_user_may_manage_api_keys(db: Session, user: User) -> None:
    if may_manage_custom_api_keys(db, user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=CUSTOM_API_FORBIDDEN_MSG,
    )


def assert_user_may_use_api(user: User) -> None:
    """Legacy helper — prefer assert_user_may_manage_api_keys for key CRUD."""
    if api_access_enabled_for(user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin chưa cấp quyền sử dụng API. Vui lòng liên hệ quản trị viên.",
    )


def _user_has_valid_llm_key(user_id: int) -> bool:
    from app.services.api_keys_store import list_enabled_keys_for_user
    from app.services.llm_content_writer import _ANTHROPIC_KEY_PROVIDERS, _OPENAI_KEY_PROVIDERS

    keys = list_enabled_keys_for_user(int(user_id))
    llm_providers = _OPENAI_KEY_PROVIDERS | _ANTHROPIC_KEY_PROVIDERS
    return any(str(k.get("provider") or "") in llm_providers for k in keys)


def load_admin_shared_llm_config(db: Session):
    from app.services.llm_content_writer import _load_llm_config_from_env, _load_llm_config_from_user_keys

    cfg = _load_llm_config_from_env()
    if cfg:
        return cfg

    admin_ids = (
        db.query(User.id)
        .filter(func.lower(User.role) == "admin")
        .order_by(User.id.asc())
        .all()
    )
    for (aid,) in admin_ids:
        cfg = _load_llm_config_from_user_keys(int(aid))
        if cfg:
            return cfg
    return None


def admin_system_llm_available(db: Session) -> bool:
    return load_admin_shared_llm_config(db) is not None


def describe_user_llm_source(db: Session, user: User) -> str:
    """admin | system — mọi user thường dùng pool API hệ thống."""
    if is_admin(user):
        return "admin"
    return "system"


def resolve_llm_config_for_user(db: Session, user_id: int):
    """Admin: own keys/env; mọi user khác: pool API hệ thống (không dùng key riêng)."""
    from app.services.llm_content_writer import (
        _load_llm_config_from_env,
        _load_llm_config_from_user_keys,
    )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return None

    if is_admin(user):
        cfg = _load_llm_config_from_user_keys(int(user_id))
        if cfg:
            return cfg
        return _load_llm_config_from_env()

    return load_admin_shared_llm_config(db)


def describe_llm_config_failure(db: Session, user_id: int) -> str:
    """Human-readable reason when resolve_llm_config_for_user returns None."""
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return "Không tìm thấy tài khoản."

    if is_admin(user):
        return "Khóa OpenAI/Anthropic hệ thống (env.local) chưa được cấu hình trên server."

    return SYSTEM_API_NOT_CONFIGURED_MSG


def get_ai_provider_for_user(db: Session, user: User) -> dict[str, Any]:
    """
    Nguồn LLM cho user — không bao giờ trả API key về client.
    Mọi user thường: use_system_llm=True, pool admin.
    """
    configured = resolve_llm_config_for_user(db, int(user.id)) is not None
    source = describe_user_llm_source(db, user)
    return {
        "source": source,
        "use_system_llm": True,
        "configured": configured,
        "message": "" if configured or is_admin(user) else SYSTEM_API_NOT_CONFIGURED_MSG,
    }


def build_system_ai_snapshot(
    db: Session,
    user: User,
    *,
    unit_cost: int,
    quantity: int = 1,
    denied_message: str | None = None,
    feature_key: str = "content_ai_article",
) -> dict[str, Any]:
    """Backward-compatible wrapper — delegates to entitlement_service.can_use_ai."""
    from app.services.entitlement_service import can_use_ai

    return can_use_ai(
        db,
        user,
        feature_key,
        estimated_credit_cost=unit_cost,
        quantity=quantity,
        denied_message=denied_message,
    )


def assert_system_ai_entitlement(
    db: Session,
    user: User,
    *,
    unit_cost: int,
    quantity: int = 1,
    denied_message: str | None = None,
    feature_key: str = "content_ai_article",
) -> dict[str, Any]:
    from app.services.entitlement_service import ensure_ai_entitlement

    return ensure_ai_entitlement(
        db,
        user,
        feature_key,
        estimated_credit_cost=unit_cost,
        quantity=quantity,
        denied_message=denied_message,
    )


def resolve_ai_llm_gate(
    db: Session,
    user: User,
    *,
    unit_cost: int = 0,
    denied_message: str | None = None,
    feature_key: str = "content_ai_article",
    quantity: int = 1,
) -> dict[str, Any]:
    """Unified LLM gate — delegates to entitlement_service.can_use_ai."""
    from app.services.entitlement_service import can_use_ai

    return can_use_ai(
        db,
        user,
        feature_key,
        estimated_credit_cost=unit_cost,
        quantity=quantity,
        denied_message=denied_message,
    )


def load_llm_config_for_request(db: Session, user: User):
    """LLM config for AI routes — user thường luôn dùng pool admin, không key riêng."""
    from app.services.llm_content_writer import load_llm_config_admin

    cfg = resolve_llm_config_for_user(db, int(user.id))
    if cfg:
        return cfg
    return load_llm_config_admin()


# Backward-compatible alias
_load_admin_shared_llm_config = load_admin_shared_llm_config
