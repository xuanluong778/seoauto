"""WordPress SEO Helper plugin — connection, pairing, entitlement cache, command & idempotency logs.

Tenant isolation: every row carries user_id + organization_id.
Until a real organizations table exists, personal workspaces use organization_id = user_id.
Cross-organization read/control is forbidden at the query layer (always filter both keys).
"""

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


class WordpressConnection(Base):
    """Paired WordPress site owned by one user within one organization tenant."""

    __tablename__ = "wordpress_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "domain_normalized",
            name="uq_wordpress_connections_org_domain",
        ),
        Index("ix_wordpress_connections_user_org", "user_id", "organization_id"),
        Index("ix_wordpress_connections_org_status", "organization_id", "status"),
        Index("ix_wordpress_connections_publishing_site", "publishing_site_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # No FK yet — organizations table does not exist; app sets personal org = user_id.
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Optional link to existing publishing_sites.json entry id (reuse, not duplicated creds required).
    publishing_site_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    site_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    domain_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    site_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plugin_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WordpressPairingCode(Base):
    """One-time pairing codes. Only code_hash is stored (never plaintext)."""

    __tablename__ = "wordpress_pairing_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_wordpress_pairing_codes_hash"),
        Index("ix_wordpress_pairing_codes_org_status", "organization_id", "status"),
        Index("ix_wordpress_pairing_codes_user_org", "user_id", "organization_id"),
        Index("ix_wordpress_pairing_codes_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    domain_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WordpressEntitlement(Base):
    """Cached plugin entitlement snapshot (from PluginEntitlementService — no credit burn)."""

    __tablename__ = "wordpress_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "connection_id",
            name="uq_wordpress_entitlements_org_connection",
        ),
        Index("ix_wordpress_entitlements_user_org", "user_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_sites: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    enabled_features_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WordpressCommandLog(Base):
    """Audit trail for SaaS ↔ plugin commands (scoped per organization)."""

    __tablename__ = "wordpress_command_logs"
    __table_args__ = (
        Index(
            "ix_wordpress_command_logs_org_connection_created",
            "organization_id",
            "connection_id",
            "created_at",
        ),
        Index("ix_wordpress_command_logs_user_org", "user_id", "organization_id"),
        Index("ix_wordpress_command_logs_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'saas_to_wp'")
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WordpressPublishJob(Base):
    """Async publish command executed by Celery → SEO Helper plugin (HMAC)."""

    __tablename__ = "wordpress_publish_jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "request_id",
            name="uq_wordpress_publish_jobs_org_request",
        ),
        Index("ix_wordpress_publish_jobs_user_org", "user_id", "organization_id"),
        Index("ix_wordpress_publish_jobs_status_retry", "status", "next_retry_at"),
        Index("ix_wordpress_publish_jobs_schedule", "schedule_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False, default="post_create")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_post_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WordpressRequestIdempotency(Base):
    """Deduplicate plugin/API requests within an organization tenant."""

    __tablename__ = "wordpress_request_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_wordpress_request_idempotency_org_key",
        ),
        Index("ix_wordpress_request_idempotency_user_org", "user_id", "organization_id"),
        Index("ix_wordpress_request_idempotency_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WordpressPluginRelease(Base):
    """Private plugin release registry (stable/beta) — ZIP lives in object storage only."""

    __tablename__ = "wordpress_plugin_releases"
    __table_args__ = (
        UniqueConstraint("slug", "version", "channel", name="uq_wordpress_plugin_releases_slug_ver_ch"),
        Index("ix_wordpress_plugin_releases_status_channel", "status", "channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, default="seoauto-seo-helper")
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'stable'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    # Object storage key (R2/S3). Legacy local absolute path may still appear in package_storage_path.
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    package_storage_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # HMAC(release_signing_key, version|sha256|channel) — not site_secret.
    package_signature: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    requires_wp: Mapped[str] = mapped_column(String(16), nullable=False, default="6.0")
    requires_php: Mapped[str] = mapped_column(String(16), nullable=False, default="8.1")
    tested: Mapped[str] = mapped_column(String(16), nullable=False, default="6.7")  # tested_wp
    changelog_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    changelog_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    autoupdate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    security_patch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    min_from_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rollout_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    allowed_site_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_site_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WordpressPluginDownloadToken(Base):
    """Short-lived signed download tokens (anti-replay)."""

    __tablename__ = "wordpress_plugin_download_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_wordpress_plugin_download_tokens_hash"),
        Index("ix_wordpress_plugin_download_tokens_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("wordpress_plugin_releases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WordpressPluginUpdateEvent(Base):
    """Telemetry: check / download / update_error counts."""

    __tablename__ = "wordpress_plugin_update_events"
    __table_args__ = (
        Index("ix_wordpress_plugin_update_events_type_created", "event_type", "created_at"),
        Index("ix_wordpress_plugin_update_events_connection", "connection_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_connections.id", ondelete="SET NULL"), nullable=True
    )
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("wordpress_plugin_releases.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
