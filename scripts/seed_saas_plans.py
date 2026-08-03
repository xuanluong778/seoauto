#!/usr/bin/env python3
"""Seed SaaS plans + usage_limits (Phase 1 — idempotent, no enforcement)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local", override=True)

from app.db import SessionLocal
from app.models.plan import Plan
from app.models.subscription import Subscription  # noqa: F401 — resolve Plan.subscriptions
from app.models.usage_limit import UsageLimit
from app.services.plan_quota_registry import iter_usage_limits
from app.services.saas_hybrid_pricing import FREE_TRIAL_HYBRID_NOTE, HYBRID_PLAN_DEFAULTS

PLANS: list[dict[str, Any]] = [
    {
        "slug": "free_trial_5d",
        "name": "Dùng tool 5 ngày miễn phí",
        "description": "Free Trial 5 ngày — BYOK: cần API key cá nhân để dùng AI.",
        "price_amount": 0,
        "currency": "VND",
        "billing_cycle": "none",
        "is_active": True,
        "is_public": True,
        "sort_order": 0,
        "metadata_json": json.dumps(
            {
                "trial_days": 5,
                "note": FREE_TRIAL_HYBRID_NOTE,
                "byok": True,
                "hybrid_demo": True,
            },
            ensure_ascii=False,
        ),
    },
    {
        "slug": "free_trial",
        "name": "Miễn phí (legacy)",
        "description": "Deprecated — dùng free_trial_5d.",
        "price_amount": 0,
        "currency": "VND",
        "billing_cycle": "none",
        "is_active": False,
        "is_public": False,
        "sort_order": 99,
        "metadata_json": json.dumps({"deprecated": True}, ensure_ascii=False),
    },
    {
        "slug": "starter",
        "name": "Basic",
        "price_amount": HYBRID_PLAN_DEFAULTS["starter"]["month_price"],
        "currency": "VND",
        "billing_cycle": "monthly",
        "is_active": True,
        "is_public": True,
        "sort_order": 1,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "price_amount": HYBRID_PLAN_DEFAULTS["pro"]["month_price"],
        "currency": "VND",
        "billing_cycle": "monthly",
        "is_active": True,
        "is_public": True,
        "sort_order": 2,
    },
    {
        "slug": "agency",
        "name": "Agency",
        "price_amount": HYBRID_PLAN_DEFAULTS["agency"]["month_price"],
        "currency": "VND",
        "billing_cycle": "monthly",
        "is_active": True,
        "is_public": True,
        "sort_order": 3,
    },
    {
        "slug": "business",
        "name": "Business",
        "description": "Công ty, team lớn",
        "price_amount": HYBRID_PLAN_DEFAULTS["business"]["month_price"],
        "currency": "VND",
        "billing_cycle": "monthly",
        "is_active": True,
        "is_public": True,
        "sort_order": 4,
    },
    {
        "slug": "unlimited",
        "name": "Unlimited",
        "price_amount": 1_165_000,
        "currency": "VND",
        "billing_cycle": "monthly",
        "is_active": False,
        "is_public": False,
        "sort_order": 50,
    },
]

# (plan_slug, feature_key, limit_value, period, is_hard_limit) — from plan_quota_registry
USAGE_LIMITS: list[tuple[str, str, int, str, bool]] = iter_usage_limits()

PLAN_LIMIT_KEYS: dict[str, frozenset[tuple[str, str]]] = {
    slug: frozenset((fk, period) for ps, fk, _, period, _ in USAGE_LIMITS if ps == slug)
    for slug in {ps for ps, *_ in USAGE_LIMITS}
}

PLAN_FIELDS = (
    "name",
    "description",
    "price_amount",
    "currency",
    "billing_cycle",
    "is_active",
    "is_public",
    "sort_order",
    "metadata_json",
)
LIMIT_FIELDS = ("limit_value", "period", "is_hard_limit")


def _upsert_plan(db, data: dict[str, Any]) -> tuple[Plan, str]:
    slug = data["slug"]
    plan = db.query(Plan).filter(Plan.slug == slug).one_or_none()
    if plan is None:
        plan = Plan(slug=slug, **{k: data.get(k) for k in PLAN_FIELDS})
        db.add(plan)
        db.flush()
        return plan, "created"
    changed = False
    for key in PLAN_FIELDS:
        new_val = data.get(key)
        if getattr(plan, key) != new_val:
            setattr(plan, key, new_val)
            changed = True
    return plan, "updated" if changed else "unchanged"


def _upsert_usage_limit(
    db,
    plan_id: int,
    feature_key: str,
    limit_value: int,
    period: str,
    is_hard_limit: bool,
) -> str:
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
        return "created"
    changed = False
    for key, val in (
        ("limit_value", limit_value),
        ("period", period),
        ("is_hard_limit", is_hard_limit),
    ):
        if getattr(row, key) != val:
            setattr(row, key, val)
            changed = True
    return "updated" if changed else "unchanged"


def _prune_stale_limits(db, plan: Plan, allowed: frozenset[tuple[str, str]]) -> None:
    for row in db.query(UsageLimit).filter(UsageLimit.plan_id == plan.id).all():
        if (row.feature_key, row.period) not in allowed:
            db.delete(row)
            print(f"  {plan.slug}: removed stale limit {row.feature_key}/{row.period}")


def main() -> None:
    db = SessionLocal()
    try:
        plans_by_slug: dict[str, Plan] = {}
        print("Plans:")
        for data in PLANS:
            plan, status = _upsert_plan(db, data)
            plans_by_slug[data["slug"]] = plan
            print(f"  {data['slug']}: {status}")

        print("Usage limits:")
        for plan_slug, feature_key, limit_value, period, is_hard_limit in USAGE_LIMITS:
            plan = plans_by_slug[plan_slug]
            status = _upsert_usage_limit(
                db, plan.id, feature_key, limit_value, period, is_hard_limit
            )
            print(f"  {plan_slug}/{feature_key}/{period}: {status}")

        for slug, allowed in PLAN_LIMIT_KEYS.items():
            plan = plans_by_slug.get(slug)
            if plan is not None:
                _prune_stale_limits(db, plan, allowed)

        db.commit()
        print("OK — seed_saas_plans completed (idempotent).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
