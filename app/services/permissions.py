"""RBAC permission matrix — platform roles + organization member roles."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user

# --- Permission keys (stable API for backend checks) ---
PERM_ADMIN_ACCESS = "admin.access"
PERM_WORKSPACE_READ = "workspace.read"
PERM_WORKSPACE_WRITE = "workspace.write"
PERM_SETTINGS_WRITE = "settings.write"
PERM_BILLING_MANAGE = "billing.manage"
PERM_API_KEYS_MANAGE = "api_keys.manage"
PERM_ORG_MEMBERS_MANAGE = "org.members.manage"
PERM_ORG_SETTINGS = "org.settings"

ALL_PERMISSIONS = frozenset(
    {
        PERM_ADMIN_ACCESS,
        PERM_WORKSPACE_READ,
        PERM_WORKSPACE_WRITE,
        PERM_SETTINGS_WRITE,
        PERM_BILLING_MANAGE,
        PERM_API_KEYS_MANAGE,
        PERM_ORG_MEMBERS_MANAGE,
        PERM_ORG_SETTINGS,
    }
)

ORG_ROLES = frozenset({"owner", "admin", "editor", "viewer"})

ORG_SCOPED_PERMISSIONS = frozenset(
    {
        PERM_ORG_MEMBERS_MANAGE,
        PERM_ORG_SETTINGS,
        PERM_BILLING_MANAGE,
    }
)

# Platform role → granted permissions (super_admin handled separately — all).
_PLATFORM_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(
        {
            PERM_ADMIN_ACCESS,
            PERM_WORKSPACE_READ,
            PERM_WORKSPACE_WRITE,
            PERM_SETTINGS_WRITE,
            PERM_BILLING_MANAGE,
            PERM_API_KEYS_MANAGE,
            PERM_ORG_MEMBERS_MANAGE,
            PERM_ORG_SETTINGS,
        }
    ),
    "user": frozenset(
        {
            PERM_WORKSPACE_READ,
            PERM_WORKSPACE_WRITE,
            PERM_SETTINGS_WRITE,
            PERM_BILLING_MANAGE,
        }
    ),
    "editor": frozenset(
        {
            PERM_WORKSPACE_READ,
            PERM_WORKSPACE_WRITE,
            PERM_SETTINGS_WRITE,
        }
    ),
    "viewer": frozenset({PERM_WORKSPACE_READ}),
}

# Organization member role → granted permissions within that org.
_ORG_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            PERM_WORKSPACE_READ,
            PERM_WORKSPACE_WRITE,
            PERM_BILLING_MANAGE,
            PERM_ORG_MEMBERS_MANAGE,
            PERM_ORG_SETTINGS,
        }
    ),
    "admin": frozenset(
        {
            PERM_WORKSPACE_READ,
            PERM_WORKSPACE_WRITE,
            PERM_BILLING_MANAGE,
            PERM_ORG_MEMBERS_MANAGE,
            PERM_ORG_SETTINGS,
        }
    ),
    "editor": frozenset({PERM_WORKSPACE_READ, PERM_WORKSPACE_WRITE}),
    "viewer": frozenset({PERM_WORKSPACE_READ}),
}


def normalize_org_role(role: str | None) -> str:
    r = str(role or "viewer").strip().lower()
    return r if r in ORG_ROLES else "viewer"


def platform_permissions_for_role(role: str | None) -> frozenset[str]:
    """Return permissions granted by platform role (excludes super_admin shortcut)."""
    from app.services.rbac import normalize_role

    return _PLATFORM_ROLE_PERMISSIONS.get(normalize_role(role), frozenset())


def org_permissions_for_role(role: str | None) -> frozenset[str]:
    return _ORG_ROLE_PERMISSIONS.get(normalize_org_role(role), frozenset())


def permission_matrix() -> dict[str, dict[str, list[str]]]:
    """Human/machine-readable matrix for docs and tests."""
    from app.services.rbac import ROLES

    platform: dict[str, list[str]] = {"super_admin": sorted(ALL_PERMISSIONS)}
    for role in sorted(ROLES - {"super_admin"}):
        platform[role] = sorted(platform_permissions_for_role(role))
    org: dict[str, list[str]] = {}
    for role in sorted(ORG_ROLES):
        org[role] = sorted(org_permissions_for_role(role))
    return {"platform": platform, "organization": org}


def _platform_allows(user: User, permission: str) -> bool:
    from app.services.rbac import is_admin, is_super_admin, normalize_role

    if permission not in ALL_PERMISSIONS:
        return False
    if is_super_admin(user):
        return True
    if permission == PERM_ADMIN_ACCESS or permission == PERM_API_KEYS_MANAGE:
        return is_admin(user)
    role = normalize_role(getattr(user, "role", None))
    return permission in _PLATFORM_ROLE_PERMISSIONS.get(role, frozenset())


def _org_allows(db: Session, user_id: int, organization_id: int, permission: str) -> bool:
    from app.services.tenant_org import resolve_org_member_role

    org_role = resolve_org_member_role(db, user_id, organization_id)
    return permission in _ORG_ROLE_PERMISSIONS.get(org_role, frozenset())


def has_permission(
    user: User,
    permission: str,
    *,
    db: Session | None = None,
    organization_id: int | None = None,
) -> bool:
    """
    Effective permission with optional org context.

    - Platform-only (admin.access, api_keys.manage): platform role only.
    - Org-scoped (org.members.manage, org.settings, billing.manage + org_id): org role
      is authoritative; caller must at least have workspace.read on platform.
    - Workspace read/write: platform role AND org member role must both allow.
    """
    from app.services.rbac import is_super_admin

    if permission not in ALL_PERMISSIONS:
        return False
    if is_super_admin(user):
        return True

    if permission in {PERM_ADMIN_ACCESS, PERM_API_KEYS_MANAGE}:
        return _platform_allows(user, permission)

    if db is None or organization_id is None:
        return _platform_allows(user, permission)

    oid = int(organization_id)

    if permission in ORG_SCOPED_PERMISSIONS:
        if not _platform_allows(user, PERM_WORKSPACE_READ):
            return False
        return _org_allows(db, int(user.id), oid, permission)

    if not _platform_allows(user, permission):
        return False
    return _org_allows(db, int(user.id), oid, permission)


def assert_permission(
    user: User,
    permission: str,
    *,
    db: Session | None = None,
    organization_id: int | None = None,
    detail: str | None = None,
) -> None:
    if has_permission(user, permission, db=db, organization_id=organization_id):
        return
    msg = detail or _default_deny_message(permission)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)


def _default_deny_message(permission: str) -> str:
    if permission == PERM_ADMIN_ACCESS:
        return "Bạn không có quyền thực hiện thao tác này."
    if permission == PERM_WORKSPACE_WRITE:
        return "Tài khoản chỉ xem (viewer) — không có quyền chỉnh sửa."
    if permission == PERM_WORKSPACE_READ:
        return "Bạn không có quyền xem dữ liệu này."
    if permission == PERM_API_KEYS_MANAGE:
        return "Chỉ quản trị viên được cấu hình API hệ thống."
    return "Bạn không có quyền thực hiện thao tác này."


def require_permission(
    permission: str,
    *,
    organization_resolver: Callable[[User, Session], int | None] | None = None,
):
    """
    FastAPI dependency factory.

    organization_resolver(user, db) → org_id for org-scoped checks; None = platform only.
    """

    def _dep(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        org_id = organization_resolver(current_user, db) if organization_resolver else None
        assert_permission(current_user, permission, db=db, organization_id=org_id)
        return current_user

    return _dep
