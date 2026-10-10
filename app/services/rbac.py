"""Role-based access: super_admin, admin, user, editor, viewer."""

from __future__ import annotations

from fastapi import Depends

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
    """Platform admin access (role or ADMIN_EMAIL). Not the same as free credits."""
    if user is None:
        return False
    if is_admin_role_name(getattr(user, "role", None)):
        return True
    email = str(getattr(user, "email", "") or "")
    if is_configured_admin_email(email):
        return True
    return is_platform_admin(user)


def admin_skips_credit_deduction(user: User | None) -> bool:
    """
    Whether credit consume/reserve should no-op for this user.

    super_admin never spends credits. Other admins are charged by default so
    Content AI and billing can be tested on admin accounts.
    Opt-in free unlimited credits for all admins: ADMIN_FREE_CREDITS=1.
    """
    if is_super_admin(user):
        return True
    if not is_admin(user):
        return False
    import os

    raw = (os.getenv("ADMIN_FREE_CREDITS") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def has_unlimited_access(user: User | None) -> bool:
    """Skip plan caps / feature locks for admins. Credit free only when ADMIN_FREE_CREDITS."""
    return is_admin(user)


def can_write(user: User) -> bool:
    from app.services.permissions import PERM_WORKSPACE_WRITE, has_permission

    return has_permission(user, PERM_WORKSPACE_WRITE)


def can_write_in_org(user: User, db: Session, organization_id: int) -> bool:
    from app.services.permissions import PERM_WORKSPACE_WRITE, has_permission

    return has_permission(user, PERM_WORKSPACE_WRITE, db=db, organization_id=organization_id)


def require_write_user(current_user: User = Depends(get_current_user)) -> User:
    from app.services.permissions import PERM_WORKSPACE_WRITE, assert_permission

    assert_permission(current_user, PERM_WORKSPACE_WRITE)
    return current_user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    from app.services.permissions import PERM_ADMIN_ACCESS, assert_permission

    assert_permission(current_user, PERM_ADMIN_ACCESS)
    return current_user
