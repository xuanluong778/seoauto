"""SaaS read-only snapshot for the logged-in user (Phase 1c)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.monthly_usage import MonthlyUsage
from app.models.user import User
from app.schemas.saas import SaasMeResponse, SaasQuotaItem
from app.services import plan_service, subscription_service, usage_tracking_service
from app.services.rbac import is_admin, normalize_role
from app.services.user_api_access import api_access_enabled_for
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
                byok_note = "Yêu cầu API key cá nhân"
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

    if byok_note is None and trial_status in ("active", "pending"):
        byok_note = "Yêu cầu API key cá nhân (BYOK — thêm key trong Cài đặt)"
    if trial_days is None and trial_status in ("active", "pending"):
        trial_days = 5

    return SaasMeResponse(
        user_id=int(user.id),
        plan_slug=plan_slug,
        plan_name=plan_name,
        subscription_status=subscription_status,
        current_period_start=period_start,
        current_period_end=period_end,
        usage_month=usage_month,
        quotas=quotas,
        trial_status=trial_status,
        trial_message=trial_message,
        api_access_enabled=api_access_enabled_for(user) or is_admin(user),
        message=message,
        byok_note=byok_note,
        trial_days=trial_days,
    )
