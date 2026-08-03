"""Sync usage_limits from plan_quota_registry (idempotent)."""

from __future__ import annotations

import logging

from app.db import SessionLocal
from app.models.plan import Plan
from app.models.usage_limit import UsageLimit
from app.services.plan_quota_registry import iter_usage_limits

_LOG = logging.getLogger(__name__)

_SYNCED = False


def _upsert_limit(
    db,
    plan_id: int,
    feature_key: str,
    limit_value: int,
    period: str,
    is_hard_limit: bool,
) -> bool:
    row = (
        db.query(UsageLimit)
        .filter(
            UsageLimit.plan_id == plan_id,
            UsageLimit.feature_key == feature_key,
            UsageLimit.period == period,
        )
        .one_or_none()
    )
    if row is None:
        db.add(
            UsageLimit(
                plan_id=plan_id,
                feature_key=feature_key,
                limit_value=limit_value,
                period=period,
                is_hard_limit=is_hard_limit,
            )
        )
        return True
    changed = False
    for attr, val in (
        ("limit_value", limit_value),
        ("period", period),
        ("is_hard_limit", is_hard_limit),
    ):
        if getattr(row, attr) != val:
            setattr(row, attr, val)
            changed = True
    return changed


def ensure_plan_quotas() -> None:
    global _SYNCED
    if _SYNCED:
        return
    db = SessionLocal()
    try:
        plans = {p.slug: p for p in db.query(Plan).all()}
        changed = 0
        for plan_slug, feature_key, limit_value, period, is_hard in iter_usage_limits():
            plan = plans.get(plan_slug)
            if plan is None:
                continue
            if _upsert_limit(db, plan.id, feature_key, limit_value, period, is_hard):
                changed += 1
        if changed:
            db.commit()
            _LOG.info("ensure_plan_quotas: synced %s usage_limit row(s)", changed)
        else:
            db.rollback()
        _SYNCED = True
    except Exception:
        db.rollback()
        _LOG.exception("ensure_plan_quotas failed")
        raise
    finally:
        db.close()
