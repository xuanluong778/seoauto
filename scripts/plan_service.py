"""SaaS plan catalog reads (Phase 1 — no enforcement)."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models.plan import Plan
from app.models.usage_limit import UsageLimit


def list_active_plans(db: Session, *, public_only: bool = True) -> list[Plan]:
    q = db.query(Plan).filter(Plan.is_active.is_(True))
    if public_only:
        q = q.filter(Plan.is_public.is_(True))
    return q.order_by(Plan.sort_order.asc(), Plan.id.asc()).all()


def get_plan_by_slug(db: Session, slug: str) -> Plan | None:
    return db.query(Plan).filter(Plan.slug == slug.strip()).one_or_none()


def get_plan_by_id(db: Session, plan_id: int) -> Plan | None:
    return db.query(Plan).filter(Plan.id == int(plan_id)).one_or_none()


def get_limits_for_plan(db: Session, plan_id: int) -> list[UsageLimit]:
    return (
        db.query(UsageLimit)
        .filter(UsageLimit.plan_id == int(plan_id))
        .order_by(UsageLimit.feature_key.asc())
        .all()
    )


def get_limit_for_feature(db: Session, plan_id: int, feature_key: str) -> UsageLimit | None:
    return (
        db.query(UsageLimit)
        .filter(
            UsageLimit.plan_id == int(plan_id),
            UsageLimit.feature_key == feature_key,
        )
        .one_or_none()
    )


def get_plan_with_limits(db: Session, plan_id: int) -> Plan | None:
    return (
        db.query(Plan)
        .options(joinedload(Plan.usage_limits))
        .filter(Plan.id == int(plan_id))
        .one_or_none()
    )
