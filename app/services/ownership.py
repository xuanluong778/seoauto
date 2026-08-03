"""Record ownership checks — prevent cross-user data access."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.admin_auth import _is_admin_role

T = TypeVar("T")


def is_admin_user(user: User) -> bool:
    return _is_admin_role(user)


def check_owner(record_user_id: int | None, current_user_id: int, *, allow_admin: bool = False, admin: User | None = None) -> None:
    if record_user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if int(record_user_id) != int(current_user_id):
        if allow_admin and admin is not None and is_admin_user(admin):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def require_owned_record(
    db: Session,
    model: type[T],
    record_id: int,
    current_user: User,
    *,
    owner_field: str = "user_id",
    allow_admin: bool = False,
) -> T:
    row = db.query(model).filter(model.id == int(record_id)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    owner_id = getattr(row, owner_field, None)
    check_owner(owner_id, current_user.id, allow_admin=allow_admin, admin=current_user)
    return row


def audit_belongs_to_user(audit: dict | None, user_id: int) -> bool:
    if not audit or not isinstance(audit, dict):
        return False
    raw = audit.get("user_id")
    if raw is None:
        return False
    try:
        return int(raw) == int(user_id)
    except (TypeError, ValueError):
        return False
