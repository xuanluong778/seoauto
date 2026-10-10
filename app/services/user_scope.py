"""Helpers for per-user data isolation in JSON stores and async jobs."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.services.rbac import normalize_role


def entry_user_id(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def is_legacy_orphan(entry: dict[str, Any]) -> bool:
    return bool(entry.get("legacy_orphan")) or ("user_id" not in entry)


def is_admin_role(role: str | None) -> bool:
    from app.services.rbac import is_admin_role_name

    return is_admin_role_name(role)


def belongs_to_user(entry: dict[str, Any], user_id: int) -> bool:
    """Only rows with an explicit owner are visible (legacy rows without user_id are hidden)."""
    if "user_id" not in entry:
        return False
    if is_legacy_orphan(entry) and entry_user_id(entry) <= 0:
        return False
    try:
        return int(entry.get("user_id")) == int(user_id)
    except (TypeError, ValueError):
        return False


def can_access_record(
    entry: dict[str, Any] | None,
    user_id: int,
    role: str | None = "user",
    *,
    allow_global: bool = False,
) -> bool:
    """True if user may read the record (owner, admin, or optional global scope)."""
    if not entry:
        return False
    if is_admin_role(role):
        return True
    if allow_global and str(entry.get("scope") or "").lower() == "global":
        return True
    if is_legacy_orphan(entry):
        return False
    return belongs_to_user(entry, user_id)


def require_owner_or_admin(
    entry: dict[str, Any] | None,
    user_id: int,
    role: str | None = "user",
    *,
    detail: str = "Không tìm thấy tài nguyên.",
    write: bool = False,
) -> dict[str, Any]:
    """
    Read: owner or admin.
    Write (write=True): owner only; admin may write any user's data; non-admin cannot write others'.
    """
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if is_admin_role(role):
        return entry
    if is_legacy_orphan(entry):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if not belongs_to_user(entry, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return entry


def assert_record_owner(
    entry: dict[str, Any] | None,
    user_id: int,
    *,
    detail: str = "Không tìm thấy tài nguyên.",
) -> None:
    if not entry or not belongs_to_user(entry, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def assert_owner_or_admin(
    entry: dict[str, Any] | None,
    user_id: int,
    role: str | None = "user",
    *,
    detail: str = "Không tìm thấy tài nguyên.",
    write: bool = False,
) -> dict[str, Any]:
    return require_owner_or_admin(entry, user_id, role, detail=detail, write=write)


def job_owner_user_id(payload: dict[str, Any] | None) -> int:
    if not payload:
        return 0
    try:
        return int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def assert_job_access(payload: dict[str, Any] | None, user_id: int) -> None:
    """Legacy helper — prefer get_job_for_user / assert_job_owned."""
    owner = job_owner_user_id(payload)
    if not owner or owner != int(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy job.")


def assert_job_owned(
    job: Any | None,
    user_id: int,
    *,
    organization_id: int | None = None,
    detail: str = "Không tìm thấy job.",
) -> Any:
    """Require job ownership via JobState columns or dict, never id alone."""
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    uid = int(user_id or 0)
    if uid <= 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    from app.services.tenant_org import OrganizationForbiddenError, resolve_organization_id

    try:
        org_id = resolve_organization_id(uid, organization_id)
    except OrganizationForbiddenError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from None

    job_uid = getattr(job, "user_id", None)
    job_org = getattr(job, "organization_id", None)
    if job_uid is None and isinstance(job, dict):
        try:
            job_uid = int(job.get("user_id") or 0) or None
        except (TypeError, ValueError):
            job_uid = None
        try:
            job_org = int(job.get("organization_id") or 0) or None
        except (TypeError, ValueError):
            job_org = None
    if job_uid is None and getattr(job, "payload", None):
        try:
            job_uid = int((job.payload or {}).get("user_id") or 0) or None
        except (TypeError, ValueError):
            job_uid = None
    if job_uid is None or int(job_uid) != uid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if job_org is not None and int(job_org) != int(org_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return job