"""Technical SEO audit runs — tenant-scoped PostgreSQL store (JSON dual-write during Wave 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TechnicalAudit(Base):
    __tablename__ = "technical_audits"
    __table_args__ = (
        Index("ix_technical_audits_user_at", "user_id", "created_at"),
        Index("ix_technical_audits_user_domain", "user_id", "domain"),
        Index("ix_technical_audits_org_at", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Integer (no FK) — supports legacy JSON rows whose user may be gone; tenant filter still enforced in queries.
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    domain: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    pages_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated_issues: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Partial unique index (user_id, idempotency_key) WHERE key present — see ensure_* migration.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
