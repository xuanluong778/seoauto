"""SaaS read-only snapshot for the logged-in user (Phase 1c)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.monthly_usage import MonthlyUsage
from app.models.user import User
from app.schemas.saas import SaasMeResponse, SaasQuotaItem
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.credits import get_available_balance
from app.services.free_usage_service import free_usage_plan_label, free_usage_snapshot
from app.services.saas_trial_service import trial_status_payload
from app.services.rbac import is_admin, normalize_role
from app.services.user_api_access import (
    api_access_enabled_for,
    describe_user_llm_source,
    may_manage_custom_api_keys,
)
from app.services.saas_ui_messages import (
    MSG_EXPIRED,
    MSG_NEED_CREDIT,
    MSG_NO_TRIAL,
    MSG_SYSTEM_OK,
    resolve_ai_access_state,
)
from app.services.user_trial_service import trial_status_snapshot


def _parse_plan_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _trial_status_label(snap: dict) -> str:
    if snap.get("is_admin_bypass"):
        return "admin"
    if snap.get("is_api_grant_bypass"):
        return "api_granted"
    if snap.get("is_active"):
        return "active"
    if snap.get("never_used"):
        return "pending"
    return "expired"


def build_saas_me_response(db: Session, user: User) -> SaasMeResponse:
    usage_month = usage_tracking_service.current_usage_month()
    credit_balance = get_available_balance(db, user.id, sync=True)
    snap = trial_status_snapshot(db, user.id, role=normalize_role(getattr(user, "role", None)))
    trial_status = _trial_status_label(snap)
    trial_message = str(snap.get("message") or "") or None

    sub = subscription_service.get_active_subscription(db, user.id)
    plan_slug: str | None = None
    plan_name: str | None = None
    subscription_status: str | None = None
    period_start = None
    period_end = None
    message: str | None = "Chưa có gói SaaS"
    quotas: list[SaasQuotaItem] = []
    byok_note: str | None = None
    trial_days: int | None = None

    if sub is not None:
        plan = plan_service.get_plan_by_id(db, sub.plan_id)
        if plan is not None:
            plan_slug = plan.slug
            plan_name = plan.name
            message = None
            meta = _parse_plan_metadata(getattr(plan, "metadata_json", None))
            trial_days = int(meta.get("trial_days") or 0) or None
            note = str(meta.get("note") or "").strip()
            if note:
                byok_note = note
            elif plan_slug == "free_trial_5d":
                byok_note = None  # legacy plan — không quảng bá BYOK cho user thường
        subscription_status = sub.status
        period_start = sub.current_period_start
        period_end = sub.current_period_end

        for lim in plan_service.get_limits_for_plan(db, sub.plan_id):
            qty = usage_tracking_service.get_monthly_usage(
                db, user.id, lim.feature_key, month=usage_month
            )
            remaining = usage_tracking_service.get_quota_remaining(
                db, user.id, lim.feature_key, plan_id=sub.plan_id
            )
            quotas.append(
                SaasQuotaItem(
                    feature_key=lim.feature_key,
                    limit_value=int(lim.limit_value),
                    quantity_used=qty,
                    quota_remaining=remaining,
                )
            )
    else:
        rows = (
            db.query(MonthlyUsage)
            .filter(
                MonthlyUsage.user_id == int(user.id),
                MonthlyUsage.usage_month == usage_month,
            )
            .order_by(MonthlyUsage.feature_key.asc())
            .all()
        )
        for row in rows:
            quotas.append(
                SaasQuotaItem(
                    feature_key=row.feature_key,
                    limit_value=None,
                    quantity_used=int(row.quantity_used),
                    quota_remaining=None,
                )
            )

    if trial_days is None and trial_status in ("active", "pending"):
        trial_days = 3

    usage_snap = free_usage_snapshot(
        db,
        user,
        credit_balance=credit_balance,
    )
    if usage_snap["free_usage_active"] and plan_slug is None:
        plan_name = free_usage_plan_label(int(usage_snap["free_usage_days_remaining"]))
        message = usage_snap.get("free_usage_banner")

    trial_snap = trial_status_payload(db, user)
    access_ui = resolve_ai_access_state(db, user)

    if str(plan_slug or "").lower() == "trial_3d" or trial_snap.get("trial_active"):
        plan_slug = plan_slug or "trial_3d"
        plan_name = f"Còn {trial_snap.get('trial_days_remaining', 0)} ngày dùng thử"
        subscription_status = "trialing" if trial_snap.get("trial_active") else subscription_status
        if access_ui.get("state") == "need_credit":
            message = MSG_NEED_CREDIT
        elif access_ui.get("state") == "ready":
            message = MSG_SYSTEM_OK
        else:
            message = trial_snap.get("banner")
    elif not is_admin(user):
        message = str(access_ui.get("message") or message)

    if not is_admin(user):
        byok_note = None
        if access_ui.get("state") == "no_trial":
            trial_message = MSG_NO_TRIAL
        elif access_ui.get("state") == "need_credit":
            trial_message = MSG_NEED_CREDIT
        elif access_ui.get("state") == "expired":
            trial_message = MSG_EXPIRED

    return SaasMeResponse(
        user_id=int(user.id),
        plan_slug=plan_slug,
        plan_name=plan_name,
        subscription_status=subscription_status,
        current_period_start=period_start,
        current_period_end=period_end,
        usage_month=usage_month,
        quotas=quotas,
        credit_balance=int(credit_balance),
        trial_status=trial_status,
        trial_message=trial_message,
        api_access_enabled=api_access_enabled_for(user) or is_admin(user),
        can_manage_api_keys=may_manage_custom_api_keys(db, user),
        llm_source=describe_user_llm_source(db, user),
        message=message,
        byok_note=byok_note,
        trial_days=trial_days,
        free_usage_active=bool(usage_snap["free_usage_active"]),
        free_usage_days_remaining=int(usage_snap["free_usage_days_remaining"]),
        free_usage_expires_at=usage_snap["free_usage_expires_at"],
        free_usage_banner=usage_snap.get("free_usage_banner"),
        needs_credit_for_features=bool(usage_snap["needs_credit_for_features"]),
        free_usage_need_credit_message=usage_snap.get("free_usage_need_credit_message"),
        saas_trial_active=bool(trial_snap.get("trial_active")),
        saas_trial_used=bool(trial_snap.get("trial_used")),
        saas_trial_can_activate=bool(trial_snap.get("can_activate")),
        saas_trial_days_remaining=int(trial_snap.get("trial_days_remaining") or 0),
        saas_trial_credit_limit=int(trial_snap.get("trial_credit_limit") or 1000),
        saas_trial_credit_used=int(trial_snap.get("trial_credit_used") or 0),
        saas_trial_credit_remaining=int(trial_snap.get("trial_credit_remaining") or 0),
        saas_trial_banner=trial_snap.get("banner"),
        saas_trial_need_credit_message=trial_snap.get("need_credit_message"),
        has_paid_plan=bool(trial_snap.get("has_paid_plan")),
        effective_plan_slug=trial_snap.get("effective_plan_slug") or plan_slug,
        plan_source=trial_snap.get("plan_source"),
        show_upgrade_banner=bool(trial_snap.get("show_upgrade_banner")),
        show_trial_expired_banner=bool(trial_snap.get("show_trial_expired_banner")),
        ai_access_state=str(access_ui.get("state") or ""),
        ai_access_message=str(access_ui.get("message") or ""),
        can_use_ai=bool(access_ui.get("can_use_ai")),
    )
