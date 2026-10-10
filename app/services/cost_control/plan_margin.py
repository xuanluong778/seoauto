"""Plan margin model for SaaS economics (NOT a product user quota).

Product billing SSOT = plan entitlement + credit wallet.
Category caps below are for worst-case GM modeling / internal ops only —
they must NOT block users who still have wallet credits.

Worst-case model (pack floor 77–100 VND/cr is sell price; API COGS uses economics blend):
  cost = H * HIGH_COGS_VND_PER_CR + (C - H) * LOW_COGS_VND_PER_CR
  require cost ≤ 0.30 * plan_month_price  (⇒ GM ≥ 70%)

H = sum of monthly expensive-feature credit caps for the plan (model input).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.user import User
from app.services.rbac import is_admin
from app.services.saas_hybrid_pricing import HYBRID_PLAN_DEFAULTS, PAID_PLAN_SLUGS

_LOG = logging.getLogger("cost_control.plan_margin")

# Blend COGS attribution (VND per credit burned) — matches economics defaults.
HIGH_COGS_VND_PER_CR = 250  # image / places / DFS / premium LLM blend
LOW_COGS_VND_PER_CR = 50  # local/cache/cheap paths for remaining pool
PACK_FLOOR_VND_PER_CR = 77
PACK_CEIL_VND_PER_CR = 100
TARGET_GM = 0.70

# Expensive burn categories → CreditLedger (module, action) matchers.
EXPENSIVE_CATEGORY_MATCHERS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "ai_image": (
        ("content_ai", "ai_image"),
        ("chatbot", "images_bundle"),
    ),
    "places_lead": (
        ("lead_scanner", None),  # any lead_scanner action
        ("google_map", None),
    ),
    "dataforseo_live": (
        ("keyword", "research_run"),
        ("keyword", "dataforseo_live"),
        ("keyword", "dataforseo_standard"),
        ("keyword", "volume_batch_100"),
        ("keyword", "serp"),
    ),
    "premium_llm": (
        ("content_ai", "article_short"),
        ("content_ai", "article_medium"),
        ("content_ai", "article_long"),
        ("content_ai", "addon_rewrite"),
        ("content_ai", "addon_research"),
        ("cau", "modal_rewrite"),
        ("cau", "seo_ai_fix"),
        ("audit", "technical_deep"),
    ),
}

# Monthly expensive credit caps per plan (sum = H). Tuned for GM ≥ 70%.
# starter H=450, pro H=560, agency H=780, business H=720
PLAN_EXPENSIVE_CREDIT_CAPS: dict[str, dict[str, int]] = {
    "starter": {
        "ai_image": 150,
        "places_lead": 150,
        "dataforseo_live": 100,
        "premium_llm": 50,
    },
    "pro": {
        "ai_image": 200,
        "places_lead": 160,
        "dataforseo_live": 120,
        "premium_llm": 80,
    },
    "agency": {
        "ai_image": 260,
        "places_lead": 220,
        "dataforseo_live": 180,
        "premium_llm": 120,
    },
    "business": {
        "ai_image": 240,
        "places_lead": 200,
        "dataforseo_live": 160,
        "premium_llm": 120,
    },
}

# Map gate provider/action/feature → expensive category
def resolve_expensive_category(
    *,
    provider: str | None = None,
    module: str | None = None,
    action: str | None = None,
    feature_key: str | None = None,
) -> str | None:
    mod = str(module or "").strip().lower()
    act = str(action or "").strip().lower()
    fk = str(feature_key or "").strip().lower()
    prov = str(provider or "").strip().lower()

    if act in ("ai_image", "images_bundle") or fk in ("ai_image", "content_ai_image", "images_bundle"):
        return "ai_image"
    if prov in ("google_places",) or mod == "lead_scanner" or fk.startswith("lead_"):
        return "places_lead"
    if prov == "dataforseo" or act in {
        "research_run",
        "dataforseo_live",
        "dataforseo_standard",
        "volume_batch_100",
        "serp",
        "search_volume",
    }:
        return "dataforseo_live"
    if mod in ("content_ai", "cau", "audit") or act.startswith("article_") or act in {
        "addon_rewrite",
        "addon_research",
        "modal_rewrite",
        "seo_ai_fix",
        "technical_deep",
        "suggest",
        "write",
        "chat_completion",
    }:
        if act not in ("google_image", "brief_suggest", "addon_outline", "addon_internal_link"):
            return "premium_llm"
    if fk in {
        "content_ai_write",
        "content_ai_article",
        "technical_audit",
        "addon_research",
        "keyword_research",
    }:
        if fk == "keyword_research":
            return "dataforseo_live"
        return "premium_llm"
    return None


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _matches(module: str, action: str, category: str) -> bool:
    for mod, act in EXPENSIVE_CATEGORY_MATCHERS.get(category, ()):
        if module != mod:
            continue
        if act is None or action == act:
            return True
    return False


def monthly_expensive_credits_used(
    db: Session,
    user_id: int,
    category: str,
) -> int:
    since = _month_start()
    rows = (
        db.query(CreditLedger.module, CreditLedger.action, CreditLedger.delta)
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.created_at >= since,
            CreditLedger.delta < 0,
        )
        .all()
    )
    total = 0
    for module, action, delta in rows:
        if _matches(str(module or ""), str(action or ""), category):
            total += abs(int(delta or 0))
    return total


def expensive_caps_for_plan(plan_slug: str | None) -> dict[str, int]:
    slug = str(plan_slug or "starter").strip().lower()
    if slug not in PLAN_EXPENSIVE_CREDIT_CAPS:
        slug = "starter"
    return dict(PLAN_EXPENSIVE_CREDIT_CAPS[slug])


def assert_expensive_feature_monthly_cap(
    db: Session,
    user: User,
    *,
    category: str | None,
    extra_credits: int = 0,
    plan_slug: str | None = None,
) -> None:
    """No-op product gate.

    Previously raised HTTP 429 (expensive_feature_monthly_cap) and blocked Pro
    users who still had wallet credits (e.g. premium_llm cap 80 vs 3329 balance).

    Credit wallet + plan entitlement are the SSOT. Emergency platform cost
    protection stays in saas_economics_guard (global expensive API block),
    not as a per-user category quota.

    Caps remain available via expensive_caps_for_plan() for margin modeling.
    Optional debug logging when COST_CONTROL_EXPENSIVE_CAPS_LOG=1.
    """
    if not category or is_admin(user):
        return
    if os.getenv("COST_CONTROL_EXPENSIVE_CAPS_LOG", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    try:
        caps = expensive_caps_for_plan(plan_slug)
        cap = int(caps.get(category, 0) or 0)
        if cap <= 0:
            return
        used = monthly_expensive_credits_used(db, int(user.id), category)
        extra = max(0, int(extra_credits or 0))
        if used + extra > cap:
            _LOG.info(
                "expensive_cap_observe_only category=%s used=%s extra=%s cap=%s plan=%s user_id=%s",
                category,
                used,
                extra,
                cap,
                plan_slug,
                getattr(user, "id", None),
            )
    except Exception:
        _LOG.debug("expensive_cap_observe_failed", exc_info=True)


def worst_case_plan_margin(
    plan_slug: str,
    *,
    high_cogs: int = HIGH_COGS_VND_PER_CR,
    low_cogs: int = LOW_COGS_VND_PER_CR,
) -> dict[str, Any]:
    """Compute worst-case GM under expensive hard caps (no plan price change)."""
    cfg = HYBRID_PLAN_DEFAULTS[plan_slug]
    price = int(cfg["month_price"])
    credits = int(cfg["credits_per_month"])
    caps = expensive_caps_for_plan(plan_slug)
    h = sum(int(v) for v in caps.values())
    h = min(h, credits)
    cost = h * int(high_cogs) + max(0, credits - h) * int(low_cogs)
    max_cost = int(price * (1.0 - TARGET_GM))
    gm = 0.0 if price <= 0 else max(0.0, 1.0 - (cost / float(price)))
    pack_liability_floor = credits * PACK_FLOOR_VND_PER_CR
    pack_liability_ceil = credits * PACK_CEIL_VND_PER_CR
    return {
        "plan_slug": plan_slug,
        "month_price": price,
        "included_credits": credits,
        "expensive_credit_cap_total": h,
        "expensive_caps": caps,
        "worst_case_cost_vnd": cost,
        "max_cost_for_70gm": max_cost,
        "gross_margin": round(gm, 4),
        "pass_70gm": cost <= max_cost and gm + 1e-9 >= TARGET_GM,
        "pack_liability_77": pack_liability_floor,
        "pack_liability_100": pack_liability_ceil,
        "pack_gm_at_100": round(1.0 - pack_liability_ceil / price, 4) if price else 0.0,
    }


def evaluate_all_plan_margins() -> dict[str, Any]:
    rows = [worst_case_plan_margin(slug) for slug in PAID_PLAN_SLUGS]
    return {
        "target_gm": TARGET_GM,
        "high_cogs_vnd_per_cr": HIGH_COGS_VND_PER_CR,
        "low_cogs_vnd_per_cr": LOW_COGS_VND_PER_CR,
        "plans": rows,
        "all_pass": all(bool(r["pass_70gm"]) for r in rows),
    }
