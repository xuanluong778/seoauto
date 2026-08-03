"""SaaS usage events + monthly rollup (Phase 1 — call after success only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.monthly_usage import MonthlyUsage
from app.models.usage_event import UsageEvent
from app.services import plan_service, subscription_service


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_usage_month(*, dt: datetime | None = None) -> str:
    dt = dt or _utc_now()
    return dt.strftime("%Y-%m")


def get_monthly_usage(
    db: Session,
    user_id: int,
    feature_key: str,
    month: str | None = None,
) -> int:
    usage_month = month or current_usage_month()
    row = (
        db.query(MonthlyUsage)
        .filter(
            MonthlyUsage.user_id == int(user_id),
            MonthlyUsage.usage_month == usage_month,
            MonthlyUsage.feature_key == feature_key,
        )
        .one_or_none()
    )
    return int(row.quantity_used) if row else 0


def get_quota_remaining(
    db: Session,
    user_id: int,
    feature_key: str,
    plan_id: int | None = None,
) -> int | None:
    """
    Remaining quota for feature in current month.
    None = unlimited or no limit configured for plan.
    """
    if plan_id is None:
        sub = subscription_service.get_active_subscription(db, user_id)
        plan_id = sub.plan_id if sub else None
    if plan_id is None:
        return None

    limit_row = plan_service.get_limit_for_feature(db, plan_id, feature_key)
    if limit_row is None:
        return None
    if int(limit_row.limit_value) == -1:
        return None

    used = get_monthly_usage(db, user_id, feature_key)
    return max(0, int(limit_row.limit_value) - used)


def record_successful_usage(
    db: Session,
    user_id: int,
    feature_key: str,
    *,
    quantity: int = 1,
    subscription_id: int | None = None,
    plan_id: int | None = None,
    credits_used: int = 0,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    """
    Record a successful feature use: usage_events + monthly_usage upsert.
    Idempotent when idempotency_key is set and already exists.
    """
    qty = max(1, int(quantity))
    credits = max(0, int(credits_used))

    if idempotency_key:
        key = idempotency_key.strip()[:128]
        existing = (
            db.query(UsageEvent).filter(UsageEvent.idempotency_key == key).one_or_none()
        )
        if existing is not None:
            return existing

    if plan_id is None and subscription_id is not None:
        from app.models.subscription import Subscription

        sub = db.query(Subscription).filter(Subscription.id == int(subscription_id)).one_or_none()
        if sub is not None:
            plan_id = sub.plan_id

    if plan_id is None:
        sub = subscription_service.get_active_subscription(db, user_id)
        if sub is not None:
            subscription_id = subscription_id or sub.id
            plan_id = sub.plan_id

    usage_month = current_usage_month()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    event = UsageEvent(
        user_id=int(user_id),
        subscription_id=subscription_id,
        plan_id=plan_id,
        event_type="feature_usage",
        feature_key=feature_key,
        quantity=qty,
        credits_used=credits,
        status="success",
        idempotency_key=idempotency_key.strip()[:128] if idempotency_key else None,
        metadata_json=metadata_json,
    )
    db.add(event)
    db.flush()

    row = (
        db.query(MonthlyUsage)
        .filter(
            MonthlyUsage.user_id == int(user_id),
            MonthlyUsage.usage_month == usage_month,
            MonthlyUsage.feature_key == feature_key,
        )
        .one_or_none()
    )
    if row is None:
        row = MonthlyUsage(
            user_id=int(user_id),
            subscription_id=subscription_id,
            plan_id=plan_id,
            usage_month=usage_month,
            feature_key=feature_key,
            quantity_used=qty,
            credits_used=credits,
        )
        db.add(row)
    else:
        row.quantity_used = int(row.quantity_used) + qty
        row.credits_used = int(row.credits_used) + credits
        if subscription_id is not None:
            row.subscription_id = subscription_id
        if plan_id is not None:
            row.plan_id = plan_id

    db.flush()
    return event
