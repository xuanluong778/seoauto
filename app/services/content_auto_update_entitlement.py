"""Content Auto Update — SaaS quota feature keys."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.saas import EntitlementResult
from app.services.cau_ai_fix_entitlement import build_cau_ai_fix_snapshot
from app.services.content_ai_entitlement import (
    assert_content_ai_feature,
    build_content_ai_usage,
    check_content_ai_feature,
    record_content_ai_usage,
)

CAU_FEATURES: tuple[tuple[str, str], ...] = (
    ("content_auto_update_fetch", "Lấy bài WordPress"),
    ("content_auto_update_generate", "AI đề xuất SEO"),
    ("content_auto_update_publish", "Publish Auto Update"),
    ("content_auto_update_restore", "Restore Auto Update"),
)


def build_cau_quota_snapshot(db: Session, user: User) -> dict[str, Any]:
    """Quota snapshot cho Auto Update (4 feature keys)."""
    base = build_content_ai_usage(db, user)
    by_key = {row["feature_key"]: row for row in (base.get("items") or [])}
    items = []
    for key, label in CAU_FEATURES:
        row = by_key.get(key) or {
            "feature_key": key,
            "quantity_used": 0,
            "limit_value": None,
            "quota_remaining": None,
            "usage_percent": None,
            "is_unlimited": True,
            "is_over_quota": False,
            "is_warning": False,
        }
        items.append({**row, "label": label})
    any_over = any(r.get("is_over_quota") for r in items)
    ai_fix = build_cau_ai_fix_snapshot(db, user, quantity=1)
    return {
        "enforcement_enabled": bool(base.get("enforcement_enabled")),
        "bypass_entitlement": bool(base.get("bypass_entitlement")),
        "plan_slug": base.get("plan_slug"),
        "plan_name": base.get("plan_name"),
        "items": items,
        "any_over_quota": any_over,
        "ai_fix": ai_fix,
    }


def assert_cau_feature(db: Session, user: User, feature_key: str, quantity: int = 1) -> EntitlementResult:
    return assert_content_ai_feature(db, user, feature_key, quantity=quantity)


def check_cau_feature(db: Session, user: User, feature_key: str, quantity: int = 1) -> EntitlementResult:
    return check_content_ai_feature(db, user, feature_key, quantity=quantity)


def record_cau_usage(
    db: Session,
    user: User,
    feature_key: str,
    *,
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> None:
    record_content_ai_usage(
        db,
        user,
        feature_key,
        quantity=quantity,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )
