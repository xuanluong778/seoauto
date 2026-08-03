"""Add module/action/request audit columns to credit_ledgers."""

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


def ensure_credit_ledger_audit_columns() -> dict[str, bool]:
    if engine.dialect.name == "sqlite":
        int_type = "INTEGER"
        varchar64 = "VARCHAR(64)"
        varchar32 = "VARCHAR(32)"
    else:
        int_type = "INTEGER"
        varchar64 = "VARCHAR(64)"
        varchar32 = "VARCHAR(32)"
    return {
        "module": _add_column_if_missing(
            "credit_ledgers",
            "module",
            f"ALTER TABLE credit_ledgers ADD COLUMN module {varchar64}",
        ),
        "action": _add_column_if_missing(
            "credit_ledgers",
            "action",
            f"ALTER TABLE credit_ledgers ADD COLUMN action {varchar64}",
        ),
        "credit_used": _add_column_if_missing(
            "credit_ledgers",
            "credit_used",
            f"ALTER TABLE credit_ledgers ADD COLUMN credit_used {int_type}",
        ),
        "request_id": _add_column_if_missing(
            "credit_ledgers",
            "request_id",
            f"ALTER TABLE credit_ledgers ADD COLUMN request_id {varchar64}",
        ),
        "source": _add_column_if_missing(
            "credit_ledgers",
            "source",
            f"ALTER TABLE credit_ledgers ADD COLUMN source {varchar32}",
        ),
    }
