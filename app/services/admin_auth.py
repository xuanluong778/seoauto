"""Admin accounts: skip OTP; email list from ADMIN_EMAIL env only (no hard-coded emails)."""

from __future__ import annotations

import os

from app.models.user import User


def _is_admin_role(user: User) -> bool:
    from app.services.rbac import is_admin_role_name

    return is_admin_role_name(getattr(user, "role", None))


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def admin_emails_from_env() -> frozenset[str]:
    """ADMIN_EMAIL and optional PLATFORM_ADMIN_EMAILS (comma-separated)."""
    parts: list[str] = []
    for key in ("ADMIN_EMAIL", "PLATFORM_ADMIN_EMAILS"):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        for chunk in raw.replace(";", ",").split(","):
            e = chunk.strip().lower()
            if e:
                parts.append(e)
    return frozenset(parts)


# Backward-compatible name: now env-derived only (empty if unset).
PLATFORM_ADMIN_EMAILS = admin_emails_from_env()


def is_platform_admin_email(email: str) -> bool:
    return normalize_email(email) in admin_emails_from_env()


def is_platform_admin(user: User | None) -> bool:
    if user is None:
        return False
    return is_platform_admin_email(str(getattr(user, "email", "") or ""))


def is_configured_admin_email(email: str) -> bool:
    return normalize_email(email) in admin_emails_from_env()


def skips_otp_for_user(user: User | None, email: str) -> bool:
    if user is not None and _is_admin_role(user):
        return True
    return is_configured_admin_email(email)


def ensure_admin_user_fields(user: User) -> None:
    """Ensure admin capabilities without downgrading an existing super_admin."""
    from app.services.rbac import is_admin_role_name

    if not is_admin_role_name(getattr(user, "role", None)):
        user.role = "admin"
    user.status = "active"
    user.api_access_enabled = True
    user.use_admin_api_pool = True


def ensure_super_admin_user_fields(user: User) -> None:
    """Elevate to super_admin with full API pool (idempotent fields)."""
    user.role = "super_admin"
    user.status = "active"
    user.api_access_enabled = True
    user.use_admin_api_pool = True
    user.allow_custom_api_key = True
