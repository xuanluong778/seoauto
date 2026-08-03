"""Create dataforseo_usage_logs table."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_dataforseo_usage_logs_table() -> bool:
    from app.models.dataforseo_usage_log import DataforseoUsageLog  # noqa: F401

    _ = DataforseoUsageLog
    Base.metadata.create_all(bind=engine, tables=[DataforseoUsageLog.__table__])
    insp = inspect(engine)
    return "dataforseo_usage_logs" in insp.get_table_names()


def ensure_dataforseo_usage_logs() -> dict[str, object]:
    return {"dataforseo_usage_logs_table": ensure_dataforseo_usage_logs_table()}
