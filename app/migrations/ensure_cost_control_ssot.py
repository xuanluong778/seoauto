"""Sync locked credit_cost_configs to CREDIT_SSOT_REVISION (idempotent)."""

from __future__ import annotations

import logging

from app.db import SessionLocal

_LOG = logging.getLogger(__name__)
_SETTINGS_KEY = "credit_ssot_revision"


def ensure_cost_control_ssot() -> dict[str, object]:
    from app.models.credit_cost_config import CreditCostConfig
    from app.models.plan import Plan  # noqa: F401
    from app.models.saas_economics import SaasEconomicsConfig
    from app.models.subscription import Subscription  # noqa: F401
    from app.services.credit_cost_registry import (
        CREDIT_SSOT_REVISION,
        DEFAULT_CREDIT_COSTS,
        SSOT_LOCK_KEYS,
        invalidate_credit_cost_cache,
    )

    db = SessionLocal()
    updated = 0
    seeded = 0
    try:
        row = (
            db.query(SaasEconomicsConfig)
            .filter(SaasEconomicsConfig.key == _SETTINGS_KEY)
            .one_or_none()
        )
        current = 0
        if row is not None:
            try:
                current = int(str(row.value_json or "0").strip() or 0)
            except (TypeError, ValueError):
                current = 0
        force = current < int(CREDIT_SSOT_REVISION)

        by_key = {(str(r["module"]), str(r["action"])): r for r in DEFAULT_CREDIT_COSTS}
        for (mod, act), spec in by_key.items():
            existing = (
                db.query(CreditCostConfig)
                .filter(CreditCostConfig.module == mod, CreditCostConfig.action == act)
                .one_or_none()
            )
            if existing is None:
                db.add(
                    CreditCostConfig(
                        module=mod,
                        action=act,
                        credit_cost=int(spec["credit_cost"]),
                        cache_discount_percent=int(spec.get("cache_discount_percent", 80)),
                        cache_zero_cost=bool(spec.get("cache_zero_cost", False)),
                        label=str(spec.get("label") or "")[:200] or None,
                        description=str(spec.get("description") or "")[:2000] or None,
                        is_active=True,
                    )
                )
                seeded += 1
                continue
            if force and (mod, act) in SSOT_LOCK_KEYS:
                existing.credit_cost = int(spec["credit_cost"])
                if "cache_discount_percent" in spec:
                    existing.cache_discount_percent = int(spec["cache_discount_percent"])
                if "cache_zero_cost" in spec:
                    existing.cache_zero_cost = bool(spec["cache_zero_cost"])
                if spec.get("label"):
                    existing.label = str(spec["label"])[:200]
                updated += 1

        if row is None:
            db.add(SaasEconomicsConfig(key=_SETTINGS_KEY, value_json=str(CREDIT_SSOT_REVISION)))
        else:
            row.value_json = str(CREDIT_SSOT_REVISION)
        db.commit()
        invalidate_credit_cost_cache()
        _LOG.info(
            "ensure_cost_control_ssot revision=%s seeded=%s updated=%s",
            CREDIT_SSOT_REVISION,
            seeded,
            updated,
        )
        return {
            "revision": CREDIT_SSOT_REVISION,
            "seeded": seeded,
            "updated": updated,
            "forced": force,
        }
    except Exception:
        db.rollback()
        _LOG.exception("ensure_cost_control_ssot failed")
        raise
    finally:
        db.close()
