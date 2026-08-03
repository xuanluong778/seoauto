"""Per-user API access flags and shared admin LLM key pool."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.rbac import is_admin


def api_access_enabled_for(user: User) -> bool:
    if is_admin(user):
        return True
    return bool(getattr(user, "api_access_enabled", False))


def use_admin_api_pool_for(user: User) -> bool:
    if is_admin(user):
        return True
    return bool(getattr(user, "use_admin_api_pool", False))


def assert_user_may_use_api(user: User) -> None:
    """Block LLM/API features when admin has not granted API access."""
    if api_access_enabled_for(user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin chưa cấp quyền sử dụng API. Vui lòng liên hệ quản trị viên.",
    )


def resolve_llm_config_for_user(db: Session, user_id: int):
    """
    Order: user's own keys → admin pool (env.local + admin user keys) if allowed.
    Returns None when API access is disabled or no keys are available.
    """
    from app.services.llm_content_writer import (
        LlmConfig,
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

    if not api_access_enabled_for(user):
        return None

    cfg = _load_llm_config_from_user_keys(int(user_id))
    if cfg:
        return cfg

    if use_admin_api_pool_for(user):
        return _load_admin_shared_llm_config(db)
    return None


def _load_admin_shared_llm_config(db: Session):
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
