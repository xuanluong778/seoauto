"""Create credit_cost_configs and seed default module/action costs."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def _seed_defaults() -> int:
    from app.models.credit_cost_config import CreditCostConfig
    from app.services.credit_cost_registry import DEFAULT_CREDIT_COSTS

    from sqlalchemy.orm import Session

    added = 0
    with Session(engine) as db:
        for row in DEFAULT_CREDIT_COSTS:
            exists = (
                db.query(CreditCostConfig.id)
                .filter(
                    CreditCostConfig.module == row["module"],
                    CreditCostConfig.action == row["action"],
                )
                .first()
            )
            if exists:
                continue
            db.add(
                CreditCostConfig(
                    module=row["module"],
                    action=row["action"],
                    credit_cost=int(row["credit_cost"]),
                    cache_discount_percent=int(row.get("cache_discount_percent", 80)),
                    cache_zero_cost=bool(row.get("cache_zero_cost", False)),
                    label=str(row.get("label") or "")[:200] or None,
                    description=str(row.get("description") or "")[:2000] or None,
                    is_active=True,
                )
            )
            added += 1
        if added:
            db.commit()
    return added


def ensure_credit_cost_configs() -> dict[str, object]:
    from app.models.credit_cost_config import CreditCostConfig  # noqa: F401

    Base.metadata.create_all(bind=engine, tables=[CreditCostConfig.__table__])
    insp = inspect(engine)
    names = set(insp.get_table_names())
    seeded = _seed_defaults() if "credit_cost_configs" in names else 0
    return {"credit_cost_configs": "credit_cost_configs" in names, "seeded": seeded}
