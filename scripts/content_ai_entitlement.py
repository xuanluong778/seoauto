"""Content AI SaaS entitlement helpers — usage snapshot, guards, event logging."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.saas import EntitlementResult
from app.services import entitlement_service, plan_service, subscription_service, usage_tracking_service
from app.services.rbac import is_admin
from app.services.user_api_access import api_access_enabled_for

# Widget feature keys (order preserved for UI)
WIDGET_FEATURES: tuple[tuple[str, str, str], ...] = (
    ("content_ai_article", "ai_articles", "Bài viết AI"),
    ("content_ai_brief", "content_briefs", "Content Brief"),
    ("image_generate", "ai_images", "Ảnh AI"),
    ("content_ai_bulk_article", "bulk_jobs", "Bulk job"),
    ("wp_publish", "wp_publish", "WordPress Publish"),
    ("content_auto_update_fetch", "cau_fetch", "Auto Update · Fetch"),
    ("content_auto_update_generate", "cau_generate", "Auto Update · AI"),
    ("content_auto_update_publish", "cau_publish", "Auto Update · Publish"),
    ("content_auto_update_restore", "cau_restore", "Auto Update · Restore"),
)

BRIEF_SUGGEST_FIELDS = frozenset(
    {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
        "outline",
        "outline_content",
        "target_website",
    }
)


def feature_for_suggest_field(field: str) -> str:
    f = (field or "").strip().lower()
    if f == "content":
        return "content_ai_article"
    return "content_ai_brief"


def bypass_entitlement(user: User) -> bool:
    """Admin and API-grant test accounts skip quota enforcement."""
    return is_admin(user) or api_access_enabled_for(user)


def _fallback_brief_limit(db: Session, plan_id: int) -> int | None:
    art = plan_service.get_limit_for_feature(db, plan_id, "content_ai_article")
    if art is None:
        return None
    val = int(art.limit_value)
    if val == -1:
        return -1
    if val <= 0:
        return val
    return val * 5


def resolve_plan_limit(db: Session, plan_id: int | None, feature_key: str) -> int | None:
    """
    Effective limit for display/enforcement.
    None = unlimited / not configured; -1 = unlimited explicit.
    """
    if plan_id is None:
        return None
    row = plan_service.get_limit_for_feature(db, plan_id, feature_key)
    if row is not None:
        return int(row.limit_value)
    if feature_key == "content_ai_brief":
        return _fallback_brief_limit(db, plan_id)
    return None


def _quota_item(
    db: Session,
    user_id: int,
    plan_id: int | None,
    feature_key: str,
    *,
    usage_month: str,
) -> dict[str, Any]:
    used = usage_tracking_service.get_monthly_usage(
        db, user_id, feature_key, month=usage_month
    )
    limit_val = resolve_plan_limit(db, plan_id, feature_key)
    remaining: int | None
    if limit_val is None or limit_val == -1:
        remaining = None
    else:
        remaining = max(0, int(limit_val) - used)
    pct: float | None = None
    if limit_val is not None and limit_val > 0:
        pct = min(100.0, round((used / limit_val) * 100, 1))
    return {
        "feature_key": feature_key,
        "quantity_used": used,
        "limit_value": limit_val,
        "quota_remaining": remaining,
        "usage_percent": pct,
        "is_unlimited": limit_val is None or limit_val == -1,
        "is_over_quota": limit_val is not None and limit_val >= 0 and used >= limit_val,
        "is_warning": pct is not None and pct >= 80,
    }


def build_content_ai_usage(db: Session, user: User) -> dict[str, Any]:
    usage_month = usage_tracking_service.current_usage_month()
    sub = subscription_service.get_active_subscription(db, user.id)
    plan_id = sub.plan_id if sub else None
    plan_slug: str | None = None
    plan_name: str | None = None
    if sub is not None:
        plan = plan_service.get_plan_by_id(db, sub.plan_id)
        if plan is not None:
            plan_slug = plan.slug
            plan_name = plan.name

    items: list[dict[str, Any]] = []
    widget: dict[str, dict[str, Any]] = {}
    for feature_key, widget_key, _label in WIDGET_FEATURES:
        row = _quota_item(db, user.id, plan_id, feature_key, usage_month=usage_month)
        items.append(row)
        widget[widget_key] = row

    any_warning = any(r.get("is_warning") for r in items)
    any_over = any(r.get("is_over_quota") for r in items)

    return {
        "user_id": int(user.id),
        "usage_month": usage_month,
        "plan_slug": plan_slug,
        "plan_name": plan_name,
        "enforcement_enabled": entitlement_service.is_saas_enforcement_enabled(),
        "bypass_entitlement": bypass_entitlement(user),
        "items": items,
        "widget": widget,
        "any_warning": any_warning,
        "any_over_quota": any_over,
    }


def _check_fallback_brief_quota(
    db: Session,
    user: User,
    quantity: int,
) -> EntitlementResult | None:
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return None
    if plan_service.get_limit_for_feature(db, sub.plan_id, "content_ai_brief") is not None:
        return None
    fb = _fallback_brief_limit(db, sub.plan_id)
    if fb is None or fb == -1:
        return None
    if fb == 0:
        plan = plan_service.get_plan_by_id(db, sub.plan_id)
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Tính năng không có trong gói hiện tại.",
            plan_slug=plan.slug if plan else None,
            subscription_id=sub.id,
            quota_remaining=0,
            feature_key="content_ai_brief",
        )
    used = usage_tracking_service.get_monthly_usage(db, user.id, "content_ai_brief")
    need = max(1, int(quantity))
    remaining = max(0, fb - used)
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    if remaining < need:
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Đã hết quota tháng cho Content Brief.",
            plan_slug=plan.slug if plan else None,
            subscription_id=sub.id,
            quota_remaining=remaining,
            feature_key="content_ai_brief",
        )
    return None


def check_content_ai_feature(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int = 1,
) -> EntitlementResult:
    if bypass_entitlement(user):
        return EntitlementResult(
            allowed=True,
            reason_code="bypass",
            message="Admin hoặc tài khoản test — bỏ qua quota.",
            plan_slug=entitlement_service.resolve_effective_plan(db, user),
            feature_key=feature_key,
        )
    result = entitlement_service.check_feature(db, user, feature_key, quantity=quantity)
    if not result.allowed:
        return result
    if feature_key == "content_ai_brief":
        brief_block = _check_fallback_brief_quota(db, user, quantity)
        if brief_block is not None:
            return brief_block
    return result


def raise_if_denied(result: EntitlementResult) -> None:
    if result.allowed:
        return
    code = "quota_exceeded"
    if result.reason_code not in ("denied",):
        code = result.reason_code
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": code,
            "message": result.message,
            "feature_key": result.feature_key,
            "plan_slug": result.plan_slug,
            "subscription_id": result.subscription_id,
            "quota_remaining": result.quota_remaining,
            "upgrade_required": True,
        },
    )


def assert_content_ai_feature(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int = 1,
) -> EntitlementResult:
    result = check_content_ai_feature(db, user, feature_key, quantity=quantity)
    raise_if_denied(result)
    return result


def record_content_ai_usage(
    db: Session,
    user: User,
    feature_key: str,
    *,
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> None:
    if bypass_entitlement(user):
        return
    sub = subscription_service.get_active_subscription(db, user.id)
    usage_tracking_service.record_successful_usage(
        db,
        user.id,
        feature_key,
        quantity=quantity,
        subscription_id=sub.id if sub else None,
        plan_id=sub.plan_id if sub else None,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )
