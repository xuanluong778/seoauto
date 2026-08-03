"""Admin-only SaaS Phase 1 APIs (manual test — no product enforcement)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.models.monthly_usage import MonthlyUsage
from app.models.payment_transaction import PaymentTransaction
from app.schemas.saas import (
    AdminGiftEligibilityResponse,
    AdminGiftHistoryResponse,
    AdminGiftPlanBody,
    AdminGiftPlanResponse,
    AdminGiftUsageDaysBody,
    AdminGiftUsageDaysResponse,
    AdminGrantSubscriptionBody,
    AdminPricingPlanItem,
    AdminPricingPlanListResponse,
    AdminPricingPlanUpdateBody,
    AdminPricingResetBody,
    AdminPlanQuotaListResponse,
    AdminPlanQuotaPatch,
    AdminPlanQuotaPlan,
    AdminPlanQuotaRow,
    AdminTestRecordUsageBody,
    AdminTestRecordUsageResponse,
    AdminUserSubscriptionStatus,
    AdminUserUsageResponse,
    EntitlementResult,
    MonthlyUsageRow,
    PlanListResponse,
    PlanResponse,
    SubscriptionResponse,
    UsageLimitResponse,
)
from app.services import entitlement_service, plan_service, subscription_service, usage_tracking_service
from app.services.admin_gift_service import (
    GIFT_DAYS_ACTION,
    GIFT_PLAN_ACTION,
    admin_gift_plan,
    admin_gift_usage_days,
    gift_eligibility,
    list_user_gift_history,
)
from app.services.affiliate_payment_hooks import on_payment_completed
from app.services.rbac import require_admin_user
from app.services.security_audit_log import log_audit_event
from app.services.seoauto_pricing_catalog import (
    list_admin_pricing_plans,
    reset_admin_pricing_plans,
    update_admin_pricing_plan,
)
from app.services.plan_quota_admin_service import (
    list_admin_plan_quotas,
    reset_admin_plan_quota,
    update_admin_plan_quota,
)

router = APIRouter(prefix="/saas", tags=["admin-saas"])


def _plan_to_response(plan) -> PlanResponse:
    limits = getattr(plan, "usage_limits", None) or plan_service.get_limits_for_plan(plan.id)
    return PlanResponse(
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
        usage_limits=[UsageLimitResponse.model_validate(ul) for ul in limits],
    )


def _user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == int(user_id)).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/plans", response_model=PlanListResponse)
def list_saas_plans(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> PlanListResponse:
    plans = plan_service.list_active_plans(db, public_only=False)
    items = []
    for plan in plans:
        full = plan_service.get_plan_with_limits(db, plan.id) or plan
        items.append(_plan_to_response(full))
    return PlanListResponse(items=items, total=len(items))


@router.get("/pricing-plans", response_model=AdminPricingPlanListResponse)
def admin_list_pricing_plans(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminPricingPlanListResponse:
    """Admin catalog for /pricing (Starter, Pro, Agency, Business)."""
    items = [AdminPricingPlanItem.model_validate(row) for row in list_admin_pricing_plans(db)]
    return AdminPricingPlanListResponse(items=items, total=len(items))


@router.get("/plan-quotas", response_model=AdminPlanQuotaListResponse)
def admin_list_plan_quotas(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminPlanQuotaListResponse:
    """Quota tháng theo gói (usage_limits) — Basic / Pro / Agency / Business."""
    rows = list_admin_plan_quotas(db)
    return AdminPlanQuotaListResponse(
        items=[AdminPlanQuotaPlan.model_validate(r) for r in rows],
    )


@router.patch("/plan-quotas/{plan_slug}/{quota_key}", response_model=AdminPlanQuotaRow)
def admin_patch_plan_quota(
    plan_slug: str,
    quota_key: str,
    payload: AdminPlanQuotaPatch,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPlanQuotaRow:
    try:
        row = update_admin_plan_quota(
            db,
            plan_slug=plan_slug,
            quota_key=quota_key,
            limit_value=payload.limit_value,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        action="admin.saas.update_plan_quota",
        user_id=admin.id,
        resource_type="plan_quota",
        resource_id=f"{plan_slug.strip().lower()}:{quota_key.strip().lower()}",
        detail={"plan_slug": plan_slug, "quota_key": quota_key, "limit_value": payload.limit_value},
        request=request,
    )
    return AdminPlanQuotaRow.model_validate(row)


@router.post("/plan-quotas/{plan_slug}/{quota_key}/reset", response_model=AdminPlanQuotaRow)
def admin_reset_plan_quota(
    plan_slug: str,
    quota_key: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPlanQuotaRow:
    try:
        row = reset_admin_plan_quota(db, plan_slug=plan_slug, quota_key=quota_key)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        action="admin.saas.reset_plan_quota",
        user_id=admin.id,
        resource_type="plan_quota",
        resource_id=f"{plan_slug.strip().lower()}:{quota_key.strip().lower()}",
        detail={"plan_slug": plan_slug, "quota_key": quota_key},
        request=request,
    )
    return AdminPlanQuotaRow.model_validate(row)


@router.put("/pricing-plans/{slug}", response_model=AdminPricingPlanItem)
def admin_update_pricing_plan(
    slug: str,
    payload: AdminPricingPlanUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPricingPlanItem:
    try:
        row = update_admin_pricing_plan(db, slug, payload.model_dump())
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        action="admin.saas.update_pricing_plan",
        user_id=admin.id,
        resource_type="plan",
        resource_id=slug.strip().lower(),
        detail={"slug": slug.strip().lower(), "month_price": payload.month_price},
        request=request,
    )
    return AdminPricingPlanItem.model_validate(row)


@router.post("/pricing-plans/reset", response_model=AdminPricingPlanListResponse)
def admin_reset_pricing_plans(
    payload: AdminPricingResetBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPricingPlanListResponse:
    try:
        reset_admin_pricing_plans(db, payload.slug)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        action="admin.saas.reset_pricing_plans",
        user_id=admin.id,
        resource_type="plan",
        resource_id=payload.slug or "all",
        detail={"slug": payload.slug},
        request=request,
    )
    items = [AdminPricingPlanItem.model_validate(row) for row in list_admin_pricing_plans(db)]
    return AdminPricingPlanListResponse(items=items, total=len(items))


@router.get("/users/{user_id}/subscription", response_model=AdminUserSubscriptionStatus)
def get_user_subscription(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminUserSubscriptionStatus:
    _user_or_404(db, user_id)
    sub = subscription_service.get_active_subscription(db, user_id)
    if sub is None:
        return AdminUserSubscriptionStatus(
            user_id=int(user_id),
            message="User chưa có subscription SaaS đang hiệu lực.",
        )

    plan = plan_service.get_plan_by_id(db, sub.plan_id)
    return AdminUserSubscriptionStatus(
        user_id=int(user_id),
        subscription_id=sub.id,
        plan_slug=plan.slug if plan else None,
        plan_name=plan.name if plan else None,
        status=sub.status,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=bool(sub.cancel_at_period_end),
        notes=sub.notes,
    )


@router.post("/users/{user_id}/grant-subscription", response_model=SubscriptionResponse)
def grant_user_subscription(
    user_id: int,
    payload: AdminGrantSubscriptionBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> SubscriptionResponse:
    target = _user_or_404(db, user_id)
    plan = plan_service.get_plan_by_slug(db, payload.plan_slug.strip())
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan slug không tồn tại: {payload.plan_slug}",
        )

    cycle = str(payload.billing_cycle or "monthly").strip().lower()
    months = int(payload.months or 1)
    if cycle == "semi_annual":
        months = 6
    elif cycle == "yearly":
        months = 14

    sub = subscription_service.create_subscription(
        db,
        target.id,
        plan.id,
        months=months,
        status="active",
        source="manual",
        notes=payload.notes,
    )
    from app.services.monthly_bonus_credit_service import grant_admin_plan_cycle_credits

    credit_note = (
        f"admin_grant subscription_id={sub.id} billing_cycle={cycle} months={months}"
    )
    credit_result = grant_admin_plan_cycle_credits(
        db,
        user_id=target.id,
        plan_slug=plan.slug,
        billing_cycle=cycle,
        note=credit_note,
    )
    order_amount = int(plan.price_amount or 0) * max(1, int(payload.months or 1))
    if order_amount > 0:
        pay = PaymentTransaction(
            user_id=target.id,
            subscription_id=sub.id,
            plan_id=plan.id,
            amount=order_amount,
            currency=str(plan.currency or "VND"),
            status="paid",
            provider="manual",
            provider_transaction_id=f"grant-{sub.id}",
            paid_at=sub.current_period_start,
        )
        db.add(pay)
        db.flush()
        on_payment_completed(
            db,
            user_id=target.id,
            net_amount=order_amount,
            payment_transaction_id=pay.id,
            subscription_id=sub.id,
        )
    db.commit()
    db.refresh(sub)

    log_audit_event(
        action="admin.saas.grant_subscription",
        user_id=admin.id,
        resource_type="subscription",
        resource_id=str(sub.id),
        detail={
            "target_user_id": target.id,
            "target_email": target.email,
            "plan_slug": plan.slug,
            "months": months,
            "billing_cycle": cycle,
            "credit_grant": credit_result,
        },
        request=request,
    )

    return subscription_service.subscription_to_response(db, sub)


@router.get("/users/{user_id}/gift-eligibility", response_model=AdminGiftEligibilityResponse)
def get_user_gift_eligibility(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminGiftEligibilityResponse:
    _user_or_404(db, user_id)
    return AdminGiftEligibilityResponse(**gift_eligibility(db, user_id))


@router.get("/users/{user_id}/gifts", response_model=AdminGiftHistoryResponse)
def get_user_gift_history(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminGiftHistoryResponse:
    _user_or_404(db, user_id)
    items = list_user_gift_history(db, user_id, limit=limit)
    return AdminGiftHistoryResponse(items=items, total=len(items))


@router.post("/users/{user_id}/gift-plan", response_model=AdminGiftPlanResponse)
def gift_user_plan(
    user_id: int,
    payload: AdminGiftPlanBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminGiftPlanResponse:
    target = _user_or_404(db, user_id)
    result = admin_gift_plan(
        db,
        admin=admin,
        target=target,
        plan_slug=payload.plan_slug.strip(),
        duration_days=payload.duration_days,
        duration_months=payload.duration_months,
        include_credit=bool(payload.include_credit),
        notes=payload.notes,
    )
    db.commit()

    log_audit_event(
        action=GIFT_PLAN_ACTION,
        user_id=admin.id,
        resource_type="user",
        resource_id=str(target.id),
        detail={
            "admin_id": admin.id,
            "target_user_id": target.id,
            "target_email": target.email,
            "plan_slug": result["plan_slug"],
            "plan_name": result.get("plan_name"),
            "duration_days": result.get("duration_days"),
            "duration_months": result.get("duration_months"),
            "credits_granted": result.get("credits_granted", 0),
            "include_credit": result.get("include_credit"),
            "reason": result.get("notes"),
            "subscription_id": result.get("subscription_id"),
        },
        request=request,
    )
    return AdminGiftPlanResponse(**result)


@router.post("/users/{user_id}/gift-usage-days", response_model=AdminGiftUsageDaysResponse)
def gift_user_usage_days(
    user_id: int,
    payload: AdminGiftUsageDaysBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminGiftUsageDaysResponse:
    target = _user_or_404(db, user_id)
    result = admin_gift_usage_days(
        db,
        admin=admin,
        target=target,
        days=int(payload.days),
        notes=payload.notes,
    )
    db.commit()

    log_audit_event(
        action=GIFT_DAYS_ACTION,
        user_id=admin.id,
        resource_type="user",
        resource_id=str(target.id),
        detail={
            "admin_id": admin.id,
            "target_user_id": target.id,
            "target_email": target.email,
            "days_granted": result.get("days_granted"),
            "previous_free_usage_expires_at": result.get("previous_free_usage_expires_at"),
            "free_usage_expires_at": result.get("free_usage_expires_at"),
            "free_usage_days_remaining": result.get("free_usage_days_remaining"),
            "reason": result.get("notes"),
        },
        request=request,
    )
    return AdminGiftUsageDaysResponse(**result)


@router.get("/users/{user_id}/trial-status")
def admin_get_trial_status(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict:
    target = _user_or_404(db, user_id)
    from app.services.saas_trial_service import trial_status_payload

    return trial_status_payload(db, target)


@router.post("/users/{user_id}/trial/end")
def admin_end_trial(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> dict:
    target = _user_or_404(db, user_id)
    from app.services.saas_trial_service import end_saas_trial_state, log_trial_audit, trial_status_payload

    end_saas_trial_state(db, target.id, reason="admin_end")
    subscription_service.expire_active_subscriptions_for_user(db, target.id)
    log_trial_audit(db, action="trial_expired", user_id=target.id, admin_id=admin.id, detail={"by": "admin"})
    db.commit()
    return {"ok": True, **trial_status_payload(db, target)}


@router.post("/users/{user_id}/trial/extend")
def admin_extend_trial(
    user_id: int,
    days: int = Query(..., ge=1, le=30),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> dict:
    from datetime import datetime, timedelta, timezone

    from app.services.saas_trial_service import log_trial_audit, trial_status_payload

    target = _user_or_404(db, user_id)
    now = datetime.now(timezone.utc)
    end = target.trial_expires_at
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    base = end if end and end > now else now
    target.trial_expires_at = base + timedelta(days=int(days))
    target.trial_used = True
    log_trial_audit(
        db,
        action="extend_trial",
        user_id=target.id,
        admin_id=admin.id,
        detail={"days": int(days)},
    )
    db.commit()
    return {"ok": True, **trial_status_payload(db, target)}


@router.get("/users/{user_id}/usage", response_model=AdminUserUsageResponse)
def get_user_usage(
    user_id: int,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminUserUsageResponse:
    _user_or_404(db, user_id)
    usage_month = month or usage_tracking_service.current_usage_month()
    sub = subscription_service.get_active_subscription(db, user_id)
    plan_id = sub.plan_id if sub else None
    plan_slug: str | None = None
    if plan_id:
        plan = plan_service.get_plan_by_id(db, plan_id)
        plan_slug = plan.slug if plan else None

    rows = (
        db.query(MonthlyUsage)
        .filter(
            MonthlyUsage.user_id == int(user_id),
            MonthlyUsage.usage_month == usage_month,
        )
        .order_by(MonthlyUsage.feature_key.asc())
        .all()
    )
    used_by_feature = {r.feature_key: r for r in rows}
    items: list[MonthlyUsageRow] = []

    if plan_id:
        for lim in plan_service.get_limits_for_plan(db, plan_id):
            row = used_by_feature.get(lim.feature_key)
            qty = int(row.quantity_used) if row else 0
            credits = int(row.credits_used) if row else 0
            remaining = usage_tracking_service.get_quota_remaining(
                db, user_id, lim.feature_key, plan_id=plan_id
            )
            items.append(
                MonthlyUsageRow(
                    feature_key=lim.feature_key,
                    quantity_used=qty,
                    credits_used=credits,
                    limit_value=int(lim.limit_value),
                    quota_remaining=remaining,
                    period=lim.period,
                )
            )
    else:
        for row in rows:
            items.append(
                MonthlyUsageRow(
                    feature_key=row.feature_key,
                    quantity_used=int(row.quantity_used),
                    credits_used=int(row.credits_used),
                    limit_value=None,
                    quota_remaining=None,
                    period="monthly",
                )
            )

    message = None
    if not sub:
        message = "User chưa có subscription SaaS đang hiệu lực — chỉ hiển thị usage đã ghi (nếu có)."
    elif not items:
        message = "Chưa có usage trong tháng này."

    return AdminUserUsageResponse(
        user_id=int(user_id),
        usage_month=usage_month,
        plan_slug=plan_slug,
        subscription_id=sub.id if sub else None,
        items=items,
        message=message,
    )


@router.get("/users/{user_id}/entitlement-check", response_model=EntitlementResult)
def entitlement_check(
    user_id: int,
    feature_key: str = Query(..., min_length=1, max_length=64),
    quantity: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> EntitlementResult:
    user = _user_or_404(db, user_id)
    return entitlement_service.check_feature(db, user, feature_key, quantity=quantity)


@router.post("/users/{user_id}/usage/test-record", response_model=AdminTestRecordUsageResponse)
def test_record_usage(
    user_id: int,
    payload: AdminTestRecordUsageBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminTestRecordUsageResponse:
    user = _user_or_404(db, user_id)
    sub = subscription_service.get_active_subscription(db, user.id)

    existing_id: int | None = None
    if payload.idempotency_key:
        from app.models.usage_event import UsageEvent

        row = (
            db.query(UsageEvent)
            .filter(UsageEvent.idempotency_key == payload.idempotency_key.strip()[:128])
            .one_or_none()
        )
        if row is not None:
            existing_id = row.id

    event = usage_tracking_service.record_successful_usage(
        db,
        user.id,
        payload.feature_key.strip(),
        quantity=payload.quantity,
        subscription_id=sub.id if sub else None,
        plan_id=sub.plan_id if sub else None,
        idempotency_key=payload.idempotency_key,
    )
    db.commit()

    log_audit_event(
        action="admin.saas.test_record_usage",
        user_id=admin.id,
        resource_type="usage_event",
        resource_id=str(event.id),
        detail={
            "target_user_id": user.id,
            "feature_key": payload.feature_key,
            "quantity": payload.quantity,
            "idempotency_key": payload.idempotency_key,
        },
        request=request,
    )

    qty_month = usage_tracking_service.get_monthly_usage(db, user.id, payload.feature_key.strip())
    remaining = usage_tracking_service.get_quota_remaining(
        db, user.id, payload.feature_key.strip()
    )

    return AdminTestRecordUsageResponse(
        event_id=event.id,
        idempotent_replay=existing_id is not None and existing_id == event.id,
        feature_key=payload.feature_key.strip(),
        quantity_used_month=qty_month,
        quota_remaining=remaining,
    )


@router.get("/credit-policy")
def admin_credit_policy(
    admin: User = Depends(require_admin_user),
) -> dict:
    """Admin: cấu hình credit gói, cap cộng dồn, hạn purchased/trial/promo (env + defaults)."""
    from app.services.credit_policy_service import policy_snapshot

    _ = admin
    return policy_snapshot()
