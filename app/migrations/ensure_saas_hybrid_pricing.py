"""Idempotent sync hybrid pricing defaults into plans table (safe — no subscription wipe)."""

from __future__ import annotations

import json
import logging

from app.db import SessionLocal
from app.models.plan import Plan
from app.services.saas_hybrid_pricing import (
    HYBRID_PLAN_DEFAULTS,
    HYBRID_PRICING_REVISION,
    FREE_TRIAL_HYBRID_NOTE,
)

_LOG = logging.getLogger(__name__)
_SYNCED_REVISION: int | None = None


def _parse_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def ensure_saas_hybrid_pricing() -> None:
    global _SYNCED_REVISION
    if _SYNCED_REVISION == HYBRID_PRICING_REVISION:
        return

    db = SessionLocal()
    changed = 0
    try:
        for slug, cfg in HYBRID_PLAN_DEFAULTS.items():
            plan = db.query(Plan).filter(Plan.slug == slug).one_or_none()
            if plan is None:
                continue
            want_price = int(cfg["month_price"])
            meta = _parse_meta(plan.metadata_json)
            prev_rev = int(meta.get("hybrid_pricing_revision") or 0)
            if plan.price_amount != want_price or prev_rev < HYBRID_PRICING_REVISION:
                plan.price_amount = want_price
                meta["hybrid_pricing_revision"] = HYBRID_PRICING_REVISION
                meta["hybrid_model"] = True
                meta["credits_per_month_default"] = int(cfg["credits_per_month"])
                plan.metadata_json = json.dumps(meta, ensure_ascii=False)
                changed += 1

        trial = db.query(Plan).filter(Plan.slug == "free_trial_5d").one_or_none()
        if trial is not None:
            meta = _parse_meta(trial.metadata_json)
            if meta.get("hybrid_demo") is not True:
                meta["hybrid_demo"] = True
                meta["byok"] = True
                meta["note"] = FREE_TRIAL_HYBRID_NOTE
                meta["trial_days"] = int(meta.get("trial_days") or 5)
                trial.metadata_json = json.dumps(meta, ensure_ascii=False)
                changed += 1

        if changed:
            db.commit()
            _LOG.info("ensure_saas_hybrid_pricing: updated %s plan row(s)", changed)
        else:
            db.rollback()
        _SYNCED_REVISION = HYBRID_PRICING_REVISION
    except Exception:
        db.rollback()
        _LOG.exception("ensure_saas_hybrid_pricing failed")
        raise
    finally:
        db.close()
