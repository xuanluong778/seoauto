"""SaaS economics — cấu hình ngưỡng & trạng thái chặn API đắt."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SaasEconomicsConfig(Base):
    __tablename__ = "saas_economics_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SaasEconomicsState(Base):
    """Singleton row id=1 — trạng thái chặn API đắt toàn hệ thống."""

    __tablename__ = "saas_economics_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=text("1"))
    expensive_api_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    block_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_alert_daily_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_alert_monthly_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
