"""Persisted keyword research sessions (history / projects)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KeywordResearchProject(Base):
    __tablename__ = "keyword_research_projects"
    __table_args__ = (Index("ix_kw_research_org", "organization_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    keywords_label: Mapped[str] = mapped_column(String(2000), nullable=False)
    seeds_json: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="vi")
    country: Mapped[str] = mapped_column(String(16), nullable=False, default="vn")
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="google")
    location_label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
