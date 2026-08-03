"""Admin accounts: skip OTP; email list from ADMIN_EMAIL env."""

from __future__ import annotations

import os

from app.models.user import User

# Chỉ các email này thấy tab / trang Administrator trong UI (legacy allowlist).
# Quyền SaaS/credit dựa trên role admin|super_admin qua rbac.is_admin — không hard-code email ở nhiều chỗ.
PLATFORM_ADMIN_EMAILS = frozenset(
    {
        "xuanluong778@gmail.com",
        "xuanluongmarketing@gmail.com",
        "thegioimarketingdigi@gmail.com",
    }
)


def _is_admin_role(user: User) -> bool:
    from app.services.rbac import is_admin_role_name

    return is_admin_role_name(getattr(user, "role", None))


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def is_platform_admin_email(email: str) -> bool:
    return normalize_email(email) in PLATFORM_ADMIN_EMAILS


def is_platform_admin(user: User | None) -> bool:
    if user is None:
        return False
    return is_platform_admin_email(str(getattr(user, "email", "") or ""))


def admin_emails_from_env() -> frozenset[str]:
    raw = (os.getenv("ADMIN_EMAIL") or "").strip()
    if not raw:
        return frozenset()
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        e = chunk.strip().lower()
        if e:
            parts.append(e)
    return frozenset(parts)


def is_configured_admin_email(email: str) -> bool:
    return email.strip().lower() in admin_emails_from_env()


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
