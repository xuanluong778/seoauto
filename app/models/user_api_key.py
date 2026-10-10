from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    organization_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai")
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'healthy'"))
    used_today: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    errors_today: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_used_at: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
