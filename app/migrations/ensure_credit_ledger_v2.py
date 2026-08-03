"""Create credit_ledger_entries and migrate legacy user.credit_balance into buckets."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


def _timestamp_sql_type() -> str:
    if engine.dialect.name == "sqlite":
        return "DATETIME"
    return "TIMESTAMP WITH TIME ZONE"


def ensure_credit_ledger_entries_table() -> bool:
    from app.models.credit_ledger_entry import CreditLedgerEntry  # noqa: F401

    _ = CreditLedgerEntry
    Base.metadata.create_all(bind=engine, tables=[CreditLedgerEntry.__table__])
    insp = inspect(engine)
    return "credit_ledger_entries" in insp.get_table_names()


def migrate_legacy_credit_balances(db: Session) -> int:
    """
    For each user with credit_balance > sum(active bucket remaining), create
    admin_adjustment bucket so no credit is lost.
    """
    from app.models.credit_ledger_entry import CreditLedgerEntry
    from app.models.user import User
    from app.services.credits import get_available_balance, grant_credits

    migrated = 0
    users = db.query(User).filter(User.credit_balance > 0).all()
    for user in users:
        stored = int(user.credit_balance or 0)
        if stored <= 0:
            continue
        available = get_available_balance(db, user.id, sync=False)
        gap = stored - available
        if gap <= 0:
            continue
        grant_credits(
            db,
            user_id=user.id,
            amount=gap,
            reason="legacy_balance_migration",
            source_type="admin_adjustment",
            note="legacy_balance_migration",
            expired_at=None,
        )
        migrated += 1
    if migrated:
        db.commit()
        logger.info("credit_ledger_v2 migrated legacy balances for %s users", migrated)
    return migrated


def ensure_credit_ledger_v2() -> dict[str, object]:
    created = ensure_credit_ledger_entries_table()
    migrated = 0
    backfilled = 0
    db = SessionLocal()
    try:
        migrated = migrate_legacy_credit_balances(db)
        from app.services.credits import credits_enforced

        if credits_enforced():
            from app.services.credits import backfill_activation_credits

            backfilled = backfill_activation_credits(db)
    finally:
        db.close()
    return {
        "credit_ledger_entries_table": created,
        "legacy_users_migrated": migrated,
        "activation_credits_backfilled": backfilled,
    }
