"""Chatbot CSKH credits — monthly allowance + admin bonus, separate from keyword/content credits."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotUsage
from app.models.chatbot_cskh_credit_log import ChatbotCskhCreditLog
from app.models.user import User
from app.services.chatbot_cskh_entitlement import monthly_reply_limit_for_plan

REPLY_CREDIT_COST = 1


def month_key(dt: datetime | None = None) -> str:
    when = dt or datetime.now(timezone.utc)
    return when.strftime("%Y-%m")


def get_bonus_credits(db: Session, user_id: int) -> int:
    user = db.get(User, int(user_id))
    if user is None:
        return 0
    return max(0, int(getattr(user, "chatbot_cskh_bonus_credits", 0) or 0))


def monthly_replies_used(db: Session, user_id: int, *, month: str | None = None) -> int:
    mk = str(month or month_key()).strip()[:7]
    return int(
        db.execute(
            select(func.coalesce(func.sum(ChatbotUsage.ai_replies), 0)).where(
                ChatbotUsage.user_id == int(user_id),
                ChatbotUsage.month == mk,
            )
        ).scalar()
        or 0
    )


def effective_monthly_limit(plan_slug: str | None, bonus_credits: int = 0) -> int:
    return max(0, monthly_reply_limit_for_plan(plan_slug)) + max(0, int(bonus_credits or 0))


def build_usage_snapshot(db: Session, user_id: int, plan_slug: str | None) -> dict[str, Any]:
    used = monthly_replies_used(db, user_id)
    bonus = get_bonus_credits(db, user_id)
    plan_limit = monthly_reply_limit_for_plan(plan_slug)
    limit = effective_monthly_limit(plan_slug, bonus)
    remaining = max(0, limit - used)
    return {
        "month": month_key(),
        "ai_replies_used": used,
        "plan_monthly_limit": plan_limit,
        "bonus_credits": bonus,
        "effective_limit": limit,
        "remaining": remaining,
        "allowed": used < limit,
    }


def assert_can_consume_reply(db: Session, user_id: int, plan_slug: str | None) -> dict[str, Any]:
    snap = build_usage_snapshot(db, user_id, plan_slug)
    if snap["allowed"]:
        return {**snap, "billing": "quota", "overage_cost": 0}
    from app.services.credits import cost_chatbot_cskh_reply, credits_enforced, ensure_sufficient_credits

    if not credits_enforced():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "reply_limit_exceeded",
                "message": "Đã đạt giới hạn lượt AI trả lời tháng này. Nâng cấp gói hoặc liên hệ admin để mua thêm credit chatbot.",
                "feature_key": "chatbot_cskh",
                "upgrade_url": "/pricing",
                "usage": snap,
            },
        )
    overage_cost = cost_chatbot_cskh_reply(db=db)
    balance, sufficient = ensure_sufficient_credits(db, user_id, overage_cost)
    if not sufficient:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "reply_limit_exceeded",
                "message": "Đã hết quota chatbot tháng này và không đủ credit ví chung để tiếp tục.",
                "feature_key": "chatbot_cskh",
                "upgrade_url": "/pricing",
                "usage": snap,
                "balance": balance,
                "required": overage_cost,
            },
        )
    return {**snap, "billing": "main_credit", "overage_cost": overage_cost}


def record_cskh_ai_reply(db: Session, user_id: int, bot_id: int, plan_slug: str | None) -> dict[str, Any]:
    """Ghi usage; nếu vượt quota thì trừ credit ví chung."""
    snap = build_usage_snapshot(db, user_id, plan_slug)
    overage = not bool(snap.get("allowed"))
    charged = 0
    if overage:
        from app.services.credit_cost_registry import new_request_id
        from app.services.credits import consume_credits, cost_chatbot_cskh_reply, credits_enforced

        if credits_enforced():
            charged = cost_chatbot_cskh_reply(db=db)
            if charged > 0:
                consume_credits(
                    db,
                    user_id=int(user_id),
                    amount=charged,
                    reason="chatbot_cskh_overage",
                    note=f"bot_id={bot_id}",
                    module="chatbot_cskh",
                    action="reply_overage",
                    request_id=new_request_id(),
                    source="overage",
                )
    increment_reply_usage(db, user_id, bot_id, replies=1)
    return {"overage": overage, "credit_charged": charged}


def increment_reply_usage(db: Session, user_id: int, bot_id: int, *, replies: int = 1) -> None:
    """Record one AI reply (=1 chatbot credit) in chatbot_usage."""
    amount = max(0, int(replies))
    if amount <= 0:
        return
    mk = month_key()
    row = db.execute(
        select(ChatbotUsage).where(
            ChatbotUsage.user_id == int(user_id),
            ChatbotUsage.bot_id == int(bot_id),
            ChatbotUsage.month == mk,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ChatbotUsage(
            user_id=int(user_id),
            bot_id=int(bot_id),
            month=mk,
            ai_replies=0,
            credits_used=0,
        )
        db.add(row)
    credit = amount * REPLY_CREDIT_COST
    row.ai_replies = int(row.ai_replies or 0) + amount
    row.credits_used = int(row.credits_used or 0) + credit
    db.commit()


def adjust_bonus_credits(
    db: Session,
    *,
    user_id: int,
    delta: int,
    reason: str,
    admin_id: int | None = None,
    internal_note: str | None = None,
) -> int:
    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy user.")

    change = int(delta)
    if change == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số credit không hợp lệ.")

    grant_reason = str(reason or "").strip()
    if not grant_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lý do không được để trống.")

    current = max(0, int(getattr(user, "chatbot_cskh_bonus_credits", 0) or 0))
    new_balance = current + change
    if new_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không thể trừ {abs(change)} credit — số dư chatbot hiện có {current}.",
        )

    user.chatbot_cskh_bonus_credits = new_balance
    db.add(
        ChatbotCskhCreditLog(
            user_id=user.id,
            admin_id=admin_id,
            delta=change,
            balance_after=new_balance,
            reason=grant_reason[:500],
            internal_note=(internal_note or "").strip()[:2000] or None,
        )
    )
    db.commit()
    db.refresh(user)
    return new_balance
