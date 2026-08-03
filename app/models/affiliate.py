"""Affiliate program models — 30% commission, referral tracking."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AffiliateAccount(Base):
    __tablename__ = "affiliate_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_affiliate_accounts_user_id"),
        UniqueConstraint("referral_code", name="uq_affiliate_accounts_referral_code"),
        Index("ix_affiliate_accounts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    referral_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    commission_rate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    cookie_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    payout_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fraud_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fraud_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"
    __table_args__ = (
        Index("ix_affiliate_clicks_affiliate_id", "affiliate_id"),
        Index("ix_affiliate_clicks_referral_code", "referral_code"),
        Index("ix_affiliate_clicks_created_at", "created_at"),
        Index("ix_affiliate_clicks_ip_hash", "ip_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_accounts.id", ondelete="CASCADE"), nullable=False
    )
    referral_code: Mapped[str] = mapped_column(String(32), nullable=False)
    landing_page: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(128), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AffiliateReferral(Base):
    __tablename__ = "affiliate_referrals"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_affiliate_referrals_referred_user"),
        Index("ix_affiliate_referrals_affiliate_id", "affiliate_id"),
        Index("ix_affiliate_referrals_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_accounts.id", ondelete="CASCADE"), nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    first_click_id: Mapped[int | None] = mapped_column(
        ForeignKey("affiliate_clicks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'registered'"))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    first_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AffiliateCommission(Base):
    __tablename__ = "affiliate_commissions"
    __table_args__ = (
        Index("ix_affiliate_commissions_affiliate_id", "affiliate_id"),
        Index("ix_affiliate_commissions_status", "status"),
        Index("ix_affiliate_commissions_order_id", "order_id"),
        UniqueConstraint("idempotency_key", name="uq_affiliate_commissions_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_accounts.id", ondelete="CASCADE"), nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    order_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    commission_rate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    commission_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    paid_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AffiliatePayout(Base):
    __tablename__ = "affiliate_payouts"
    __table_args__ = (
        Index("ix_affiliate_payouts_affiliate_id", "affiliate_id"),
        Index("ix_affiliate_payouts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_accounts.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'requested'"))
    payout_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AffiliateSettings(Base):
    """Singleton-style global affiliate configuration (row id=1)."""

    __tablename__ = "affiliate_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    default_commission_rate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    cookie_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    min_payout_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("200000"))
    commission_hold_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("7"))
    auto_approve_commissions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AffiliateAdjustment(Base):
    """Negative balance adjustments (e.g. clawback after refund of a paid commission)."""

    __tablename__ = "affiliate_adjustments"
    __table_args__ = (
        Index("ix_affiliate_adjustments_affiliate_id", "affiliate_id"),
        Index("ix_affiliate_adjustments_status", "status"),
        UniqueConstraint("idempotency_key", name="uq_affiliate_adjustments_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    affiliate_id: Mapped[int] = mapped_column(
        ForeignKey("affiliate_accounts.id", ondelete="CASCADE"), nullable=False
    )
    commission_id: Mapped[int | None] = mapped_column(
        ForeignKey("affiliate_commissions.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # positive = debt to deduct
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
