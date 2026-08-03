"""Standard SaaS / Content AI user-facing messages."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import user_api_access
from app.services.credits import get_available_balance
from app.services.rbac import is_admin
from app.services.saas_trial_service import trial_status_payload
from app.services.software_access_service import user_has_software_access

MSG_NO_TRIAL = "Bạn chưa kích hoạt dùng thử 3 ngày."
MSG_NEED_CREDIT = "Bạn đã có quyền dùng phần mềm. Vui lòng mua credit để sử dụng AI."
MSG_SYSTEM_OK = "Bạn đang dùng API hệ thống. Credit sẽ bị trừ theo lượt sử dụng."
MSG_EXPIRED = "Gói dùng thử hoặc quyền sử dụng đã hết hạn. Vui lòng gia hạn hoặc nâng cấp."
MSG_SYSTEM_API_MISSING = user_api_access.SYSTEM_API_NOT_CONFIGURED_MSG

# Legacy phrases that must not appear in user UI
FORBIDDEN_UI_PHRASES = (
    "dùng thử 5 ngày",
    "5 ngày",
    "thêm api key",
    "api key hợp lệ",
    "byok",
)


def resolve_ai_access_state(db: Session, user: User) -> dict[str, Any]:
    """
    Unified UI state for SaaS / Content AI.
    States: admin | no_trial | need_credit | ready | expired | system_api_missing
    """
    if is_admin(user):
        return {
            "state": "admin",
            "message": MSG_SYSTEM_OK,
            "can_use_ai": True,
            "use_system_llm": True,
            "credit_balance": get_available_balance(db, user.id),
        }

    balance = int(get_available_balance(db, user.id))
    has_access = user_has_software_access(db, user.id)
    trial_snap = trial_status_payload(db, user)
    system_ok = user_api_access.admin_system_llm_available(db)

    if not has_access:
        if trial_snap.get("can_activate"):
            return {
                "state": "no_trial",
                "message": MSG_NO_TRIAL,
                "can_use_ai": False,
                "use_system_llm": True,
                "credit_balance": balance,
                "can_activate_trial": True,
            }
        return {
            "state": "expired",
            "message": MSG_EXPIRED,
            "can_use_ai": False,
            "use_system_llm": True,
            "credit_balance": balance,
        }

    if not system_ok:
        return {
            "state": "system_api_missing",
            "message": MSG_SYSTEM_API_MISSING,
            "can_use_ai": False,
            "use_system_llm": True,
            "credit_balance": balance,
        }

    if balance <= 0:
        return {
            "state": "need_credit",
            "message": MSG_NEED_CREDIT,
            "can_use_ai": False,
            "use_system_llm": True,
            "credit_balance": balance,
        }

    return {
        "state": "ready",
        "message": MSG_SYSTEM_OK,
        "can_use_ai": True,
        "use_system_llm": True,
        "credit_balance": balance,
    }
