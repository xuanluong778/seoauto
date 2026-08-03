"""Credit grant buckets — remaining balance per source with optional expiry."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CREDIT_SOURCE_TYPES = frozenset(
    {
        "monthly_bonus",
        "plan_monthly",  # legacy alias → normalized to monthly_bonus
        "purchased",
        "admin_grant",
        "admin_adjustment",  # legacy
        "trial",
        "promo",
        "refund",
    }
)

CREDIT_BUCKET_STATUSES = frozenset({"active", "locked", "expired", "consumed"})


class CreditLedgerEntry(Base):
    """
    One grant bucket. Consumption deducts from remaining_amount (FIFO by expired_at).
    Only buckets with status=active and remaining>0 are spendable.
    """

    __tablename__ = "credit_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active", index=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
