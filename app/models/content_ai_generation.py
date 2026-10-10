"""Persisted Content AI async generation jobs (WAVE 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContentAiGeneration(Base):
    __tablename__ = "content_ai_generations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="Queued")

    request_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    credit_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credits_charged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_stream_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
