"""Additive migrations for payment activation columns and related tables."""

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


def _timestamp_sql_type() -> str:
    if engine.dialect.name == "sqlite":
        return "DATETIME"
    return "TIMESTAMP WITH TIME ZONE"


def _text_sql_type() -> str:
    if engine.dialect.name == "sqlite":
        return "TEXT"
    return "TEXT"


def ensure_payment_order_activation_columns() -> dict[str, bool]:
    """Add activation tracking columns to payment_orders without touching existing rows."""
    from app.models.payment_order import PaymentOrder  # noqa: F401

    _ = PaymentOrder
    Base.metadata.create_all(bind=engine, tables=[PaymentOrder.__table__])

    ts = _timestamp_sql_type()
    txt = _text_sql_type()
    changed = {
        "activation_status": _add_column_if_missing(
            "payment_orders",
            "activation_status",
            "ALTER TABLE payment_orders ADD COLUMN activation_status VARCHAR(24)",
        ),
        "activation_error": _add_column_if_missing(
            "payment_orders",
            "activation_error",
            f"ALTER TABLE payment_orders ADD COLUMN activation_error {txt}",
        ),
        "activation_result_json": _add_column_if_missing(
            "payment_orders",
            "activation_result_json",
            f"ALTER TABLE payment_orders ADD COLUMN activation_result_json {txt}",
        ),
        "activated_at": _add_column_if_missing(
            "payment_orders",
            "activated_at",
            f"ALTER TABLE payment_orders ADD COLUMN activated_at {ts}",
        ),
    }
    return changed


def ensure_credit_ledger_expires_column() -> bool:
    from app.models.credit_ledger import CreditLedger  # noqa: F401

    _ = CreditLedger
    ts = _timestamp_sql_type()
    return _add_column_if_missing(
        "credit_ledgers",
        "expires_at",
        f"ALTER TABLE credit_ledgers ADD COLUMN expires_at {ts}",
    )


def ensure_user_quota_addons_table() -> bool:
    from app.models.user_quota_addon import UserQuotaAddon  # noqa: F401

    _ = UserQuotaAddon
    Base.metadata.create_all(bind=engine, tables=[UserQuotaAddon.__table__])
    insp = inspect(engine)
    return "user_quota_addons" in insp.get_table_names()


def ensure_billing_activation_schema() -> dict[str, object]:
    return {
        "payment_order_columns": ensure_payment_order_activation_columns(),
        "credit_ledger_expires": ensure_credit_ledger_expires_column(),
        "user_quota_addons": ensure_user_quota_addons_table(),
    }
