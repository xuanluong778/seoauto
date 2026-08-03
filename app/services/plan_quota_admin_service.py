"""Admin read/write plan quotas (usage_limits + registry defaults)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.usage_limit import UsageLimit
from app.services import plan_service
from app.services.plan_quota_registry import (
    FEATURE_KEYS,
    FEATURE_LABELS_VI,
    PAID_PLAN_SLUGS,
    PLAN_DISPLAY_NAMES,
    PLAN_FEATURES,
    feature_key_for,
    monthly_quota,
)


def _quota_keys_ordered() -> list[str]:
    return list(FEATURE_KEYS.keys())


def list_admin_plan_quotas(db: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slug in PAID_PLAN_SLUGS:
        plan = plan_service.get_plan_by_slug(db, slug)
        if plan is None:
            continue
        limits_by_fk: dict[str, UsageLimit] = {}
        for row in plan_service.get_limits_for_plan(db, plan.id):
            limits_by_fk[row.feature_key] = row

        quotas: list[dict[str, Any]] = []
        for qkey in _quota_keys_ordered():
            fk = feature_key_for(qkey)
            default_val = monthly_quota(slug, qkey)
            row = limits_by_fk.get(fk)
            current = int(row.limit_value) if row is not None else default_val
            quotas.append({
                "quota_key": qkey,
                "feature_key": fk,
                "label": FEATURE_LABELS_VI.get(qkey, qkey),
                "limit_value": current,
                "default_value": default_val,
                "period": row.period if row is not None else "monthly",
                "is_custom": row is not None and int(row.limit_value) != default_val,
            })
        out.append({
            "plan_slug": slug,
            "plan_name": plan.name or PLAN_DISPLAY_NAMES.get(slug, slug),
            "quotas": quotas,
            "features": dict(PLAN_FEATURES.get(slug, {})),
        })
    return out


def update_admin_plan_quota(
    db: Session,
    *,
    plan_slug: str,
    quota_key: str,
    limit_value: int,
) -> dict[str, Any]:
    slug = str(plan_slug or "").strip().lower()
    qkey = str(quota_key or "").strip().lower()
    if slug not in PAID_PLAN_SLUGS:
        raise ValueError(f"Gói không hợp lệ: {plan_slug}")
    if qkey not in FEATURE_KEYS:
        raise ValueError(f"Quota key không hợp lệ: {quota_key}")

    plan = plan_service.get_plan_by_slug(db, slug)
    if plan is None:
        raise ValueError(f"Plan chưa có trong DB: {slug}")

    fk = feature_key_for(qkey)
    val = max(0, int(limit_value))
    row = plan_service.get_limit_for_feature(db, plan.id, fk)
    if row is None:
        row = UsageLimit(
            plan_id=plan.id,
            feature_key=fk,
            limit_value=val,
            period="monthly",
            is_hard_limit=True,
        )
        db.add(row)
    else:
        row.limit_value = val
        row.period = "monthly"
        row.is_hard_limit = True
    db.flush()

    default_val = monthly_quota(slug, qkey)
    return {
        "plan_slug": slug,
        "plan_name": plan.name or PLAN_DISPLAY_NAMES.get(slug, slug),
        "quota_key": qkey,
        "feature_key": fk,
        "label": FEATURE_LABELS_VI.get(qkey, qkey),
        "limit_value": val,
        "default_value": default_val,
        "period": "monthly",
        "is_custom": val != default_val,
    }


def reset_admin_plan_quota(db: Session, *, plan_slug: str, quota_key: str) -> dict[str, Any]:
    slug = str(plan_slug or "").strip().lower()
    qkey = str(quota_key or "").strip().lower()
    default_val = monthly_quota(slug, qkey)
    return update_admin_plan_quota(db, plan_slug=slug, quota_key=qkey, limit_value=default_val)
