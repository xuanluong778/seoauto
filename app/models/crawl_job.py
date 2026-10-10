"""Distributed crawl jobs and per-URL results (Celery + Postgres/SQLite)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class DistributedCrawlJob(Base):
    """Parent job: single-URL task or site crawl metadata."""

    __tablename__ = "distributed_crawl_jobs"
    __table_args__ = (
        Index("ix_dc_jobs_project_status", "project_id", "status"),
        Index("ix_dc_jobs_created", "created_at"),
        Index("ix_dc_jobs_user_id", "user_id"),
        Index("ix_dc_jobs_organization_id", "organization_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="single_url")
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    results: Mapped[list["DistributedCrawlResult"]] = relationship(
        "DistributedCrawlResult", back_populates="job", cascade="all, delete-orphan"
    )


class DistributedCrawlResult(Base):
    """One row per crawled URL (idempotent with unique job + url_hash)."""

    __tablename__ = "distributed_crawl_results"
    __table_args__ = (
        UniqueConstraint("job_id", "url_hash", name="uq_dc_job_urlhash"),
        Index("ix_dc_results_status", "crawl_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("distributed_crawl_jobs.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    crawl_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    block_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proxy_used: Mapped[str | None] = mapped_column(String(512), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawl_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped["DistributedCrawlJob"] = relationship("DistributedCrawlJob", back_populates="results")
