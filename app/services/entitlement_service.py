"""SaaS entitlement checks — subscription, trial, free usage, system AI."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.saas import EntitlementResult
from app.services import credits as credits_svc
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.free_usage_service import (
    free_usage_days_remaining,
    free_usage_need_credit_message,
    has_active_free_usage,
)
from app.services.saas_trial_service import (
    TRIAL_PLAN_SLUG,
    check_trial_feature_allowed,
    is_saas_trial_active,
)
from app.services.rbac import can_write, is_admin

_LEGACY_PAID_SLUGS = frozenset({"free_trial_5d"})


def is_saas_enforcement_enabled() -> bool:
    return os.getenv("SAAS_ENFORCEMENT", "0").strip().lower() in ("1", "true", "yes", "on")


def resolve_effective_plan(db: Session, user: User) -> str | None:
    """
    SSOT plan slug from active subscription (paid or trialing trial_3d).

    Priority for access is enforced by check_feature / resolve_effective_plan_state:
    paid active > free_usage > saas trial > none.
    Credits never imply a plan.
    """
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None:
        return None
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    return plan.slug if plan else None


def resolve_effective_plan_state(db: Session, user: User) -> dict[str, Any]:
    """
    Single source of truth for UI banners + permission messaging.

    Paid ACTIVE (non-trial slug, not expired) always wins over trial_used /
    trial_expires_at. Trial-expired banners must never show for paid users.
    """
    if is_admin(user):
        return {
            "effective_plan_slug": "admin",
            "source": "admin",
            "has_paid_plan": True,
            "subscription_status": "active",
            "trial_active": False,
            "trial_used": bool(getattr(user, "trial_used", False)),
            "show_trial_expired_banner": False,
            "show_upgrade_banner": False,
            "free_usage_active": False,
        }

    free_usage = has_active_free_usage(db, user.id)
    sub, plan = _active_subscription_plan(db, user)
    slug = str(plan.slug or "").lower() if plan else ""
    trial_active = is_saas_trial_active(user)
    trial_used = bool(getattr(user, "trial_used", False))

    if plan is not None and slug and slug not in {TRIAL_PLAN_SLUG, *_LEGACY_PAID_SLUGS}:
        return {
            "effective_plan_slug": slug,
            "source": "paid_subscription",
            "has_paid_plan": True,
            "subscription_status": str(getattr(sub, "status", None) or "active"),
            "trial_active": False,
            "trial_used": trial_used,
            "show_trial_expired_banner": False,
            "show_upgrade_banner": False,
            "free_usage_active": free_usage,
            "subscription_id": int(sub.id) if sub else None,
            "current_period_end": getattr(sub, "current_period_end", None),
        }

    if free_usage:
        return {
            "effective_plan_slug": None,
            "source": "free_usage",
            "has_paid_plan": False,
            "subscription_status": None,
            "trial_active": False,
            "trial_used": trial_used,
            "show_trial_expired_banner": False,
            "show_upgrade_banner": False,
            "free_usage_active": True,
        }

    if trial_active and (plan is None or slug == TRIAL_PLAN_SLUG or slug in _LEGACY_PAID_SLUGS):
        return {
            "effective_plan_slug": TRIAL_PLAN_SLUG,
            "source": "saas_trial",
            "has_paid_plan": False,
            "subscription_status": "trialing",
            "trial_active": True,
            "trial_used": True,
            "show_trial_expired_banner": False,
            "show_upgrade_banner": False,
            "free_usage_active": False,
        }

    source = "trial_expired" if trial_used else "none"
    return {
        "effective_plan_slug": None,
        "source": source,
        "has_paid_plan": False,
        "subscription_status": "expired" if trial_used else None,
        "trial_active": False,
        "trial_used": trial_used,
        "show_trial_expired_banner": bool(trial_used),
        "show_upgrade_banner": True,
        "free_usage_active": False,
    }


def _credit_cost_for_feature(feature_key: str, quantity: int = 1) -> int:
    q = max(1, int(quantity))
    per = {
        "keyword_research": credits_svc.cost_research_run,
        "technical_audit": credits_svc.cost_technical_analyze,
        "seo_score": credits_svc.cost_url_seo_scoreboard,
        "content_ai_article": lambda: credits_svc.cost_content_ai_article(word_count=1000),
        "content_ai_bulk_article": lambda: credits_svc.cost_content_ai_article(word_count=1500),
    }.get(feature_key)
    if per is None:
        return credits_svc._int_env(f"CREDIT_COST_{feature_key.upper()}", 0) * q
    unit = per() if callable(per) else int(per)
    return max(0, unit) * q


def _active_subscription_plan(db: Session, user: User):
    sub = subscription_service.get_active_subscription(db, user.id)
    if sub is None or not subscription_service.is_subscription_active(sub):
        return None, None
    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    return sub, plan


def _has_paid_active_subscription(db: Session, user: User) -> bool:
    _sub, plan = _active_subscription_plan(db, user)
    if plan is None:
        return False
    slug = str(plan.slug or "").lower()
    return slug not in {TRIAL_PLAN_SLUG, *_LEGACY_PAID_SLUGS}


def _apply_credit_requirement(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int,
    base: EntitlementResult,
) -> EntitlementResult:
    if not base.allowed or not credits_svc.credits_enforced():
        return base
    credits_svc.ensure_plan_monthly_credits(db, user.id)
    cost = _credit_cost_for_feature(feature_key, quantity)
    balance = credits_svc.get_available_balance(db, user.id)
    if balance <= 0:
        return EntitlementResult(
            allowed=False,
            reason_code="insufficient_credits",
            message="Tài khoản cần credit > 0 để sử dụng tính năng AI.",
            plan_slug=base.plan_slug,
            subscription_id=base.subscription_id,
            quota_remaining=balance,
            feature_key=feature_key,
        )
    if cost > 0 and balance < cost:
        return EntitlementResult(
            allowed=False,
            reason_code="insufficient_credits",
            message=f"Không đủ credit (cần {cost}, hiện có {balance}).",
            plan_slug=base.plan_slug,
            subscription_id=base.subscription_id,
            quota_remaining=balance,
            feature_key=feature_key,
        )
    return base


def _subscription_allows(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int,
) -> EntitlementResult | None:
    sub, plan = _active_subscription_plan(db, user)
    if sub is None or plan is None:
        return None

    if str(plan.slug or "").lower() == TRIAL_PLAN_SLUG:
        if not is_saas_trial_active(user):
            return EntitlementResult(
                allowed=False,
                reason_code="trial_expired",
                message="Gói dùng thử đã hết hạn. Vui lòng nâng cấp Basic, Pro, Agency hoặc Business để tiếp tục.",
                plan_slug=plan.slug,
                subscription_id=sub.id,
                feature_key=feature_key,
            )
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


def _free_usage_credit_allows(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int,
) -> EntitlementResult | None:
    if _has_paid_active_subscription(db, user):
        return None
    if not has_active_free_usage(db, user.id):
        return None

    days = free_usage_days_remaining(db, user.id)
    if not credits_svc.credits_enforced():
        return EntitlementResult(
            allowed=True,
            reason_code="free_usage",
            message=free_usage_need_credit_message(days),
            feature_key=feature_key,
        )

    credits_svc.ensure_plan_monthly_credits(db, user.id)
    cost = _credit_cost_for_feature(feature_key, quantity)
    balance = credits_svc.get_available_balance(db, user.id)
    if balance <= 0:
        return EntitlementResult(
            allowed=False,
            reason_code="insufficient_credits",
            message=free_usage_need_credit_message(days),
            quota_remaining=balance,
            feature_key=feature_key,
        )
    if cost <= 0:
        return EntitlementResult(
            allowed=True,
            reason_code="free_usage",
            message="Còn ngày sử dụng miễn phí — tính năng không trừ credit.",
            quota_remaining=balance,
            feature_key=feature_key,
        )
    if balance >= cost:
        return EntitlementResult(
            allowed=True,
            reason_code="free_usage_credits",
            message=f"Còn {days} ngày miễn phí — đủ credit ({balance} >= {cost}).",
            quota_remaining=balance - cost,
            feature_key=feature_key,
        )
    return EntitlementResult(
        allowed=False,
        reason_code="insufficient_credits",
        message=free_usage_need_credit_message(days),
        quota_remaining=balance,
        feature_key=feature_key,
    )


def _trial_3d_allows(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int,
) -> EntitlementResult | None:
    if _has_paid_active_subscription(db, user):
        return None
    if not is_saas_trial_active(user):
        if bool(getattr(user, "trial_used", False)):
            return EntitlementResult(
                allowed=False,
                reason_code="trial_expired",
                message="Gói dùng thử đã hết hạn. Vui lòng nâng cấp Basic, Pro, Agency hoặc Business để tiếp tục.",
                plan_slug=TRIAL_PLAN_SLUG,
                feature_key=feature_key,
            )
        return None

    trial_check = check_trial_feature_allowed(db, user, feature_key, quantity=quantity)
    if not trial_check.get("allowed"):
        return EntitlementResult(
            allowed=False,
            reason_code=str(trial_check.get("code") or "denied"),
            message=str(trial_check.get("message") or "Không được phép trong gói dùng thử."),
            plan_slug=TRIAL_PLAN_SLUG,
            feature_key=feature_key,
        )
    return EntitlementResult(
        allowed=True,
        reason_code="trial_3d",
        message="Gói dùng thử 3 ngày — được phép.",
        plan_slug=TRIAL_PLAN_SLUG,
        feature_key=feature_key,
    )


def check_feature(
    db: Session,
    user: User,
    feature_key: str,
    quantity: int = 1,
) -> EntitlementResult:
    """
    Kiểm tra quyền feature (quota/plan):
    1) Admin  2) Subscription paid  3) Free usage  4) Trial 3d  5) Deny.
  Legacy api_access_enabled / BYOK không bypass.
    """
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
            message="SAAS_ENFORCEMENT tắt — giữ hành vi legacy.",
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

    if _has_paid_active_subscription(db, user):
        sub_result = _subscription_allows(db, user, feature_key, quantity)
        if sub_result is not None:
            return _apply_credit_requirement(db, user, feature_key, quantity, sub_result)

    free_usage_result = _free_usage_credit_allows(db, user, feature_key, quantity)
    if free_usage_result is not None:
        return free_usage_result

    trial_result = _trial_3d_allows(db, user, feature_key, quantity)
    if trial_result is not None:
        return trial_result

    sub, plan = _active_subscription_plan(db, user)
    return EntitlementResult(
        allowed=False,
        reason_code="denied",
        message=(
            "Hết thời gian sử dụng miễn phí — vui lòng nâng cấp hoặc gia hạn gói."
            if not has_active_free_usage(db, user.id)
            else "Không có gói, trial hoặc credit phù hợp."
        ),
        plan_slug=plan.slug if plan else resolve_effective_plan(db, user),
        subscription_id=sub.id if sub else None,
        feature_key=feature_key,
    )


def can_use_ai(
    db: Session,
    user: User,
    feature_key: str,
    *,
    estimated_credit_cost: int = 0,
    quantity: int = 1,
    denied_message: str | None = None,
) -> dict[str, Any]:
    """
    Unified AI gate: feature entitlement + system API + credit.
    Mọi user (trừ admin) dùng API hệ thống — không dùng key riêng.
    """
    from app.services.user_api_access import (
        SYSTEM_API_NOT_CONFIGURED_MSG,
        admin_system_llm_available,
        resolve_effective_ai_plan_slug,
    )

    feature_key = str(feature_key or "content_ai_article").strip()
    unit = max(0, int(estimated_credit_cost))
    balance = credits_svc.get_available_balance(db, user.id)

    if is_admin(user):
        return {
            "allowed": True,
            "use_system_llm": True,
            "charge_credits": False,
            "unit_cost": 0,
            "plan_slug": "admin",
            "code": "ok",
            "message": "",
            "feature_key": feature_key,
            "credit_balance": balance,
            "entitlement": "admin",
        }

    feat = check_feature(db, user, feature_key, quantity=quantity)
    if not feat.allowed:
        return {
            "allowed": False,
            "use_system_llm": True,
            "charge_credits": False,
            "unit_cost": unit,
            "code": feat.reason_code,
            "message": feat.message,
            "plan_slug": feat.plan_slug,
            "feature_key": feature_key,
            "credit_balance": balance,
            "entitlement": feat.reason_code,
        }

    if not admin_system_llm_available(db):
        return {
            "allowed": False,
            "use_system_llm": True,
            "charge_credits": False,
            "unit_cost": unit,
            "code": "system_api_missing",
            "message": SYSTEM_API_NOT_CONFIGURED_MSG,
            "plan_slug": feat.plan_slug or resolve_effective_ai_plan_slug(db, user),
            "feature_key": feature_key,
            "credit_balance": balance,
            "entitlement": feat.reason_code,
        }

    if credits_svc.credits_enforced():
        credits_svc.ensure_plan_monthly_credits(db, user.id)
        balance = credits_svc.get_available_balance(db, user.id)
        need = unit if unit > 0 else _credit_cost_for_feature(feature_key, quantity)
        if balance <= 0:
            return {
                "allowed": False,
                "use_system_llm": True,
                "charge_credits": False,
                "unit_cost": need,
                "code": "insufficient_credits",
                "message": denied_message or "Tài khoản cần credit > 0 để sử dụng AI.",
                "plan_slug": feat.plan_slug,
                "feature_key": feature_key,
                "credit_balance": balance,
                "entitlement": feat.reason_code,
            }
        if need > 0 and balance < need:
            return {
                "allowed": False,
                "use_system_llm": True,
                "charge_credits": False,
                "unit_cost": need,
                "code": "insufficient_credits",
                "message": f"Bạn cần {need} credit, tài khoản hiện có {balance} credit.",
                "plan_slug": feat.plan_slug,
                "feature_key": feature_key,
                "credit_balance": balance,
                "entitlement": feat.reason_code,
            }

    charge_unit = unit if unit > 0 else _credit_cost_for_feature(feature_key, quantity)
    return {
        "allowed": True,
        "use_system_llm": True,
        "charge_credits": charge_unit > 0 and credits_svc.credits_enforced(),
        "unit_cost": charge_unit,
        "plan_slug": feat.plan_slug or resolve_effective_ai_plan_slug(db, user),
        "code": "ok",
        "message": "",
        "feature_key": feature_key,
        "credit_balance": balance,
        "entitlement": feat.reason_code,
    }


def ensure_ai_entitlement(
    db: Session,
    user: User,
    feature_key: str,
    *,
    estimated_credit_cost: int = 0,
    quantity: int = 1,
    denied_message: str | None = None,
) -> dict[str, Any]:
    snap = can_use_ai(
        db,
        user,
        feature_key,
        estimated_credit_cost=estimated_credit_cost,
        quantity=quantity,
        denied_message=denied_message,
    )
    if snap.get("allowed"):
        return snap
    code = str(snap.get("code") or "denied")
    http_status = (
        status.HTTP_402_PAYMENT_REQUIRED
        if code in ("insufficient_credits", "trial_need_credit", "trial_credit_cap")
        else status.HTTP_403_FORBIDDEN
    )
    raise HTTPException(status_code=http_status, detail=snap)


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
    if result.reason_code in ("insufficient_credits", "trial_need_credit"):
        status_code = status.HTTP_402_PAYMENT_REQUIRED
        if (
            has_active_free_usage(db, user.id)
            and not _has_paid_active_subscription(db, user)
        ):
            days = free_usage_days_remaining(db, user.id)
            balance = credits_svc.get_available_balance(db, user.id)
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": "free_usage_need_credit",
                    "message": free_usage_need_credit_message(days),
                    "feature_key": result.feature_key,
                    "free_usage_days_remaining": days,
                    "quota_remaining": balance,
                    "upgrade_url": "/account/billing",
                },
            )

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
