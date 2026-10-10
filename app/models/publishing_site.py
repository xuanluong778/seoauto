"""CMS publishing sites (WordPress/Shopify/etc.) — credentials encrypted at rest."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PublishingSite(Base):
    __tablename__ = "publishing_sites"
    __table_args__ = (
        Index("ix_publishing_sites_org", "organization_id"),
        Index("ix_publishing_sites_user", "user_id"),
        Index("ix_publishing_sites_org_platform", "organization_id", "platform"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'wordpress'"))
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    site_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    site_url_normalized: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    plugin_installed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    favicon_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    last_checked_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_json_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WordpressSiteLink(Base):
    """Content Auto Update WordPress connector link — no credential copy; use publishing_sites."""

    __tablename__ = "wordpress_site_links"
    __table_args__ = (
        Index("ix_wordpress_site_links_org", "organization_id"),
        Index("ix_wordpress_site_links_user", "user_id"),
        Index("ix_wordpress_site_links_pub", "publishing_site_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    publishing_site_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("publishing_sites.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    site_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional encrypted copy only if publishing_site_id unresolved; prefer empty
    credential_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'connected'"))
    last_test_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    connected_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_json_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegacyDataQuarantine(Base):
    """JSON records that cannot be safely tenant-assigned."""

    __tablename__ = "legacy_data_quarantine"
    __table_args__ = (
        Index("ix_legacy_quarantine_store", "source_store"),
        Index("ix_legacy_quarantine_reason", "reason"),
        Index(
            "uq_legacy_quarantine_store_record",
            "source_store",
            "source_record_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_store: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
