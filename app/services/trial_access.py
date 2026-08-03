"""FastAPI dependency: block mutations when trial expired (read-only still allowed)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.rbac import can_write


def require_active_trial(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not can_write(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chỉ xem — không có quyền tạo nội dung.",
        )
    from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug

    if resolve_cau_ai_plan_slug(db, current_user):
        return current_user
    # Gói SaaS đang active (gồm free_trial_5d) — không bắt kích hoạt trial bằng API key.
    from app.services import subscription_service

    sub = subscription_service.get_active_subscription(db, current_user.id)
    if sub is not None and subscription_service.is_subscription_active(sub):
        return current_user
    from app.services.free_usage_service import has_active_free_usage

    if has_active_free_usage(db, current_user.id):
        return current_user
    from app.services.saas_trial_service import is_saas_trial_active

    if is_saas_trial_active(current_user):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "plan_required",
            "message": "Bạn cần gói, dùng thử 3 ngày hoặc ngày dùng phần mềm đang active.",
        },
    )
