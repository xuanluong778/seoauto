"""Content AI projects — org-scoped documents (content + payload metadata)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContentAiProject(Base):
    __tablename__ = "content_ai_projects"
    __table_args__ = (
        Index("ix_content_ai_projects_org", "organization_id"),
        Index("ix_content_ai_projects_user", "user_id"),
        Index("ix_content_ai_projects_org_created", "organization_id", "created_at"),
        Index(
            "ix_content_ai_projects_org_site_kw",
            "organization_id",
            "target_website_norm",
            "primary_keyword_norm",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    slug: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_website: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    target_website_norm: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    primary_keyword: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_keyword_norm: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    origin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    legacy_orphan: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_json_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
