"""Backup run records for admin monitoring."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

BACKUP_STATUSES = frozenset({"pending", "running", "success", "failed", "verified", "verify_failed"})
BACKUP_TYPES = frozenset({"db", "media", "source", "infra", "full", "data"})
BACKUP_TRIGGERS = frozenset({"scheduled", "manual", "scheduled_dr"})


class BackupRun(Base):
    __tablename__ = "backup_runs"
    __table_args__ = (
        Index("ix_backup_runs_run_id", "run_id", unique=True),
        Index("ix_backup_runs_status", "status"),
        Index("ix_backup_runs_backup_type", "backup_type"),
        Index("ix_backup_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    backup_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"))
    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'scheduled'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    remote_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verify_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
