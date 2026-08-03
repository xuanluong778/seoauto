"""Schema + plan seed for 3-day SaaS trial."""

from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import engine
from app.models.plan import Plan


def _ts_type() -> str:
    return "TIMESTAMP WITH TIME ZONE" if engine.dialect.name != "sqlite" else "DATETIME"


def _ensure_user_trial_columns() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    ts = _ts_type()
    with engine.begin() as conn:
        if "trial_started_at" not in cols:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN trial_started_at {ts}"))
        if "trial_expires_at" not in cols:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN trial_expires_at {ts}"))
        if "trial_used" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN trial_used BOOLEAN NOT NULL DEFAULT false"))
        if "trial_credit_used" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN trial_credit_used INTEGER NOT NULL DEFAULT 0"))


def _ensure_trial_tables() -> None:
    from app.models.saas_trial import SaasTrialClaim, SaasTrialDailyUsage  # noqa: F401
    from app.db import Base

    SaasTrialDailyUsage.__table__.create(bind=engine, checkfirst=True)
    SaasTrialClaim.__table__.create(bind=engine, checkfirst=True)


def _ensure_trial_plan(db: Session) -> None:
    row = db.query(Plan).filter(Plan.slug == "trial_3d").one_or_none()
    meta = json.dumps({"trial_days": 3, "plan_kind": "trial", "note": "Dùng thử 3 ngày — cần mua credit"})
    if row is None:
        db.add(
            Plan(
                slug="trial_3d",
                name="Dùng thử 3 ngày",
                description="Trial 3 ngày — Content AI, Auto Update, SEO Score, Technical Audit",
                price_amount=0,
                is_active=True,
                is_public=False,
                metadata_json=meta,
            )
        )
        db.flush()
    else:
        row.name = "Dùng thử 3 ngày"
        row.metadata_json = meta
        row.is_active = True


def ensure_saas_trial_3d() -> None:
    _ensure_user_trial_columns()
    _ensure_trial_tables()
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        _ensure_trial_plan(db)
        db.commit()
    finally:
        db.close()
