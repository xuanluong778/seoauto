"""Guard chặn API đắt khi vượt ngưỡng chi phí SaaS."""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.rbac import is_admin

_LOG = logging.getLogger("saas_economics.guard")


def expensive_api_blocked(db: Session) -> bool:
    from app.services.saas_economics_service import get_economics_state

    state = get_economics_state(db)
    return bool(state.expensive_api_blocked)


def assert_expensive_api_allowed(
    db: Session,
    *,
    user: User,
    provider: object,
) -> None:
    """Raise HTTP 503 nếu API đắt bị chặn (admin luôn được phép)."""
    from app.services.saas_economics_service import get_economics_state, is_expensive_provider

    if is_admin(user):
        return
    if not is_expensive_provider(provider):
        return
    if expensive_api_blocked(db):
        state = get_economics_state(db)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "expensive_api_blocked",
                "message": (
                    "Hệ thống tạm chặn API tốn phí do vượt ngưỡng chi phí. "
                    "Vui lòng thử lại sau hoặc liên hệ admin."
                ),
                "reason": state.block_reason,
            },
        )


def check_economics_after_burn(db: Session, *, trigger: str = "credit_burn") -> None:
    """Gọi sau khi trừ credit để cập nhật trạng thái chặn."""
    try:
        from app.services.saas_economics_service import (
            evaluate_thresholds_and_block,
            load_economics_settings,
        )

        settings = load_economics_settings(db)
        if not settings.get("auto_block_expensive_api", True):
            return
        evaluate_thresholds_and_block(db, trigger=trigger)
    except Exception:
        _LOG.exception("saas_economics_guard_check_failed trigger=%s", trigger)
