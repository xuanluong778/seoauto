"""Persisted clustering job progress/results (survives reload + worker queue)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KeywordClusterJob(Base):
    __tablename__ = "keyword_cluster_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # Allow multiple job kinds to share the same progress store.
    # Examples: "keyword_cluster", "wp_bulk_update"
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="generic", index=True)

    # Tenant ownership (never trust payload alone)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="Queued")

    # request payload (for worker execution)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

