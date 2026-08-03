"""Bonus quota grants from paid add-ons (article packs, etc.)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserQuotaAddon(Base):
    __tablename__ = "user_quota_addons"
    __table_args__ = (
        UniqueConstraint("payment_order_id", name="uq_user_quota_addons_payment_order"),
        Index("ix_user_quota_addons_user_feature", "user_id", "feature_key"),
        Index("ix_user_quota_addons_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    payment_order_id: Mapped[int] = mapped_column(
        ForeignKey("payment_orders.id", ondelete="RESTRICT"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    bonus_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
