"""Daily/monthly credit + provider cost caps and in-process concurrency."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.user import User
from app.services.rbac import is_admin


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def user_daily_credit_cap() -> int:
    return max(0, _int_env("COST_CONTROL_USER_DAILY_CREDIT_CAP", 5000))


def user_monthly_credit_cap() -> int:
    return max(0, _int_env("COST_CONTROL_USER_MONTHLY_CREDIT_CAP", 50000))


def dataforseo_user_daily_task_cap() -> int:
    return max(1, _int_env("COST_CONTROL_DATAFORSEO_DAILY_TASKS", 40))


def places_user_daily_cap() -> int:
    return max(1, _int_env("COST_CONTROL_PLACES_DAILY_CALLS", 80))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(now: datetime | None = None) -> datetime:
    ref = now or _utc_now()
    return ref.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime | None = None) -> datetime:
    ref = now or _utc_now()
    return ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _burn_credits(db: Session, user_id: int, *, since: datetime) -> int:
    total = (
        db.query(func.coalesce(func.sum(func.abs(CreditLedger.delta)), 0))
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.created_at >= since,
            CreditLedger.delta < 0,
        )
        .scalar()
    )
    return int(total or 0)


def _module_call_count(db: Session, user_id: int, module: str, *, since: datetime) -> int:
    return int(
        db.query(func.count(CreditLedger.id))
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.module == module,
            CreditLedger.created_at >= since,
            CreditLedger.delta < 0,
        )
        .scalar()
        or 0
    )


def assert_user_credit_caps(db: Session, user: User, *, extra_credits: int = 0) -> None:
    if is_admin(user):
        return
    daily_cap = user_daily_credit_cap()
    monthly_cap = user_monthly_credit_cap()
    extra = max(0, int(extra_credits or 0))
    if daily_cap > 0:
        used = _burn_credits(db, int(user.id), since=_day_start())
        if used + extra > daily_cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "daily_credit_cap",
                    "message": "Đã đạt giới hạn credit trong ngày. Thử lại vào ngày mai hoặc mua thêm pack.",
                    "used": used,
                    "cap": daily_cap,
                },
            )
    if monthly_cap > 0:
        used_m = _burn_credits(db, int(user.id), since=_month_start())
        if used_m + extra > monthly_cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "monthly_credit_cap",
                    "message": "Đã đạt giới hạn credit trong tháng.",
                    "used": used_m,
                    "cap": monthly_cap,
                },
            )


def assert_provider_daily_caps(db: Session, user: User, *, provider: str) -> None:
    if is_admin(user):
        return
    p = str(provider or "").strip().lower()
    since = _day_start()
    if p == "dataforseo":
        cap = dataforseo_user_daily_task_cap()
        used = _module_call_count(db, int(user.id), "keyword", since=since)
        if used >= cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "dataforseo_daily_cap",
                    "message": "Đã đạt hard cap DataForSEO trong ngày.",
                    "used": used,
                    "cap": cap,
                },
            )
    if p in ("google_places",):
        cap = places_user_daily_cap()
        used = _module_call_count(db, int(user.id), "lead_scanner", since=since)
        if used >= cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "places_daily_cap",
                    "message": "Đã đạt hard cap Google Places trong ngày.",
                    "used": used,
                    "cap": cap,
                },
            )
