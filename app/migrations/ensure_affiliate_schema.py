"""Ensure affiliate tables/columns/indexes for commission idempotency and refund debt."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine


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


def _ensure_unique_index(name: str, ddl: str) -> bool:
    insp = inspect(engine)
    # SQLite / Postgres: check indexes across tables
    existing: set[str] = set()
    for table in insp.get_table_names():
        for idx in insp.get_indexes(table):
            if idx.get("name"):
                existing.add(str(idx["name"]))
    # Also unique constraints
    for table in insp.get_table_names():
        for uc in insp.get_unique_constraints(table):
            if uc.get("name"):
                existing.add(str(uc["name"]))
    if name in existing:
        return False
    with engine.begin() as conn:
        conn.execute(text(ddl))
    return True


def ensure_affiliate_schema() -> dict[str, object]:
    from app.models import affiliate as affiliate_models  # noqa: F401

    _ = affiliate_models
    Base.metadata.create_all(
        bind=engine,
        tables=[
            affiliate_models.AffiliateAccount.__table__,
            affiliate_models.AffiliateClick.__table__,
            affiliate_models.AffiliateReferral.__table__,
            affiliate_models.AffiliateCommission.__table__,
            affiliate_models.AffiliatePayout.__table__,
            affiliate_models.AffiliateSettings.__table__,
            affiliate_models.AffiliateAdjustment.__table__,
        ],
    )

    dialect = engine.dialect.name
    int_default = "INTEGER NOT NULL DEFAULT 0" if dialect == "sqlite" else "INTEGER NOT NULL DEFAULT 0"

    added_paid = _add_column_if_missing(
        "affiliate_commissions",
        "paid_amount",
        f"ALTER TABLE affiliate_commissions ADD COLUMN paid_amount {int_default}",
    )
    added_idem = _add_column_if_missing(
        "affiliate_commissions",
        "idempotency_key",
        "ALTER TABLE affiliate_commissions ADD COLUMN idempotency_key VARCHAR(96)",
    )

    # Backfill idempotency_key from order_id for legacy rows (ptx:*)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE affiliate_commissions "
                "SET idempotency_key = 'ptx:' || order_id "
                "WHERE idempotency_key IS NULL AND order_id IS NOT NULL AND order_id <> ''"
            )
        )

    # Unique index on idempotency_key (NULLs allowed / multiple NULLs OK in PG & SQLite)
    if dialect == "sqlite":
        created_uq = _ensure_unique_index(
            "uq_affiliate_commissions_idempotency_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_affiliate_commissions_idempotency_key "
            "ON affiliate_commissions (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL",
        )
        created_adj_uq = _ensure_unique_index(
            "uq_affiliate_adjustments_idempotency_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_affiliate_adjustments_idempotency_key "
            "ON affiliate_adjustments (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL",
        )
    else:
        created_uq = _ensure_unique_index(
            "uq_affiliate_commissions_idempotency_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_affiliate_commissions_idempotency_key "
            "ON affiliate_commissions (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL",
        )
        created_adj_uq = _ensure_unique_index(
            "uq_affiliate_adjustments_idempotency_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_affiliate_adjustments_idempotency_key "
            "ON affiliate_adjustments (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL",
        )

    insp = inspect(engine)
    names = set(insp.get_table_names())
    return {
        "affiliate_accounts": "affiliate_accounts" in names,
        "affiliate_commissions": "affiliate_commissions" in names,
        "affiliate_adjustments": "affiliate_adjustments" in names,
        "added_paid_amount": added_paid,
        "added_idempotency_key": added_idem,
        "unique_commission_idempotency": created_uq,
        "unique_adjustment_idempotency": created_adj_uq,
    }
