"""Cached search volume/CPC rows (DB fallback when Redis is unavailable)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KeywordVolumeCache(Base):
    __tablename__ = "keyword_volume_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    keyword: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(16), nullable=False, default="vn")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="vi")

    search_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cpc_avg: Mapped[str] = mapped_column(String(32), nullable=False, default="0")  # store as string for SQLite safety
    cpc_min: Mapped[str] = mapped_column(String(32), nullable=False, default="0")
    cpc_max: Mapped[str] = mapped_column(String(32), nullable=False, default="0")
    volume_source: Mapped[str] = mapped_column(String(32), nullable=False, default="api_cache")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="0.75")
    extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

