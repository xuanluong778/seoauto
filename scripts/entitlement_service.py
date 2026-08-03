"""SaaS entitlement checks (Phase 1 — enforcement off by default)."""

from __future__ import annotations

import os

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.saas import EntitlementResult
from app.services import credits as credits_svc
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.rbac import can_write, is_admin, normalize_role
from app.services.user_api_access import api_access_enabled_for
from app.services.user_trial_service import trial_status_snapshot


def is_saas_enforcement_enabled() -> bool:
    return os.getenv("SAAS_ENFORCEMENT", "0").strip().lower() in ("1", "true", "yes", "on")


def resolve_effective_plan(db: Session, user: User) -> str | None:
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return None
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    return plan.slug if plan else None


def _credit_cost_for_feature(feature_key: str, quantity: int = 1) -> int:
    q = max(1, int(quantity))
    per = {
        "keyword_research": credits_svc.cost_research_run,
        "technical_audit": credits_svc.cost_technical_analyze,
        "seo_score": credits_svc.cost_url_seo_scoreboard,
        "content_ai_article": lambda: credits_svc._int_env("CREDIT_COST_CONTENT_AI_ARTICLE", 5),
        "content_ai_bulk_article": lambda: credits_svc._int_env("CREDIT_COST_CONTENT_AI_BULK_ARTICLE", 5),
        "keyword_cluster": credits_svc.cost_cluster_sync,
    }.get(feature_key)
    if per is None:
        return credits_svc._int_env(f"CREDIT_COST_{feature_key.upper()}", 0) * q
    unit = per() if callable(per) else int(per)
    return max(0, unit) * q


def _subscription_allows(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int,
) -> EntitlementResult | None:
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return None

    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    if plan is None:
        return None

    limit_row = plan_service.get_limit_for_feature(db, plan.id, feature_key)
    if limit_row is None:
        return EntitlementResult(
            allowed=True,
            reason_code="subscription",
            message="Gói đang active — không có giới hạn riêng cho tính năng này.",
            plan_slug=plan.slug,
            subscription_id=sub.id,
            quota_remaining=None,
            feature_key=feature_key,
        )

    limit_val = int(limit_row.limit_value)
    if limit_val == -1:
        return EntitlementResult(
            allowed=True,
            reason_code="subscription",
            message="Gói đang active — không giới hạn tính năng này.",
            plan_slug=plan.slug,
            subscription_id=sub.id,
            quota_remaining=None,
            feature_key=feature_key,
        )

    if limit_val == 0 and bool(limit_row.is_hard_limit):
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Tính năng không có trong gói hiện tại.",
            plan_slug=plan.slug,
            subscription_id=sub.id,
            quota_remaining=0,
            feature_key=feature_key,
        )

    remaining = usage_tracking_service.get_quota_remaining(
        db, user.id, feature_key, plan_id=plan.id
    )
    need = max(1, int(quantity))
    if remaining is not None and remaining < need:
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Đã hết quota tháng cho tính năng này.",
            plan_slug=plan.slug,
            subscription_id=sub.id,
            quota_remaining=remaining,
            feature_key=feature_key,
        )

    return EntitlementResult(
        allowed=True,
        reason_code="subscription",
        message="Gói đang active — còn quota.",
        plan_slug=plan.slug,
        subscription_id=sub.id,
        quota_remaining=remaining,
        feature_key=feature_key,
    )


def check_feature(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int = 1,
) -> EntitlementResult:
    feature_key = str(feature_key or "").strip()
    if not feature_key:
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Thiếu feature_key.",
            feature_key="",
        )

    if not is_saas_enforcement_enabled():
        return EntitlementResult(
            allowed=True,
            reason_code="legacy_enforcement_off",
            message="SAAS_ENFORCEMENT tắt — giữ hành vi legacy (trial / API / credits).",
            plan_slug=resolve_effective_plan(db, user),
            subscription_id=(
                sub.id
                if (sub := subscription_service.get_active_subscription(db, user.id))
                else None
            ),
            quota_remaining=None,
            feature_key=feature_key,
        )

    if not can_write(user):
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Tài khoản chỉ xem — không có quyền tạo nội dung.",
            feature_key=feature_key,
        )

    if is_admin(user):
        return EntitlementResult(
            allowed=True,
            reason_code="admin",
            message="Tài khoản admin — cho phép đầy đủ.",
            plan_slug=resolve_effective_plan(db, user),
            feature_key=feature_key,
        )

    sub_result = _subscription_allows(db, user, feature_key, quantity)
    if sub_result is not None and sub_result.allowed:
        return sub_result
    if sub_result is not None and not sub_result.allowed:
        return sub_result

    if api_access_enabled_for(user):
        return EntitlementResult(
            allowed=True,
            reason_code="api_access",
            message="Admin đã cấp quyền API — legacy bypass.",
            plan_slug=resolve_effective_plan(db, user),
            feature_key=feature_key,
        )

    snap = trial_status_snapshot(
        db, user.id, role=normalize_role(getattr(user, "role", None))
    )
    if snap.get("is_active"):
        return EntitlementResult(
            allowed=True,
            reason_code="trial",
            message=str(snap.get("message") or "Trial còn hiệu lực."),
            plan_slug=resolve_effective_plan(db, user) or "free_trial",
            feature_key=feature_key,
        )

    if credits_svc.credits_enforced():
        cost = _credit_cost_for_feature(feature_key, quantity)
        if cost <= 0:
            return EntitlementResult(
                allowed=True,
                reason_code="credits",
                message="Credit enforcement bật — tính năng không trừ credit.",
                feature_key=feature_key,
            )
        balance = int(getattr(user, "credit_balance", 0) or 0)
        if balance >= cost:
            return EntitlementResult(
                allowed=True,
                reason_code="credits",
                message=f"Đủ credit ({balance} >= {cost}).",
                quota_remaining=balance - cost,
                feature_key=feature_key,
            )
        return EntitlementResult(
            allowed=False,
            reason_code="denied",
            message="Không đủ credit.",
            quota_remaining=balance,
            feature_key=feature_key,
        )

    msg = (
        sub_result.message
        if sub_result is not None
        else "Không có gói, trial, API access hoặc credit phù hợp."
    )
    return EntitlementResult(
        allowed=False,
        reason_code="denied",
        message=msg,
        plan_slug=resolve_effective_plan(db, user),
        subscription_id=sub_result.subscription_id if sub_result else None,
        quota_remaining=sub_result.quota_remaining if sub_result else None,
        feature_key=feature_key,
    )


def assert_feature_allowed(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int = 1,
) -> EntitlementResult:
    result = check_feature(db, user, feature_key, quantity=quantity)
    if result.allowed:
        return result

    status_code = status.HTTP_403_FORBIDDEN
    if result.reason_code == "denied" and credits_svc.credits_enforced():
        cost = _credit_cost_for_feature(feature_key, quantity)
        balance = int(getattr(user, "credit_balance", 0) or 0)
        if cost > 0 and balance < cost:
            status_code = status.HTTP_402_PAYMENT_REQUIRED

    raise HTTPException(
        status_code=status_code,
        detail={
            "code": result.reason_code,
            "message": result.message,
            "feature_key": result.feature_key,
            "plan_slug": result.plan_slug,
            "subscription_id": result.subscription_id,
            "quota_remaining": result.quota_remaining,
        },
    )
