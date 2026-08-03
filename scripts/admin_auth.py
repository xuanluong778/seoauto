"""Admin accounts: skip OTP; email list from ADMIN_EMAIL env."""

from __future__ import annotations

import os

from app.models.user import User

# Chỉ các email này thấy tab / trang Administrator trong UI.
PLATFORM_ADMIN_EMAILS = frozenset(
    {
        "xuanluong778@gmail.com",
        "xuanluongmarketing@gmail.com",
    }
)


def _is_admin_role(user: User) -> bool:
    return str(getattr(user, "role", "") or "").strip().lower() == "admin"


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
    user.role = "admin"
    user.status = "active"
    user.api_access_enabled = True
    user.use_admin_api_pool = True
