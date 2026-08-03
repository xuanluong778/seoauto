"""Plan quota enforcement helpers — subscription quota + credit (không thay thế nhau)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import subscription_service, usage_tracking_service
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.entitlement_service import resolve_effective_plan
from app.services.plan_quota_registry import (
    FEATURE_KEY_LABELS_VI,
    FEATURE_LABELS_VI,
    PLAN_DISPLAY_NAMES,
    PLAN_FEATURES,
    feature_key_for,
    monthly_quota,
    plan_feature,
)
from app.services.rbac import is_admin


def quota_exceeded_detail(
    *,
    feature_key: str,
    plan_slug: str | None = None,
    remaining: int | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    label = FEATURE_KEY_LABELS_VI.get(feature_key, feature_key)
    plan_name = PLAN_DISPLAY_NAMES.get(str(plan_slug or ""), plan_slug or "hiện tại")
    msg = message or f"Đã hết quota tháng cho «{label}» (gói {plan_name})."
    return {
        "code": "quota_exceeded",
        "message": msg,
        "feature_key": feature_key,
        "plan_slug": plan_slug,
        "quota_remaining": remaining,
        "upgrade_required": True,
        "upgrade_url": "/pricing",
        "addon_url": "/account-billing",
    }


def plan_required_detail(
    *,
    feature: str,
    message: str,
    min_plan: str = "pro",
) -> dict[str, Any]:
    return {
        "code": "plan_required",
        "message": message,
        "feature": feature,
        "min_plan_slug": min_plan,
        "upgrade_required": True,
        "upgrade_url": "/pricing",
    }


def assert_quota_available(
    db: Session,
    user: User,
    feature_key: str,
    *,
    units: int = 1,
) -> int | None:
    """
    Kiểm tra quota tháng theo gói đang active.
    None = không có giới hạn (admin / chưa có row limit / unlimited).
    """
    if is_admin(user):
        return None

    remaining = usage_tracking_service.get_quota_remaining(db, user.id, feature_key)
    if remaining is None:
        return None

    need = max(1, int(units))
    if int(remaining) < need:
        plan_slug = resolve_effective_plan(db, user) or resolve_cau_ai_plan_slug(db, user)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=quota_exceeded_detail(
                feature_key=feature_key,
                plan_slug=plan_slug,
                remaining=int(remaining),
            ),
        )
    return int(remaining)


def record_quota_usage(
    db: Session,
    user_id: int,
    feature_key: str,
    *,
    quantity: int = 1,
    credits_used: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Ghi usage sau khi thao tác thành công."""
    usage_tracking_service.record_successful_usage(
        db,
        user_id,
        feature_key,
        quantity=quantity,
        credits_used=credits_used,
        metadata=metadata,
    )


def assert_plan_capability(
    db: Session,
    user: User,
    capability: str,
    *,
    min_plan_slug: str = "pro",
    message: str | None = None,
) -> str | None:
    """Raise 403 nếu gói không có capability (vd. google_map_seo trên Basic)."""
    if is_admin(user):
        return "admin"
    plan_slug = resolve_cau_ai_plan_slug(db, user)
    if not plan_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=plan_required_detail(
                feature=capability,
                message=message or "Tính năng này yêu cầu gói trả phí. Nâng cấp tại /pricing.",
            ),
        )
    if not plan_feature(plan_slug, capability, False):
        min_name = PLAN_DISPLAY_NAMES.get(min_plan_slug, min_plan_slug)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=plan_required_detail(
                feature=capability,
                min_plan=min_plan_slug,
                message=message or f"Tính năng này cần gói {min_name} trở lên.",
            ),
        )
    return plan_slug


def assert_google_map_location_capacity(
    db: Session,
    user: User,
    *,
    current_count: int,
    adding: int = 1,
) -> str | None:
    """Kiểm tra số location Google Map theo gói."""
    plan_slug = assert_plan_capability(
        db,
        user,
        "google_map_seo",
        min_plan_slug="pro",
        message="Google Map SEO chỉ có từ gói Pro trở lên. Basic ưu tiên BYOK cho Content AI.",
    )
    cap = monthly_quota(str(plan_slug), "google_map_location")
    if cap <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=plan_required_detail(
                feature="google_map_seo",
                min_plan="pro",
                message="Gói hiện tại không hỗ trợ Google Map location.",
            ),
        )
    if int(current_count) + int(adding) > cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=quota_exceeded_detail(
                feature_key=feature_key_for("google_map_location"),
                plan_slug=plan_slug,
                remaining=max(0, cap - int(current_count)),
                message=f"Đã đạt giới hạn {cap} chi nhánh Google Map (gói {PLAN_DISPLAY_NAMES.get(plan_slug or '', plan_slug)}).",
            ),
        )
    return plan_slug


def user_quota_snapshot(db: Session, user: User) -> dict[str, Any]:
    """Tóm tắt quota chuẩn hóa cho UI."""
    from app.services.plan_quota_registry import catalog_for_api, lead_scanner_limits

    plan_slug = resolve_effective_plan(db, user) or resolve_cau_ai_plan_slug(db, user)
    sub = subscription_service.get_active_subscription(db, user.id)
    items: list[dict[str, Any]] = []
    if plan_slug and plan_slug in PLAN_FEATURES:
        for qkey, fk in (
            ("projects", feature_key_for("projects")),
            ("ai_articles", feature_key_for("ai_articles")),
            ("technical_audit", feature_key_for("technical_audit")),
            ("seo_score", feature_key_for("seo_score")),
            ("keyword_research", feature_key_for("keyword_research")),
            ("lead_scan", feature_key_for("lead_scan")),
            ("lead_detail", feature_key_for("lead_detail")),
            ("chatbot_reply", feature_key_for("chatbot_reply")),
            ("google_map_location", feature_key_for("google_map_location")),
            ("team_members", feature_key_for("team_members")),
        ):
            used = usage_tracking_service.get_monthly_usage(db, user.id, fk)
            remaining = usage_tracking_service.get_quota_remaining(
                db, user.id, fk, plan_id=sub.plan_id if sub else None
            )
            limit = monthly_quota(plan_slug, qkey)
            items.append({
                "key": qkey,
                "feature_key": fk,
                "label": FEATURE_LABELS_VI.get(qkey, qkey),
                "limit": limit,
                "used": used,
                "remaining": remaining,
            })
    return {
        "plan_slug": plan_slug,
        "plan_name": PLAN_DISPLAY_NAMES.get(str(plan_slug or ""), plan_slug),
        "quotas": items,
        "lead_scanner": lead_scanner_limits(plan_slug) if plan_slug else None,
        "features": PLAN_FEATURES.get(str(plan_slug or ""), {}),
        "catalog": catalog_for_api(),
    }
