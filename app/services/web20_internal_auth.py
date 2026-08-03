"""Internal / admin access for Web 2.0 scheduler."""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, Request, status

from app.models.user import User
from app.services.auth import get_optional_current_user
from app.services.rbac import is_admin


def _internal_token() -> str:
    return str(os.getenv("WEB20_INTERNAL_TOKEN") or os.getenv("INTERNAL_CRON_TOKEN") or "").strip()


def require_web20_internal_or_admin(
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
) -> User | None:
    expected = _internal_token()
    header = str(request.headers.get("X-Internal-Token") or "").strip()
    if expected and header and secrets.compare_digest(header, expected):
        return None
    if current_user and is_admin(current_user):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Cần admin hoặc X-Internal-Token hợp lệ.",
    )
