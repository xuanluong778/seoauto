"""Role-based access: super_admin, admin, user, editor, viewer."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.models.user import User
from app.services.admin_auth import is_configured_admin_email, is_platform_admin
from app.services.auth import get_current_user

ROLES = frozenset({"super_admin", "admin", "user", "editor", "viewer"})
ADMIN_ROLES = frozenset({"super_admin", "admin"})
WRITE_ROLES = frozenset({"super_admin", "admin", "user", "editor"})
STATUSES = frozenset({"active", "inactive", "banned"})


def normalize_role(role: str | None) -> str:
    r = str(role or "user").strip().lower()
    return r if r in ROLES else "user"


def normalize_status(status: str | None) -> str:
    s = str(status or "active").strip().lower()
    return s if s in STATUSES else "active"


def is_user_active(user: User) -> bool:
    return normalize_status(getattr(user, "status", None)) == "active"


def is_super_admin(user: User | None) -> bool:
    if user is None:
        return False
    return normalize_role(getattr(user, "role", None)) == "super_admin"


def is_admin_role_name(role: str | None) -> bool:
    return normalize_role(role) in ADMIN_ROLES


def is_admin(user: User | None) -> bool:
    """Full SaaS / credit / feature bypass for admin & super_admin (role-based)."""
    if user is None:
        return False
    if is_admin_role_name(getattr(user, "role", None)):
        return True
    email = str(getattr(user, "email", "") or "")
    if is_configured_admin_email(email):
        return True
    return is_platform_admin(user)


def has_unlimited_access(user: User | None) -> bool:
    """Alias: skip plan expiry, site caps, and credit charges."""
    return is_admin(user)


def can_write(user: User) -> bool:
    return normalize_role(getattr(user, "role", None)) in WRITE_ROLES


def require_write_user(current_user: User = Depends(get_current_user)) -> User:
    if not can_write(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chỉ xem (viewer) — không có quyền chỉnh sửa.",
        )
    return current_user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thực hiện thao tác này.",
        )
    return current_user
