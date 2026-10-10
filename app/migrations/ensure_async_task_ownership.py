"""Additive migration: async task owners + crawl job tenant columns."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    insp = inspect(engine)
    if table not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def ensure_async_task_ownership() -> None:
    """Create async_task_owners; add user_id/organization_id on distributed_crawl_jobs."""
    from app.models.async_task_owner import AsyncTaskOwner  # noqa: F401
    from app.models.crawl_job import DistributedCrawlJob, DistributedCrawlResult  # noqa: F401
    from app.db import Base

    Base.metadata.create_all(
        bind=engine,
        tables=[
            AsyncTaskOwner.__table__,
            DistributedCrawlJob.__table__,
            DistributedCrawlResult.__table__,
        ],
    )

    _add_column_if_missing(
        "distributed_crawl_jobs",
        "user_id",
        "ALTER TABLE distributed_crawl_jobs ADD COLUMN user_id INTEGER",
    )
    _add_column_if_missing(
        "distributed_crawl_jobs",
        "organization_id",
        "ALTER TABLE distributed_crawl_jobs ADD COLUMN organization_id INTEGER",
    )

    insp = inspect(engine)
    if "distributed_crawl_jobs" in set(insp.get_table_names()):
        # Best-effort indexes (ignore if dialect/exists issues)
        with engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dc_jobs_user_id "
                        "ON distributed_crawl_jobs (user_id)"
                    )
                )
            except Exception:
                pass
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dc_jobs_organization_id "
                        "ON distributed_crawl_jobs (organization_id)"
                    )
                )
            except Exception:
                pass
