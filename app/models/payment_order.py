"""Bank-transfer payment orders (checkout SKUs from billing catalog)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PAYMENT_ORDER_STATUSES = frozenset(
    {"pending", "paid", "expired", "partial_paid", "cancelled", "refunded"}
)
PAYMENT_ORDER_ACTIVATION_STATUSES = frozenset(
    {"activated", "activation_failed"}
)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        UniqueConstraint("order_code", name="uq_payment_orders_order_code"),
        Index("ix_payment_orders_user_id", "user_id"),
        Index("ix_payment_orders_status", "status"),
        Index("ix_payment_orders_product_code", "product_code"),
        Index("ix_payment_orders_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    order_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    bank_code: Mapped[str] = mapped_column(String(16), nullable=False)
    bank_account: Mapped[str] = mapped_column(String(32), nullable=False)
    bank_holder: Mapped[str] = mapped_column(String(160), nullable=False)
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    activation_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    activation_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
