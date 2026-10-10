"""Email Automation + Email Marketing models.

These tables are additive (no changes to Content AI tables).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


AUTOMATION_EMAIL_TYPES = frozenset(
    {
        "welcome",
        "trial_ending",
        "exp_before_7",
        "exp_before_3",
        "exp_before_1",
        "exp_on",
        "exp_after_3",
        "expired",
        "low_credit",
        "payment_success",
        "payment_fail",
        "inactive_user",
    }
)

CAMPAIGN_STATUS_DRAFT = "draft"
CAMPAIGN_STATUS_SCHEDULED = "scheduled"
CAMPAIGN_STATUS_SENDING = "sending"
CAMPAIGN_STATUS_SENT = "sent"
CAMPAIGN_STATUS_FAILED = "failed"
CAMPAIGN_STATUS_CANCELLED = "cancelled"
CAMPAIGN_STATUSES = frozenset(
    {
        CAMPAIGN_STATUS_DRAFT,
        CAMPAIGN_STATUS_SCHEDULED,
        CAMPAIGN_STATUS_SENDING,
        CAMPAIGN_STATUS_SENT,
        CAMPAIGN_STATUS_FAILED,
        CAMPAIGN_STATUS_CANCELLED,
    }
)
SEGMENT_KINDS = frozenset({"all", "trial", "active", "expired", "low_credit", "by_plan"})


class EmailAutomationTemplate(Base):
    __tablename__ = "email_automation_templates"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "email_type", name="uq_email_auto_tpl_owner_type"),
        Index("ix_email_auto_tpl_owner", "owner_user_id"),
        Index("ix_email_auto_tpl_type", "email_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    email_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False, server_default=text("'Automation Template'"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    subject_template: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''"))
    html_body_template: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    text_body_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailMarketingCampaign(Base):
    __tablename__ = "email_marketing_campaigns"
    __table_args__ = (
        Index("ix_email_mkt_campaign_owner", "owner_user_id"),
        Index("ix_email_mkt_campaign_status_sched", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    text_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    cta_label: Mapped[str] = mapped_column(String(120), nullable=False, server_default=text("'CTA'"))
    cta_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    discount_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    segment_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'all'"),
    )  # all / trial / active / expired / by_plan
    segment_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    send_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'now'"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text(f"'{CAMPAIGN_STATUS_DRAFT}'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailMarketingUnsubscribe(Base):
    __tablename__ = "email_marketing_unsubscribes"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "recipient_email", name="uq_email_mkt_unsub_owner_email"),
        UniqueConstraint("owner_user_id", "unsub_token", name="uq_email_mkt_unsub_owner_token"),
        Index("ix_email_mkt_unsub_token", "unsub_token"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    unsub_token: Mapped[str] = mapped_column(String(64), nullable=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmailSend(Base):
    __tablename__ = "email_sends"
    __table_args__ = (
        # Automation idempotency: userId + emailType + expiryDate
        UniqueConstraint(
            "owner_user_id",
            "recipient_user_id",
            "automation_email_type",
            "expiry_date",
            name="uq_email_send_automation_dedupe",
        ),
        # Marketing idempotency: campaignId + recipient email
        UniqueConstraint(
            "owner_user_id",
            "campaign_id",
            "recipient_email",
            name="uq_email_send_marketing_dedupe",
        ),
        Index("ix_email_send_owner_status", "owner_user_id", "status"),
        Index("ix_email_send_campaign", "campaign_id"),
        Index("ix_email_send_event_token", "event_token"),
        Index("ix_email_send_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    campaign_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    recipient_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Automation columns
    automation_email_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    plan_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expiry_date: Mapped[Date | None] = mapped_column(Date, nullable=True, index=True)

    discount_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Required log statuses: QUEUED / SENT / DELIVERED / FAILED / OPENED / CLICKED
    # We store them into one column and transition as events happen.
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=text("'queued'"),
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))

    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Tracking
    event_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    unsub_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    click_target_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmailSendLog(Base):
    __tablename__ = "email_send_logs"
    __table_args__ = (
        Index("ix_email_send_logs_owner_created", "owner_user_id", "created_at"),
        Index("ix_email_send_logs_send_id", "email_send_id"),
        Index("ix_email_send_logs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    email_send_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # queued/sent/delivered/failed/opened/clicked
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)



