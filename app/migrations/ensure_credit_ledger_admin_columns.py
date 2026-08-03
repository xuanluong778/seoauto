"""Add admin grant metadata columns to credit_ledgers."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


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


def ensure_credit_ledger_admin_columns() -> dict[str, bool]:
    if engine.dialect.name == "sqlite":
        int_type = "INTEGER"
    else:
        int_type = "INTEGER"
    txt = "TEXT"
    return {
        "admin_id": _add_column_if_missing(
            "credit_ledgers",
            "admin_id",
            f"ALTER TABLE credit_ledgers ADD COLUMN admin_id {int_type}",
        ),
        "credit_type": _add_column_if_missing(
            "credit_ledgers",
            "credit_type",
            f"ALTER TABLE credit_ledgers ADD COLUMN credit_type VARCHAR(32)",
        ),
        "grant_reason": _add_column_if_missing(
            "credit_ledgers",
            "grant_reason",
            f"ALTER TABLE credit_ledgers ADD COLUMN grant_reason {txt}",
        ),
    }

