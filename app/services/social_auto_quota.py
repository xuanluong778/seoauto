"""Social Auto monthly publish quota (social_auto / social_posts per plan)."""

from __future__ import annotations

import json
import os

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.rbac import is_admin

FEATURE_KEY = "social_auto"


def is_quota_enforced() -> bool:
    if str(os.getenv("SOCIAL_AUTO_QUOTA_ENFORCEMENT", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("SAAS_ENFORCEMENT", "0").strip().lower() in {"1", "true", "yes", "on"}


def _limit_from_plan_metadata(plan) -> int | None:
    raw = getattr(plan, "metadata_json", None) or ""
    if not raw:
        return None
    try:
        meta = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    compare = meta.get("compare") if isinstance(meta.get("compare"), dict) else {}
    val = compare.get("social_posts")
    if val is None:
        return None
    try:
        n = int(val)
    except (TypeError, ValueError):
        return None
    return None if n < 0 else n


def get_monthly_limit(db: Session, user: User) -> int | None:
    """None = unlimited; 0 = blocked unless admin."""
    if is_admin(user):
        return None
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return 0
    limit_row = plan_service.get_limit_for_feature(db, sub.plan_id, FEATURE_KEY)
    if limit_row is not None:
        val = int(limit_row.limit_value)
        return None if val == -1 else max(0, val)
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    if plan is None:
        return 0
    meta_limit = _limit_from_plan_metadata(plan)
    return meta_limit if meta_limit is not None else None


def get_monthly_used(db: Session, user_id: int) -> int:
    return usage_tracking_service.get_monthly_usage(db, user_id, FEATURE_KEY)


def get_quota_snapshot(db: Session, user: User) -> dict[str, int | None | bool]:
    limit = get_monthly_limit(db, user)
    used = get_monthly_used(db, user.id)
    remaining: int | None
    if limit is None:
        remaining = None
    else:
        remaining = max(0, int(limit) - used)
    return {
        "feature_key": FEATURE_KEY,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "unlimited": limit is None,
        "enforced": is_quota_enforced(),
    }


def assert_publish_allowed(db: Session, user: User, *, quantity: int = 1) -> None:
    if not is_quota_enforced() or is_admin(user):
        return
    limit = get_monthly_limit(db, user)
    if limit is None:
        return
    need = max(1, int(quantity))
    used = get_monthly_used(db, user.id)
    if used + need > int(limit):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Đã hết quota Social Auto tháng này ({used}/{limit} bài). Nâng cấp gói để tiếp tục.",
                "feature_key": FEATURE_KEY,
                "used": used,
                "limit": limit,
            },
        )


def record_publish_usage(db: Session, user: User, *, quantity: int = 1) -> None:
    if is_admin(user):
        return
    usage_tracking_service.record_successful_usage(
        db,
        user.id,
        FEATURE_KEY,
        quantity=max(1, int(quantity)),
    )
