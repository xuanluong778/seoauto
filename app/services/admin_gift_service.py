"""Admin gift plan / usage days — no SePay billing impact."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.payment_order import PaymentOrder
from app.models.security_audit_log import SecurityAuditLog
from app.models.user import User
from app.services import plan_service, subscription_service
from app.services.credit_policy_service import monthly_grant_for_plan
from app.services.credits import grant_credits
from app.services.free_usage_service import extend_free_usage_days, free_usage_days_remaining
from app.services.monthly_bonus_credit_service import sync_subscription_credit_locks
from app.services.seoauto_pricing_catalog import get_billing_product_by_code

GIFT_PLAN_ACTION = "admin.saas.gift_plan"
GIFT_DAYS_ACTION = "admin.saas.gift_days"
PAID_PLAN_SLUGS = frozenset({"starter", "pro", "agency", "business"})


def user_has_purchased_credit(db: Session, user_id: int) -> bool:
    """True if user ever bought credit pack (paid order or purchased ledger bucket)."""
    uid = int(user_id)
    ledger_hit = (
        db.query(CreditLedgerEntry.id)
        .filter(
            CreditLedgerEntry.user_id == uid,
            CreditLedgerEntry.source_type == "purchased",
        )
        .first()
    )
    if ledger_hit is not None:
        return True

    paid_orders = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.user_id == uid, PaymentOrder.status == "paid")
        .all()
    )
    for order in paid_orders:
        code = str(order.product_code or "").strip().upper()
        if code.startswith("CREDIT_"):
            return True
        product = get_billing_product_by_code(code)
        if product and str(product.get("product_type") or "") in ("credit_pack", "credit_addon"):
            return True
    return False


def gift_eligibility(db: Session, user_id: int) -> dict[str, Any]:
    sub = subscription_service.get_active_subscription(db, user_id)
    has_credit = user_has_purchased_credit(db, user_id)
    has_sub = sub is not None
    days_left = free_usage_days_remaining(db, user_id)
    message = None
    if days_left > 0:
        message = f"User đang có {days_left} ngày sử dụng miễn phí"
    elif not has_sub:
        message = "User chưa có gói active — vẫn có thể tặng ngày sử dụng miễn phí"
    return {
        "user_id": int(user_id),
        "has_credit_purchase": has_credit,
        "has_active_subscription": has_sub,
        "can_gift_days": True,
        "free_usage_days_remaining": days_left,
        "message": message,
    }


def _resolve_duration(*, duration_days: int | None, duration_months: int | None) -> tuple[int | None, int | None]:
    days = int(duration_days) if duration_days else None
    months = int(duration_months) if duration_months else None
    if days is None and months is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cần chọn số ngày hoặc số tháng sử dụng (> 0).",
        )
    if days is not None and days <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số ngày phải > 0.")
    if months is not None and months <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số tháng phải > 0.")
    return days, months


def admin_gift_plan(
    db: Session,
    *,
    admin: User,
    target: User,
    plan_slug: str,
    duration_days: int | None = None,
    duration_months: int | None = None,
    include_credit: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    slug = str(plan_slug or "").strip().lower()
    if slug not in PAID_PLAN_SLUGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gói không hợp lệ để tặng: {plan_slug}",
        )

    plan = plan_service.get_plan_by_slug(db, slug)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plan slug không tồn tại: {slug}")

    days, months = _resolve_duration(duration_days=duration_days, duration_months=duration_months)
    reason = (notes or "").strip() or "Admin tặng gói miễn phí"
    note = f"admin_gift plan={slug} days={days} months={months} | {reason}"

    period_days = days if months is None else None
    duration_months_val = months

    sub, action = subscription_service.extend_or_create_subscription(
        db,
        target.id,
        plan.id,
        period_days=period_days,
        duration_months=duration_months_val,
        status="active",
        source="admin_gift",
        notes=note[:2000],
    )

    from app.services.saas_trial_service import end_saas_trial_state, log_trial_audit

    end_saas_trial_state(db, target.id, reason="trial_to_paid")
    log_trial_audit(
        db,
        action="trial_to_paid",
        user_id=target.id,
        admin_id=admin.id,
        detail={"plan_slug": slug, "source": "admin_gift_plan"},
    )

    credits_granted = 0
    if include_credit:
        amount = int(monthly_grant_for_plan(slug) or 0)
        if amount > 0:
            sync_subscription_credit_locks(db, target.id)
            grant_credits(
                db,
                user_id=target.id,
                amount=amount,
                reason="admin_gift_plan_credit",
                source_type="admin_grant",
                note=f"admin_gift_plan subscription_id={sub.id} credits={amount}",
                expired_at=None,
            )
            credits_granted = amount

    result = {
        "gift_type": "plan",
        "subscription_id": int(sub.id),
        "subscription_action": action,
        "plan_slug": slug,
        "plan_name": plan.name,
        "duration_days": days,
        "duration_months": months,
        "credits_granted": credits_granted,
        "include_credit": bool(include_credit),
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "notes": reason,
    }
    return result


def admin_gift_usage_days(
    db: Session,
    *,
    admin: User,
    target: User,
    days: int,
    notes: str | None = None,
) -> dict[str, Any]:
    gift_days = int(days)
    if gift_days <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Số ngày phải > 0.")

    reason = (notes or "").strip() or "Admin tặng ngày sử dụng miễn phí"
    new_end, previous_end = extend_free_usage_days(db, target.id, gift_days)

    return {
        "gift_type": "usage_days",
        "subscription_id": None,
        "plan_slug": None,
        "plan_name": None,
        "days_granted": gift_days,
        "previous_free_usage_expires_at": previous_end.isoformat() if previous_end else None,
        "free_usage_expires_at": new_end.isoformat() if new_end else None,
        "free_usage_days_remaining": free_usage_days_remaining(db, target.id),
        "notes": reason,
        "admin_id": int(admin.id),
        "user_id": int(target.id),
    }


def list_user_gift_history(db: Session, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    uid = str(int(user_id))
    rows = (
        db.query(SecurityAuditLog)
        .filter(
            SecurityAuditLog.action.in_((GIFT_PLAN_ACTION, GIFT_DAYS_ACTION)),
            SecurityAuditLog.resource_type == "user",
            SecurityAuditLog.resource_id == uid,
        )
        .order_by(SecurityAuditLog.created_at.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        detail: dict[str, Any] = {}
        try:
            parsed = json.loads(row.detail_json or "{}")
            if isinstance(parsed, dict):
                detail = parsed
        except json.JSONDecodeError:
            detail = {}
        gift_type = "plan" if row.action == GIFT_PLAN_ACTION else "usage_days"
        badge = "Gói được tặng" if gift_type == "plan" else "Ngày sử dụng được tặng"
        out.append(
            {
                "id": row.id,
                "gift_type": gift_type,
                "badge": badge,
                "action": row.action,
                "admin_id": detail.get("admin_id"),
                "plan_slug": detail.get("plan_slug"),
                "plan_name": detail.get("plan_name"),
                "duration_days": detail.get("duration_days"),
                "duration_months": detail.get("duration_months"),
                "days_granted": detail.get("days_granted"),
                "credits_granted": detail.get("credits_granted", 0),
                "notes": detail.get("reason") or detail.get("notes"),
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
        )
    return out
