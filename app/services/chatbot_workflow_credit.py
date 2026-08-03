"""Credit chung cho workflow Chatbot AI: ước tính, xác nhận, trừ credit, lịch sử."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.chatbot_workflow_credit_log import ChatbotWorkflowCreditLog
from app.services.chatbot_tab_registry import estimate_workflow_credits
from app.services.credits import credits_enforced, ensure_sufficient_credits, get_available_balance

_LOG = logging.getLogger(__name__)

SUPPORTED_WORKFLOW_INTENTS = frozenset(
    {
        "quick_keyword_article",
        "keyword_cluster_to_article",
        "keyword_research",
        "keyword_research_cluster",
        "url_seo_scoreboard",
        "content_seo_score",
        "technical_quick_audit",
        "technical_deep_audit",
        "technical_single_url",
    }
)

CREDIT_STATUS_PENDING = "pending"
CREDIT_STATUS_CHARGED = "charged"
CREDIT_STATUS_RUNNING = "running"
CREDIT_STATUS_COMPLETED = "completed"
CREDIT_STATUS_FAILED = "failed"
CREDIT_STATUS_CANCELLED = "cancelled"
CREDIT_STATUS_REFUNDED = "refunded"

_REFUNDABLE_STATUSES = frozenset(
    {
        CREDIT_STATUS_CHARGED,
        CREDIT_STATUS_RUNNING,
        CREDIT_STATUS_FAILED,
    }
)


def format_credit_estimate_message(total: int) -> str:
    return f"Tác vụ này dự kiến tốn {int(total)} credit."


def format_insufficient_credit_message(required: int, balance: int) -> str:
    return f"Bạn cần {int(required)} credit, tài khoản hiện có {int(balance)} credit."


class InsufficientCreditError(ValueError):
    """Không đủ credit để chạy workflow."""

    def __init__(self, *, required: int, balance: int) -> None:
        self.required = int(required)
        self.balance = int(balance)
        self.message = format_insufficient_credit_message(self.required, self.balance)
        super().__init__(self.message)


def quote_workflow_credits(
    db: Session,
    user_id: int,
    intent: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ước tính credit trước khi chạy (không trừ credit)."""
    from app.models.user import User
    from app.services.entitlement_service import can_use_ai
    from app.services.software_access_service import user_has_software_access

    user = db.get(User, int(user_id))
    if user is None:
        raise ValueError("User không tồn tại.")

    credits = estimate_workflow_credits(intent, params or {})
    total = int(credits.get("total") or 0)
    balance, sufficient = ensure_sufficient_credits(db, user_id, total)
    if not credits_enforced():
        balance = get_available_balance(db, user_id)
        sufficient = True

    access_ok = user_has_software_access(db, user_id)
    ai_gate = can_use_ai(db, user, "content_ai_article", estimated_credit_cost=max(1, total))
    allowed = bool(access_ok and ai_gate.get("allowed") and sufficient)

    return {
        "credits": credits,
        "credit_required": total,
        "credit_balance": balance,
        "balance": balance,
        "sufficient": allowed,
        "credit_estimate_message": format_credit_estimate_message(total),
        "insufficient_message": (
            str(ai_gate.get("message") or format_insufficient_credit_message(total, balance))
            if not allowed
            else None
        ),
    }


def ensure_workflow_intent_supported(intent: str) -> None:
    key = str(intent or "").strip()
    if key not in SUPPORTED_WORKFLOW_INTENTS:
        raise ValueError(f"Intent không hỗ trợ: {key}")


def create_credit_log(
    db: Session,
    *,
    user_id: int,
    workflow: str,
    task_id: str,
    credit_used: int,
    status: str = CREDIT_STATUS_PENDING,
) -> ChatbotWorkflowCreditLog:
    row = ChatbotWorkflowCreditLog(
        user_id=int(user_id),
        workflow=str(workflow or "")[:80],
        credit_used=max(0, int(credit_used)),
        task_id=str(task_id or "")[:64],
        status=str(status or CREDIT_STATUS_PENDING)[:32],
    )
    db.add(row)
    db.flush()
    return row


