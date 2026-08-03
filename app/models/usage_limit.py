"""Per-plan feature quotas (Phase 1 — schema only)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UsageLimit(Base):
    __tablename__ = "usage_limits"
    __table_args__ = (
        UniqueConstraint("plan_id", "feature_key", "period", name="uq_usage_limits_plan_feature_period"),
        Index("ix_usage_limits_plan_id", "plan_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    period: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'monthly'"))
    is_hard_limit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    credit_cost_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plan: Mapped["Plan"] = relationship("Plan", back_populates="usage_limits")
