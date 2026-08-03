"""Create saas_economics_configs + saas_economics_state and seed defaults."""

from __future__ import annotations

import json

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db import Base, engine


def _seed_defaults() -> int:
    from app.models.saas_economics import SaasEconomicsConfig, SaasEconomicsState
    from app.services.saas_economics_service import DEFAULT_ECONOMICS_SETTINGS

    added = 0
    with Session(engine) as db:
        exists = db.get(SaasEconomicsConfig, "settings")
        if not exists:
            db.add(
                SaasEconomicsConfig(
                    key="settings",
                    value_json=json.dumps(DEFAULT_ECONOMICS_SETTINGS, ensure_ascii=False),
                )
            )
            added += 1
        state = db.get(SaasEconomicsState, 1)
        if state is None:
            db.add(SaasEconomicsState(id=1, expensive_api_blocked=False))
            added += 1
        if added:
            db.commit()
    return added


def ensure_saas_economics() -> dict[str, object]:
    from app.models.saas_economics import SaasEconomicsConfig, SaasEconomicsState  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[SaasEconomicsConfig.__table__, SaasEconomicsState.__table__],
    )
    insp = inspect(engine)
    names = set(insp.get_table_names())
    seeded = _seed_defaults() if "saas_economics_configs" in names else 0
    return {
        "saas_economics_configs": "saas_economics_configs" in names,
        "saas_economics_state": "saas_economics_state" in names,
        "seeded": seeded,
    }
