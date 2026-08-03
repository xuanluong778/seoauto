"""Monthly bonus credit — lock/unlock on subscription, cap accumulation, idempotent grants."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.user import User
from app.services import subscription_service
from app.services.credit_policy_service import (
    accumulation_cap_for_plan,
    monthly_grant_for_plan,
    policy_snapshot,
)
from app.services.credits import (
    _sync_user_balance,
    _user_query_for_update,
    get_available_balance,
    grant_credits,
)

logger = logging.getLogger(__name__)

MONTHLY_BONUS_SOURCES = frozenset({"monthly_bonus", "plan_monthly"})
BUCKET_ACTIVE = "active"
BUCKET_LOCKED = "locked"
BUCKET_EXPIRED = "expired"
BUCKET_CONSUMED = "consumed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_monthly_bonus_source(source_type: str | None) -> bool:
    return str(source_type or "").strip().lower() in MONTHLY_BONUS_SOURCES


def _append_ledger_event(
    db: Session,
    *,
    user_id: int,
    reason: str,
    note: str,
    balance_after: int,
    credit_type: str | None = None,
) -> None:
    db.add(
        CreditLedger(
            user_id=int(user_id),
            delta=0,
            balance_after=int(balance_after),
            reason=reason[:64],
            note=note[:2000],
            credit_type=credit_type,
        )
    )


def _monthly_bonus_buckets(db: Session, user_id: int, *, statuses: tuple[str, ...] | None = None):
    q = db.query(CreditLedgerEntry).filter(
        CreditLedgerEntry.user_id == int(user_id),
        CreditLedgerEntry.source_type.in_(tuple(MONTHLY_BONUS_SOURCES)),
        CreditLedgerEntry.remaining_amount > 0,
    )
    if statuses:
        q = q.filter(CreditLedgerEntry.status.in_(statuses))
    return q.all()


def sum_monthly_bonus_remaining(db: Session, user_id: int, *, status: str = BUCKET_ACTIVE) -> int:
    rows = _monthly_bonus_buckets(db, user_id, statuses=(status,))
    return sum(int(r.remaining_amount or 0) for r in rows)


def sum_locked_monthly_bonus(db: Session, user_id: int) -> int:
    return sum_monthly_bonus_remaining(db, user_id, status=BUCKET_LOCKED)


def sum_purchased_remaining(db: Session, user_id: int) -> int:
    now = _utc_now()
    rows = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.source_type == "purchased",
            CreditLedgerEntry.status == BUCKET_ACTIVE,
            CreditLedgerEntry.remaining_amount > 0,
        )
        .all()
    )
    total = 0
    for row in rows:
        exp = _aware(row.expired_at)
        if exp is not None and exp <= now:
            continue
        total += int(row.remaining_amount or 0)
    return total


def expire_stale_buckets(db: Session, user_id: int) -> int:
    """Mark purchased/trial/promo buckets past expired_at as expired."""
    now = _utc_now()
    rows = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.status == BUCKET_ACTIVE,
            CreditLedgerEntry.remaining_amount > 0,
            CreditLedgerEntry.expired_at.isnot(None),
        )
        .all()
    )
    expired_count = 0
    expired_amount = 0
    for row in rows:
        exp = _aware(row.expired_at)
        if exp is None or exp > now:
            continue
        amt = int(row.remaining_amount or 0)
        row.remaining_amount = 0
        row.status = BUCKET_EXPIRED
        expired_count += 1
        expired_amount += amt
    if expired_count:
        balance = _sync_user_balance(db, _user_query_for_update(db, user_id).one())
        _append_ledger_event(
            db,
            user_id=user_id,
            reason="credit_bucket_expired",
            note=f"expired_buckets={expired_count} amount={expired_amount}",
            balance_after=balance,
        )
    return expired_count


def lock_monthly_bonus_credits(db: Session, user_id: int) -> int:
    """Lock monthly bonus when subscription inactive."""
    now = _utc_now()
    rows = _monthly_bonus_buckets(db, user_id, statuses=(BUCKET_ACTIVE,))
    locked_amount = 0
    for row in rows:
        locked_amount += int(row.remaining_amount or 0)
        row.status = BUCKET_LOCKED
        row.locked_at = now
    if locked_amount > 0:
        balance = get_available_balance(db, user_id, sync=True)
        _append_ledger_event(
            db,
            user_id=user_id,
            reason="monthly_bonus_locked",
            note=f"locked_amount={locked_amount} reason=subscription_inactive",
            balance_after=balance,
            credit_type="monthly_bonus",
        )
        logger.info("monthly_bonus_locked user_id=%s amount=%s", user_id, locked_amount)
    return locked_amount


def unlock_monthly_bonus_credits(db: Session, user_id: int) -> int:
    """Restore locked monthly bonus when subscription active again."""
    rows = _monthly_bonus_buckets(db, user_id, statuses=(BUCKET_LOCKED,))
    unlocked = 0
    for row in rows:
        unlocked += int(row.remaining_amount or 0)
        row.status = BUCKET_ACTIVE
        row.locked_at = None
    if unlocked > 0:
        balance = get_available_balance(db, user_id, sync=True)
        _append_ledger_event(
            db,
            user_id=user_id,
            reason="monthly_bonus_unlocked",
            note=f"unlocked_amount={unlocked}",
            balance_after=balance,
            credit_type="monthly_bonus",
        )
        logger.info("monthly_bonus_unlocked user_id=%s amount=%s", user_id, unlocked)
    return unlocked


def sync_subscription_credit_locks(db: Session, user_id: int) -> str:
    """Lock or unlock monthly bonus based on active subscription."""
    expire_stale_buckets(db, user_id)
    sub = subscription_service.get_active_subscription(db, user_id)
    if sub is not None:
        unlock_monthly_bonus_credits(db, user_id)
        return "unlocked"
    lock_monthly_bonus_credits(db, user_id)
    return "locked"


def _grant_already_for_order(db: Session, user_id: int, order_id: int) -> bool:
    marker = f"order_id={int(order_id)}"
    hit = (
        db.query(CreditLedgerEntry.id)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.source_type.in_(tuple(MONTHLY_BONUS_SOURCES)),
            CreditLedgerEntry.note.contains(marker),
        )
        .first()
    )
    return hit is not None


def grant_plan_cycle_credits_for_order(
    db: Session,
    *,
    user_id: int,
    plan_slug: str,
    order_id: int,
    billing_cycle: str,
) -> dict[str, Any]:
    """
    Grant plan credits on payment/renewal.
    - monthly: 1× monthly grant (cap applies)
    - semi_annual: 7× monthly (6 base + 1 bonus)
    - yearly: 14× monthly (12 base + 2 bonus)
    """
    cycle = str(billing_cycle or "monthly").strip().lower()
    if cycle not in ("semi_annual", "yearly"):
        return grant_monthly_bonus_for_order(
            db,
            user_id=user_id,
            plan_slug=plan_slug,
            order_id=order_id,
        )

    slug = str(plan_slug or "").strip().lower()
    from app.services.saas_hybrid_pricing import plan_cycle_credit_breakdown

    breakdown = plan_cycle_credit_breakdown(slug, cycle)
    total = int(breakdown.get("total_credit") or 0)
    if total <= 0:
        return {
            "granted": 0,
            "skipped": True,
            "reason": "no_monthly_grant",
            "order_id": int(order_id),
            "credit_balance": get_available_balance(db, user_id),
        }

    if _grant_already_for_order(db, user_id, order_id):
        bal = get_available_balance(db, user_id)
        out: dict[str, Any] = {
            "granted": 0,
            "skipped": True,
            "reason": "already_granted_for_order",
            "order_id": int(order_id),
            "credit_balance": bal,
            "base_credit": breakdown["base_credit"],
            "bonus_credit": breakdown["bonus_credit"],
            "total_credit": total,
        }
        if cycle == "yearly":
            out.update({
                "base_duration_months": breakdown.get("base_duration_months"),
                "bonus_duration_months": breakdown.get("bonus_duration_months"),
                "total_duration_months": breakdown.get("total_duration_months"),
            })
        return out

    sync_subscription_credit_locks(db, user_id)
    if cycle == "yearly":
        note = (
            f"order_id={int(order_id)} plan={slug} billing_cycle=yearly "
            f"base_duration_months={breakdown.get('base_duration_months')} "
            f"bonus_duration_months={breakdown.get('bonus_duration_months')} "
            f"total_duration_months={breakdown.get('total_duration_months')} "
            f"base_credit={breakdown['base_credit']} bonus_credit={breakdown['bonus_credit']} "
            f"total_credit={total}"
        )
        reason = "yearly_plan_credit"
    else:
        note = (
            f"order_id={int(order_id)} plan={slug} billing_cycle=semi_annual "
            f"base_credit={breakdown['base_credit']} bonus_credit={breakdown['bonus_credit']} "
            f"total_credit={total}"
        )
        reason = "semi_annual_plan_credit"

    balance = grant_credits(
        db,
        user_id=int(user_id),
        amount=total,
        reason=reason,
        source_type="monthly_bonus",
        note=note,
        expired_at=None,
    )
    result: dict[str, Any] = {
        "granted": total,
        "skipped": False,
        "plan_slug": slug,
        "billing_cycle": cycle,
        "monthly_credit": breakdown["monthly_credit"],
        "base_credit": breakdown["base_credit"],
        "bonus_credit": breakdown["bonus_credit"],
        "total_credit": total,
        "credit_balance": balance,
        "order_id": int(order_id),
    }
    if cycle == "yearly":
        result.update({
            "base_duration_months": breakdown.get("base_duration_months"),
            "bonus_duration_months": breakdown.get("bonus_duration_months"),
            "total_duration_months": breakdown.get("total_duration_months"),
        })
    return result


def grant_admin_plan_cycle_credits(
    db: Session,
    *,
    user_id: int,
    plan_slug: str,
    billing_cycle: str,
    note: str,
) -> dict[str, Any]:
    """Admin manual grant — semi_annual/yearly multi-month; monthly adds 1× without cap."""
    cycle = str(billing_cycle or "monthly").strip().lower()
    slug = str(plan_slug or "").strip().lower()
    from app.services.saas_hybrid_pricing import plan_cycle_credit_breakdown

    if cycle in ("semi_annual", "yearly"):
        breakdown = plan_cycle_credit_breakdown(slug, cycle)
        amount = int(breakdown.get("total_credit") or 0)
        if amount <= 0:
            return {"granted": 0, "skipped": True, "reason": "no_grant"}
        sync_subscription_credit_locks(db, user_id)
        balance = grant_credits(
            db,
            user_id=int(user_id),
            amount=amount,
            reason=f"admin_{cycle}_plan_credit",
            source_type="monthly_bonus",
            note=note[:2000],
            expired_at=None,
        )
        out: dict[str, Any] = {
            "granted": amount,
            "base_credit": breakdown["base_credit"],
            "bonus_credit": breakdown["bonus_credit"],
            "total_credit": amount,
            "credit_balance": balance,
            "billing_cycle": cycle,
        }
        if cycle == "yearly":
            out.update({
                "base_duration_months": breakdown.get("base_duration_months"),
                "bonus_duration_months": breakdown.get("bonus_duration_months"),
                "total_duration_months": breakdown.get("total_duration_months"),
            })
        return out

    monthly = monthly_grant_for_plan(slug)
    if monthly <= 0:
        return {"granted": 0, "skipped": True, "reason": "no_grant"}
    sync_subscription_credit_locks(db, user_id)
    balance = grant_credits(
        db,
        user_id=int(user_id),
        amount=monthly,
        reason="admin_plan_credit",
        source_type="monthly_bonus",
        note=note[:2000],
        expired_at=None,
    )
    return {"granted": monthly, "credit_balance": balance, "billing_cycle": cycle}


def grant_monthly_bonus_for_order(
    db: Session,
    *,
    user_id: int,
    plan_slug: str,
    order_id: int,
) -> dict[str, Any]:
    """
    Idempotent monthly bonus on plan payment/renewal.
    Respects accumulation cap (2 cycles by default). No calendar expiry on bonus.
    """
    slug = str(plan_slug or "").strip().lower()
    if _grant_already_for_order(db, user_id, order_id):
        bal = get_available_balance(db, user_id)
        return {
            "granted": 0,
            "skipped": True,
            "reason": "already_granted_for_order",
            "order_id": int(order_id),
            "credit_balance": bal,
        }

    monthly = monthly_grant_for_plan(slug)
    cap = accumulation_cap_for_plan(slug)
    if monthly <= 0:
        return {
            "granted": 0,
            "skipped": True,
            "reason": "no_monthly_grant",
            "order_id": int(order_id),
            "credit_balance": get_available_balance(db, user_id),
        }

    sync_subscription_credit_locks(db, user_id)
    current_active = sum_monthly_bonus_remaining(db, user_id, status=BUCKET_ACTIVE)
    room = max(0, cap - current_active)
    amount = min(monthly, room)
    if amount <= 0:
        return {
            "granted": 0,
            "skipped": True,
            "reason": "at_accumulation_cap",
            "cap": cap,
            "current_active": current_active,
            "order_id": int(order_id),
            "credit_balance": get_available_balance(db, user_id),
        }

    note = f"order_id={int(order_id)} plan={slug} monthly_grant={monthly} cap={cap}"
    balance = grant_credits(
        db,
        user_id=int(user_id),
        amount=amount,
        reason="monthly_bonus_grant",
        source_type="monthly_bonus",
        note=note,
        expired_at=None,
    )
    return {
        "granted": amount,
        "skipped": False,
        "cap": cap,
        "monthly_grant": monthly,
        "credit_balance": balance,
        "order_id": int(order_id),
        "plan_slug": slug,
    }


def renewal_grant_preview(db: Session, user_id: int, plan_slug: str | None) -> dict[str, Any]:
    """Credit user will receive on next renewal (for billing UI)."""
    slug = str(plan_slug or "").strip().lower()
    if not slug:
        return {"amount": 0, "monthly_grant": 0, "cap": 0}
    monthly = monthly_grant_for_plan(slug)
    cap = accumulation_cap_for_plan(slug)
    locked = sum_locked_monthly_bonus(db, user_id)
    active = sum_monthly_bonus_remaining(db, user_id, status=BUCKET_ACTIVE)
    room = max(0, cap - active)
    return {
        "amount": min(monthly, room),
        "monthly_grant": monthly,
        "cap": cap,
        "locked_monthly_bonus": locked,
        "active_monthly_bonus": active,
    }


def credit_wallet_breakdown(db: Session, user_id: int, *, plan_slug: str | None = None) -> dict[str, Any]:
    """User-facing credit buckets for billing UI."""
    sync_subscription_credit_locks(db, user_id)
    now = _utc_now()
    available = get_available_balance(db, user_id, sync=False)
    locked = sum_locked_monthly_bonus(db, user_id)
    purchased = sum_purchased_remaining(db, user_id)

    expiring_soon: list[dict[str, Any]] = []
    horizon_days = 30
    rows = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.status == BUCKET_ACTIVE,
            CreditLedgerEntry.remaining_amount > 0,
            CreditLedgerEntry.expired_at.isnot(None),
        )
        .order_by(CreditLedgerEntry.expired_at.asc())
        .limit(20)
        .all()
    )
    for row in rows:
        exp = _aware(row.expired_at)
        if exp is None or exp <= now:
            continue
        days_left = max(0, (exp - now).days)
        if days_left > horizon_days:
            continue
        expiring_soon.append(
            {
                "amount": int(row.remaining_amount or 0),
                "source_type": str(row.source_type or ""),
                "expired_at": exp,
                "days_left": days_left,
            }
        )

    sub = subscription_service.get_active_subscription(db, user_id)
    has_sub = sub is not None
    preview = renewal_grant_preview(db, user_id, plan_slug)

    locked_message = None
    if locked > 0 and not has_sub:
        locked_message = (
            f"Bạn còn {locked:,} credit đang bị khóa. "
            "Gia hạn để sử dụng tiếp và nhận thêm credit tháng mới."
        ).replace(",", ".")

    return {
        "available_credit": available,
        "locked_credit": locked,
        "purchased_credit": purchased,
        "credit_expiring_soon": expiring_soon,
        "renewal_grant_preview": preview,
        "has_active_subscription": has_sub,
        "locked_message": locked_message,
        "policy": policy_snapshot(),
    }
