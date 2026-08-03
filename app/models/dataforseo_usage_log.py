"""Log từng lần gọi DataForSEO — task, credit, cache vs API."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DataforseoUsageLog(Base):
    __tablename__ = "dataforseo_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    api_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="cache")
    tasks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_charged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_called: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    keyword_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_slug: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
