"""Deploy-time: SePay webhook event store + idempotency / lock-friendly indexes."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import engine

_LOG = logging.getLogger(__name__)


def _has_table(name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in inspect(engine).get_columns(table))


def schema_status() -> dict[str, Any]:
    missing: list[str] = []
    if not _has_table("sepay_webhook_events"):
        missing.append("table:sepay_webhook_events")
    for col in ("process_status", "failure_reason", "idempotency_key"):
        # process fields on sepay_payment_transactions (optional enrichment)
        if _has_table("sepay_payment_transactions") and not _has_column(
            "sepay_payment_transactions", col if col != "idempotency_key" else "process_status"
        ):
            if col == "idempotency_key":
                continue
            if not _has_column("sepay_payment_transactions", col):
                missing.append(f"sepay_payment_transactions.{col}")
    for col in ("process_status", "failure_reason", "idempotency_key"):
        if col == "idempotency_key":
            continue
        if _has_table("sepay_payment_transactions") and not _has_column(
            "sepay_payment_transactions", col
        ):
            if f"sepay_payment_transactions.{col}" not in missing:
                missing.append(f"sepay_payment_transactions.{col}")
    return {
        "ok": _has_table("sepay_webhook_events"),
        "missing": missing,
        "sepay_webhook_events": _has_table("sepay_webhook_events"),
    }


def apply_sepay_webhook_idempotency_migration() -> dict[str, Any]:
    """Create webhook events table + enrich sepay_payment_transactions (deploy-time)."""
    import app.models.user  # noqa: F401
    from app.db import Base
    from app.models.sepay_webhook_event import SepayWebhookEvent  # noqa: F401
    from app.models.sepay_payment_transaction import SepayPaymentTransaction  # noqa: F401

    Base.metadata.create_all(bind=engine, tables=[SepayWebhookEvent.__table__])

    applied: list[str] = []
    # Enrich sepay_payment_transactions with processing status
    for col, ddl in [
        (
            "process_status",
            "ALTER TABLE sepay_payment_transactions ADD COLUMN process_status VARCHAR(24)",
        ),
        (
            "failure_reason",
            "ALTER TABLE sepay_payment_transactions ADD COLUMN failure_reason VARCHAR(512)",
        ),
        (
            "idempotency_key",
            "ALTER TABLE sepay_payment_transactions ADD COLUMN idempotency_key VARCHAR(128)",
        ),
    ]:
        if _has_table("sepay_payment_transactions") and not _has_column(
            "sepay_payment_transactions", col
        ):
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(f"sepay_payment_transactions.{col}")
            except Exception as exc:
                _LOG.warning("add %s failed: %s", col, exc)

    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_webhook_events_idempotency "
            "ON sepay_webhook_events (idempotency_key)",
            # One durable event row per SePay bank transaction id when present
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_webhook_events_provider_tx "
            "ON sepay_webhook_events (provider_transaction_id) "
            "WHERE provider_transaction_id IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_tx_idempotency "
            "ON sepay_payment_transactions (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL",
            # sepay_payment_transactions.sepay_transaction_id already UNIQUE
            # payment_orders.order_code already UNIQUE
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_provider_tx "
            "ON payment_transactions (provider, provider_transaction_id) "
            "WHERE provider_transaction_id IS NOT NULL",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except Exception as exc:
                _LOG.warning("index: %s", exc)

    st = schema_status()
    _LOG.info("sepay_webhook_idempotency migration applied=%s status=%s", applied, st)
    return {"applied": applied, "status": st}


def ensure_sepay_webhook_idempotency() -> None:
    apply_sepay_webhook_idempotency_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_sepay_webhook_idempotency_migration())
