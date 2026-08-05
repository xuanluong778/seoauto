"""SePay webhook transaction log — idempotent by sepay_transaction_id."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SepayPaymentTransaction(Base):
    __tablename__ = "sepay_payment_transactions"
    __table_args__ = (
        UniqueConstraint("sepay_transaction_id", name="uq_sepay_payment_transactions_tx_id"),
        Index("ix_sepay_payment_transactions_order_code", "order_code"),
        Index("ix_sepay_payment_transactions_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sepay_transaction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transfer_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    transfer_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    process_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
