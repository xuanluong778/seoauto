"""Credit ledger v3 — bucket status (active/locked/expired/consumed) + monthly_bonus alias."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine

logger = logging.getLogger(__name__)

MONTHLY_BONUS_SOURCES = ("monthly_bonus", "plan_monthly")


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text(ddl))
    return True


def ensure_credit_ledger_v3_columns() -> dict[str, bool]:
    ts = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name != "sqlite" else "DATETIME"
    return {
        "status": _add_column_if_missing(
            "credit_ledger_entries",
            "status",
            "ALTER TABLE credit_ledger_entries ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active'",
        ),
        "locked_at": _add_column_if_missing(
            "credit_ledger_entries",
            "locked_at",
            f"ALTER TABLE credit_ledger_entries ADD COLUMN locked_at {ts}",
        ),
    }


def _backfill_bucket_status(db: Session) -> int:
    from app.models.credit_ledger_entry import CreditLedgerEntry

    rows = db.query(CreditLedgerEntry).filter(CreditLedgerEntry.status.is_(None)).all()
    updated = 0
    for row in rows:
        rem = int(row.remaining_amount or 0)
        if rem <= 0:
            row.status = "consumed"
        else:
            row.status = "active"
        updated += 1
    if updated:
        db.commit()
    return updated


def _normalize_plan_monthly_source(db: Session) -> int:
    from app.models.credit_ledger_entry import CreditLedgerEntry

    rows = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.source_type == "plan_monthly")
        .all()
    )
    for row in rows:
        row.source_type = "monthly_bonus"
    if rows:
        db.commit()
        return len(rows)
    return 0


def ensure_credit_ledger_v3() -> dict[str, object]:
    cols = ensure_credit_ledger_v3_columns()
    db = SessionLocal()
    try:
        backfilled = _backfill_bucket_status(db)
        migrated_sources = _normalize_plan_monthly_source(db)
    finally:
        db.close()
    logger.info(
        "credit_ledger_v3 cols=%s backfilled=%s source_migrated=%s",
        cols,
        backfilled,
        migrated_sources,
    )
    return {
        **cols,
        "status_backfilled": backfilled,
        "plan_monthly_renamed": migrated_sources,
    }
