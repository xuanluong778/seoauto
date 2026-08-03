"""Admin-configurable credit policy — monthly bonus, caps, purchased/trial expiry."""

from __future__ import annotations

import json
import os
from typing import Any

from app.services.saas_hybrid_pricing import HYBRID_PLAN_DEFAULTS, PLAN_MONTHLY_BONUS_CREDITS

CAP_MULTIPLIER_DEFAULT = 2

PLAN_ACCUMULATION_CAPS_DEFAULT: dict[str, int] = {
    "starter": 1_000,
    "pro": 5_000,
    "agency": 14_000,
    "business": 36_000,
}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _json_env(name: str) -> dict[str, Any] | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def monthly_grant_for_plan(plan_slug: str) -> int:
    slug = str(plan_slug or "").strip().lower()
    override = _json_env("CREDIT_MONTHLY_GRANT_JSON")
    if override and slug in override:
        return max(0, int(override[slug]))
    return max(0, int(PLAN_MONTHLY_BONUS_CREDITS.get(slug, 0)))


def accumulation_cap_for_plan(plan_slug: str) -> int:
    slug = str(plan_slug or "").strip().lower()
    override = _json_env("CREDIT_PLAN_CAPS_JSON")
    if override and slug in override:
        return max(0, int(override[slug]))
    if slug in PLAN_ACCUMULATION_CAPS_DEFAULT:
        return PLAN_ACCUMULATION_CAPS_DEFAULT[slug]
    monthly = monthly_grant_for_plan(slug)
    mult = _int_env("CREDIT_CAP_MULTIPLIER", CAP_MULTIPLIER_DEFAULT)
    return monthly * mult if monthly > 0 else 0


def purchased_validity_months() -> int:
    return max(1, _int_env("CREDIT_PURCHASED_VALIDITY_MONTHS", 12))


def trial_validity_months() -> int:
    return max(1, _int_env("CREDIT_TRIAL_VALIDITY_MONTHS", 1))


def promo_validity_months() -> int:
    return max(1, _int_env("CREDIT_PROMO_VALIDITY_MONTHS", 3))


def policy_snapshot() -> dict[str, Any]:
    plans = {}
    for slug in HYBRID_PLAN_DEFAULTS:
        plans[slug] = {
            "monthly_grant": monthly_grant_for_plan(slug),
            "accumulation_cap": accumulation_cap_for_plan(slug),
            "name": HYBRID_PLAN_DEFAULTS[slug].get("name", slug),
        }
    return {
        "cap_multiplier": _int_env("CREDIT_CAP_MULTIPLIER", CAP_MULTIPLIER_DEFAULT),
        "purchased_validity_months": purchased_validity_months(),
        "trial_validity_months": trial_validity_months(),
        "promo_validity_months": promo_validity_months(),
        "plans": plans,
    }
