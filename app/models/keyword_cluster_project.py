"""Persisted keyword clustering runs (projects/history)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KeywordClusterProject(Base):
    __tablename__ = "keyword_cluster_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords_label: Mapped[str] = mapped_column(String(2000), nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False)

    language: Mapped[str] = mapped_column(String(16), nullable=False, default="vi")
    country: Mapped[str] = mapped_column(String(16), nullable=False, default="vn")
    device: Mapped[str] = mapped_column(String(16), nullable=False, default="desktop")
    cluster_strictness: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    fetch_serp: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1/0
    brand_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")

    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

