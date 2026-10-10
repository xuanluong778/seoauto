"""Compatibility ORM models expected by legacy user_data_pg bootstrap paths.

Content AI projects use app.models.content_ai_project.ContentAiProject as the
primary table. Document-style tables remain available for dual-write tooling
if enabled; organization_id is required when present.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContentAiProjectDocument(Base):
    """Legacy document blob shape — prefer content_ai_projects structured table."""

    __tablename__ = "content_ai_project_documents"

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    legacy_orphan: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    import_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserSystemSettingsDocument(Base):
    __tablename__ = "user_system_settings_documents"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    import_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
