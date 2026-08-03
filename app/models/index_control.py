"""Index Control — lịch sử kiểm tra index theo user."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class IndexControlCheck(Base):
    __tablename__ = "index_control_checks"
    __table_args__ = (
        Index("ix_ic_checks_user_created", "user_id", "created_at"),
        Index("ix_ic_checks_user_domain", "user_id", "domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    url_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'website'"))
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    project_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list["IndexControlCheckItem"]] = relationship(
        "IndexControlCheckItem",
        back_populates="check",
        cascade="all, delete-orphan",
    )


class IndexControlCheckItem(Base):
    __tablename__ = "index_control_check_items"
    __table_args__ = (
        Index("ix_ic_items_user_created", "user_id", "created_at"),
        Index("ix_ic_items_user_domain", "user_id", "domain"),
        Index("ix_ic_items_user_indexability", "user_id", "indexability"),
        Index("ix_ic_items_check_id", "check_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("index_control_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    url_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'website'"))
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexability: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'error'"))
    main_issue: Mapped[str] = mapped_column(String(128), nullable=False, server_default=text("'HTTP error'"))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'low'"))
    checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    check: Mapped[IndexControlCheck] = relationship("IndexControlCheck", back_populates="items")


class IndexNowSubmit(Base):
    __tablename__ = "indexnow_submits"
    __table_args__ = (Index("ix_in_submit_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    url_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    api_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submit_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'unknown'"))
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    logs: Mapped[list["IndexNowSubmitLog"]] = relationship(
        "IndexNowSubmitLog",
        back_populates="submit",
        cascade="all, delete-orphan",
    )


class IndexNowSubmitLog(Base):
    __tablename__ = "indexnow_submit_logs"
    __table_args__ = (
        Index("ix_in_log_user_created", "user_id", "created_at"),
        Index("ix_in_log_submit_id", "submit_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submit_id: Mapped[int] = mapped_column(
        ForeignKey("indexnow_submits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    send_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'unknown'"))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    submit: Mapped[IndexNowSubmit] = relationship("IndexNowSubmit", back_populates="logs")
