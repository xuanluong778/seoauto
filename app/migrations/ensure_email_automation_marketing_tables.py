"""Additive tables for Email Automation + Email Marketing.

ALTER COLUMN uses short lock_timeout + autocommit so boot never leaves
idle-in-transaction AccessExclusiveLock on email tables (which blocks SELECTs).
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def _add_column_if_missing(insp, table: str, column: str, ddl: str) -> bool:
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False
    if column in cols:
        return False
    # Autocommit + short lock wait: never hold AccessExclusive across requests.
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            try:
                conn.execute(text("SET lock_timeout = '2s'"))
                conn.execute(text("SET statement_timeout = '8s'"))
            except Exception:
                pass
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}"))
            except Exception:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        return True
    except Exception as exc:
        _LOG.warning("email schema add column skipped %s.%s: %s", table, column, exc)
        return False


def ensure_email_automation_marketing_tables() -> dict[str, object]:
    from app.models.email_automation_marketing import (
        EmailAutomationTemplate,
        EmailMarketingCampaign,
        EmailMarketingUnsubscribe,
        EmailSend,
        EmailSendLog,
    )

    insp = inspect(engine)
    created: list[str] = []
    for model in (
        EmailAutomationTemplate,
        EmailMarketingCampaign,
        EmailMarketingUnsubscribe,
        EmailSend,
        EmailSendLog,
    ):
        if model.__tablename__ not in insp.get_table_names():
            Base.metadata.create_all(bind=engine, tables=[model.__table__])
            created.append(model.__tablename__)

    insp = inspect(engine)
    altered: list[str] = []
    checks = [
        ("email_automation_templates", "preheader_template", "preheader_template VARCHAR(180)"),
        ("email_marketing_campaigns", "preheader", "preheader VARCHAR(180)"),
        ("email_marketing_campaigns", "timezone", "timezone VARCHAR(64) DEFAULT 'Asia/Ho_Chi_Minh'"),
        ("email_marketing_campaigns", "cancelled_at", "cancelled_at TIMESTAMPTZ"),
        ("email_sends", "bounced_at", "bounced_at TIMESTAMPTZ"),
        ("email_sends", "unsubscribed_at", "unsubscribed_at TIMESTAMPTZ"),
    ]
    dialect = engine.dialect.name
    for table, col, ddl in checks:
        use_ddl = ddl
        if dialect == "sqlite":
            use_ddl = ddl.replace("TIMESTAMPTZ", "DATETIME")
        if _add_column_if_missing(insp, table, col, use_ddl):
            altered.append(f"{table}.{col}")
            insp = inspect(engine)

    return {"created_tables": created, "altered_columns": altered, "dialect": dialect}
