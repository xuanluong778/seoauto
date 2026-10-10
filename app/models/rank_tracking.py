"""Rank Tracking — PostgreSQL projects, keywords, SERP results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RankTrackingProject(Base):
    __tablename__ = "rank_tracking_projects"
    __table_args__ = (
        Index("ix_rt_projects_user_org", "user_id", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    location_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Vietnam")
    language_name: Mapped[str] = mapped_column(String(120), nullable=False, default="Vietnamese")
    device: Mapped[str] = mapped_column(String(32), nullable=False, default="desktop")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RankTrackingKeyword(Base):
    __tablename__ = "rank_tracking_keywords"
    __table_args__ = (
        Index("ix_rt_keywords_project", "project_id"),
        Index("ix_rt_keywords_user_org", "user_id", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rank_tracking_projects.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checking_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RankTrackingResult(Base):
    __tablename__ = "rank_tracking_results"
    __table_args__ = (
        Index("ix_rt_results_keyword_checked", "keyword_id", "checked_at"),
        Index("ix_rt_results_user_org", "user_id", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    keyword_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    rank_absolute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rank_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    found: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    serp_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
