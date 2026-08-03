"""SaaS subscriptions — manual grant / active lookup (Phase 1)."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription
from app.schemas.saas import PlanResponse, SubscriptionResponse, UsageLimitResponse, UserPlanSnapshot
from app.services import plan_service

ACTIVE_STATUSES = frozenset({"trialing", "active"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + int(months)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def is_subscription_active(sub: Subscription, *, now: datetime | None = None) -> bool:
    now = now or _utc_now()
    if sub.status not in ACTIVE_STATUSES:
        return False
    period_end = _aware(sub.current_period_end)
    if period_end is None or period_end <= now:
        return False
    ended = _aware(sub.ended_at)
    if ended is not None and ended <= now:
        return False
    return True


def _expire_subscription_row(sub: Subscription, *, now: datetime) -> None:
    sub.status = "expired"
    sub.ended_at = now


def expire_active_subscriptions_for_user(db: Session, user_id: int, *, now: datetime | None = None) -> int:
    """Close all still-active subscriptions for user. Returns count expired."""
    now = now or _utc_now()
    count = 0
    for sub in db.query(Subscription).filter(Subscription.user_id == int(user_id)).all():
        if is_subscription_active(sub, now=now):
            _expire_subscription_row(sub, now=now)
            count += 1
    return count


def get_active_subscription(db: Session, user_id: int) -> Subscription | None:
    now = _utc_now()
    candidates = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == int(user_id),
            Subscription.status.in_(tuple(ACTIVE_STATUSES)),
        )
        .order_by(Subscription.current_period_end.desc(), Subscription.id.desc())
        .all()
    )
    for sub in candidates:
        if is_subscription_active(sub, now=now):
            return sub
    return None


def create_subscription(
    db: Session,
    user_id: int,
    plan_id: int,
    *,
    months: int = 1,
    status: str = "active",
    source: str = "manual",
    notes: str | None = None,
) -> Subscription:
    plan = plan_service.get_plan_by_id(db, plan_id)
    if plan is None:
        raise ValueError(f"Plan id={plan_id} not found")

    status_norm = str(status or "active").strip().lower()
    if status_norm not in ACTIVE_STATUSES:
        raise ValueError(f"Invalid subscription status: {status}")

    now = _utc_now()
    expire_active_subscriptions_for_user(db, user_id, now=now)

    period_end = _add_months(now, max(1, int(months)))
    sub = Subscription(
        user_id=int(user_id),
        plan_id=int(plan_id),
        status=status_norm,
        started_at=now,
        current_period_start=now,
        current_period_end=period_end,
        source=(source or "manual")[:32],
        notes=(notes or "")[:2000] or None,
    )
    db.add(sub)
    db.flush()
    return sub


def expire_subscription(db: Session, subscription_id: int) -> Subscription | None:
    sub = db.query(Subscription).filter(Subscription.id == int(subscription_id)).one_or_none()
    if sub is None:
        return None
    _expire_subscription_row(sub, now=_utc_now())
    db.flush()
    return sub


def subscription_to_response(db: Session, sub: Subscription) -> SubscriptionResponse:
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    return SubscriptionResponse(
        id=sub.id,
        user_id=sub.user_id,
        plan_id=sub.plan_id,
        status=sub.status,
        started_at=sub.started_at,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=bool(sub.cancel_at_period_end),
        cancelled_at=sub.cancelled_at,
        ended_at=sub.ended_at,
        source=sub.source,
        notes=sub.notes,
        plan_slug=plan.slug if plan else None,
        plan_name=plan.name if plan else None,
    )


def user_plan_snapshot(db: Session, user_id: int) -> UserPlanSnapshot:
    sub = get_active_subscription(db, user_id)
    plan: Plan | None = None
    if sub is not None:
        plan = plan_service.get_plan_with_limits(db, sub.plan_id)

    plan_resp: PlanResponse | None = None
    if plan is not None:
        plan_resp = PlanResponse(
            id=plan.id,
            slug=plan.slug,
            name=plan.name,
            description=plan.description,
            price_amount=plan.price_amount,
            currency=plan.currency,
            billing_cycle=plan.billing_cycle,
            is_active=plan.is_active,
            is_public=plan.is_public,
            sort_order=plan.sort_order,
            usage_limits=[UsageLimitResponse.model_validate(ul) for ul in plan.usage_limits],
        )

    return UserPlanSnapshot(
        user_id=int(user_id),
        has_active_subscription=sub is not None,
        subscription=subscription_to_response(db, sub) if sub else None,
        plan=plan_resp,
        effective_plan_slug=plan.slug if plan else None,
    )
