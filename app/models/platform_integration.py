"""Platform-wide third-party integration credentials (encrypted at rest)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlatformIntegration(Base):
    __tablename__ = "platform_integrations"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
