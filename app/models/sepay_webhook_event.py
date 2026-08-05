"""Raw SePay webhook events — durable log before business processing."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# received → processing → processed | failed | skipped
SEPay_EVENT_STATUSES = frozenset(
    {"received", "processing", "processed", "failed", "skipped"}
)


class SepayWebhookEvent(Base):
    """
    Persist every authenticated webhook payload before fulfillment.
    Unique idempotency_key ensures retries never re-apply business logic.
    """

    __tablename__ = "sepay_webhook_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_sepay_webhook_events_idempotency"),
        # Partial unique on provider_transaction_id is applied in PG migration
        # (null/hash-only events may omit it); non-null should be one row per bank tx.
        Index("ix_sepay_webhook_events_provider_tx", "provider_transaction_id"),
        Index("ix_sepay_webhook_events_order_code", "order_code"),
        Index("ix_sepay_webhook_events_status", "process_status"),
        Index("ix_sepay_webhook_events_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transfer_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    process_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="received")
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
