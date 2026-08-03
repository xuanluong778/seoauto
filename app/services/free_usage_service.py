"""Admin-gifted free usage days — platform access without bundled credits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_free_usage_expires_at(user: User) -> datetime | None:
    return _aware(getattr(user, "free_usage_expires_at", None))


def has_active_free_usage(db: Session, user_id: int) -> bool:
    user = db.get(User, int(user_id))
    if user is None:
        return False
    end = get_free_usage_expires_at(user)
    if end is None:
        return False
    return end > _utc_now()


def free_usage_days_remaining(db: Session, user_id: int) -> int:
    user = db.get(User, int(user_id))
    if user is None:
        return 0
    end = get_free_usage_expires_at(user)
    if end is None:
        return 0
    now = _utc_now()
    if end <= now:
        return 0
    return max(0, (end.date() - now.date()).days)


def free_usage_plan_label(days: int) -> str:
    n = max(0, int(days))
    if n <= 0:
        return ""
    return f"Còn {n} ngày dùng phần mềm"


def free_usage_banner_message(days: int) -> str:
    return free_usage_plan_label(days)


def free_usage_need_credit_message(days: int) -> str:
    n = max(0, int(days))
    label = free_usage_plan_label(n)
    if not label:
        return "Vui lòng mua credit để sử dụng các tính năng."
    return f"{label}, vui lòng mua credit để sử dụng các tính năng."


def extend_free_usage_days(db: Session, user_id: int, days: int) -> tuple[datetime, datetime | None]:
    """Extend free_usage_expires_at from max(now, current expiry). Returns (new_end, previous_end)."""
    user = db.get(User, int(user_id))
    if user is None:
        raise ValueError("user_not_found")

    gift_days = max(1, int(days))
    now = _utc_now()
    previous = get_free_usage_expires_at(user)
    base = previous if previous and previous > now else now
    new_end = base + timedelta(days=gift_days)
    user.free_usage_expires_at = new_end
    db.flush()
    return new_end, previous


def free_usage_snapshot(db: Session, user: User, *, credit_balance: int | None = None) -> dict[str, Any]:
    days = free_usage_days_remaining(db, user.id)
    active = days > 0
    balance = int(credit_balance if credit_balance is not None else getattr(user, "credit_balance", 0) or 0)
    banner = free_usage_banner_message(days) if active else None
    return {
        "free_usage_active": active,
        "free_usage_days_remaining": days,
        "free_usage_expires_at": get_free_usage_expires_at(user),
        "free_usage_banner": banner,
        "needs_credit_for_features": bool(active and balance <= 0),
        "free_usage_need_credit_message": free_usage_need_credit_message(days) if active else None,
    }
