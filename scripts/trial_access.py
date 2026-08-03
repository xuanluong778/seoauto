"""FastAPI dependency: block mutations when trial expired (read-only still allowed)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.rbac import can_write, normalize_role
from app.services.user_api_access import api_access_enabled_for
from app.services.user_trial_service import trial_status_snapshot


def require_active_trial(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not can_write(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chỉ xem — không có quyền tạo nội dung.",
        )
    # Admin đã bật「Cho phép dùng API」— không bắt kích hoạt trial bằng khóa riêng.
    if api_access_enabled_for(current_user):
        return current_user
    snap = trial_status_snapshot(db, current_user.id, role=normalize_role(current_user.role))
    if not snap.get("is_active"):
        msg = str(snap.get("message") or "Dùng thử không còn hiệu lực.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "trial_expired",
                "message": msg,
                "trial": snap,
            },
        )
    return current_user
