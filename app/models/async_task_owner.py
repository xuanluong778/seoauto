"""Durable ownership for Celery/async task IDs (multi-worker safe)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AsyncTaskOwner(Base):
    __tablename__ = "async_task_owners"
    __table_args__ = (
        Index("ix_async_task_owners_user_org", "user_id", "organization_id"),
        Index("ix_async_task_owners_created", "created_at"),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
