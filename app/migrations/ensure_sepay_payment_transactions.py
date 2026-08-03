"""Additive migration: create sepay_payment_transactions table if missing."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_sepay_payment_transactions_table() -> bool:
    """
    Idempotent: creates sepay_payment_transactions only when absent.
    Does not modify payment_transactions or any other existing table.
    """
    from app.models.sepay_payment_transaction import SepayPaymentTransaction  # noqa: F401

    _ = SepayPaymentTransaction
    Base.metadata.create_all(bind=engine, tables=[SepayPaymentTransaction.__table__])
    insp = inspect(engine)
    return "sepay_payment_transactions" in insp.get_table_names()
