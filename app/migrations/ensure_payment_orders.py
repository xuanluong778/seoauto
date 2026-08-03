"""Additive migration: create payment_orders table if missing (no changes to existing tables)."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_payment_orders_table() -> bool:
    """
    Idempotent: creates payment_orders via SQLAlchemy metadata when absent.
    Existing tables and rows are never modified.
    """
    from app.models.payment_order import PaymentOrder  # noqa: F401
    from app.models.user import User  # noqa: F401

    _ = PaymentOrder, User
    Base.metadata.create_all(bind=engine, tables=[PaymentOrder.__table__])
    insp = inspect(engine)
    return "payment_orders" in insp.get_table_names()
