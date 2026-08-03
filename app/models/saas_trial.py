"""3-day SaaS trial — daily usage and abuse-prevention claims."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SaasTrialDailyUsage(Base):
    __tablename__ = "saas_trial_daily_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "usage_date", "feature_key", name="uq_saas_trial_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    usage_date: Mapped[str] = mapped_column(String(10), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SaasTrialClaim(Base):
    """One email / device / IP may only activate SaaS trial once."""

    __tablename__ = "saas_trial_claims"
    __table_args__ = (
        UniqueConstraint("claim_kind", "claim_value", name="uq_saas_trial_claim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    claim_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_value: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