def update_credit_log(
    db: Session,
    *,
    task_id: str,
    status: str,
    credit_used: int | None = None,
    error_reason: str | None = None,
) -> None:
    row = (
        db.query(ChatbotWorkflowCreditLog)
        .filter(ChatbotWorkflowCreditLog.task_id == str(task_id))
        .order_by(ChatbotWorkflowCreditLog.id.desc())
        .first()
    )
    if not row:
        _LOG.warning("chatbot credit log not found task_id=%s status=%s", task_id, status)
        return
    row.status = str(status or "")[:32]
    if credit_used is not None:
        row.credit_used = max(0, int(credit_used))
    if error_reason is not None:
        row.error_reason = str(error_reason)[:2000] or None
    db.flush()


def update_credit_log_in_new_session(
    *,
    task_id: str,
    status: str,
    credit_used: int | None = None,
    error_reason: str | None = None,
) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        update_credit_log(
            db,
            task_id=task_id,
            status=status,
            credit_used=credit_used,
            error_reason=error_reason,
        )
        db.commit()
    except Exception:
        db.rollback()
        _LOG.exception("failed to update chatbot credit log task_id=%s status=%s", task_id, status)
    finally:
        db.close()


def refund_workflow_credits(
    db: Session,
    *,
    user_id: int,
    task_id: str,
    reason: str = "",
) -> int:
    """Hoàn credit khi workflow thất bại sau khi đã trừ. Trả số credit đã hoàn."""
    from app.models.user import User
    from app.services.credits import credits_enforced, grant_credits
    from app.services.rbac import is_admin

    row = (
        db.query(ChatbotWorkflowCreditLog)
        .filter(
            ChatbotWorkflowCreditLog.task_id == str(task_id),
            ChatbotWorkflowCreditLog.user_id == int(user_id),
        )
        .order_by(ChatbotWorkflowCreditLog.id.desc())
        .first()
    )
    if not row:
        _LOG.warning("chatbot refund: log not found task_id=%s user_id=%s", task_id, user_id)
        return 0
    if row.status == CREDIT_STATUS_REFUNDED:
        return 0
    if row.status not in _REFUNDABLE_STATUSES:
        return 0

    amount = max(0, int(row.credit_used or 0))
    err_note = str(reason or row.error_reason or "workflow_failed")[:2000]

    if amount <= 0 or not credits_enforced():
        row.status = CREDIT_STATUS_REFUNDED
        row.credit_used = 0
        row.error_reason = err_note or None
        db.flush()
        return 0

    user = db.get(User, int(user_id))
    if user and is_admin(user):
        row.status = CREDIT_STATUS_REFUNDED
        row.credit_used = 0
        row.error_reason = err_note or None
        db.flush()
        return 0

    note = f"refund wf={str(task_id)[:32]};{(reason or 'workflow_failed')[:180]}"
    grant_credits(
        db,
        user_id=int(user_id),
        amount=amount,
        reason="chatbot_workflow_refund",
        note=note,
        source_type="refund",
    )
    row.status = CREDIT_STATUS_REFUNDED
    row.credit_used = 0
    row.error_reason = err_note or None
    db.flush()
    _LOG.info(
        "chatbot workflow credit refunded task_id=%s user_id=%s amount=%s",
        task_id,
        user_id,
        amount,
    )
    return amount


def refund_workflow_credits_in_new_session(
    *,
    user_id: int,
    task_id: str,
    reason: str = "",
) -> int:
    """Hoàn credit trong session riêng (workflow thread). Trả số credit đã hoàn."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        refunded = refund_workflow_credits(
            db,
            user_id=int(user_id),
            task_id=str(task_id),
            reason=reason,
        )
        db.commit()
        return refunded
    except Exception:
        db.rollback()
        _LOG.exception("chatbot workflow refund failed task_id=%s user_id=%s", task_id, user_id)
        return 0
    finally:
        db.close()
