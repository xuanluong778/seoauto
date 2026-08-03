"""Ensure backup_runs table exists."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine
from app.models.backup_run import BackupRun


def ensure_backup_runs_table() -> bool:
    insp = inspect(engine)
    if "backup_runs" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("backup_runs")}
        if "admin_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE backup_runs ADD COLUMN admin_id INTEGER NULL"))
        return True
    Base.metadata.create_all(bind=engine, tables=[BackupRun.__table__])
    insp = inspect(engine)
    return "backup_runs" in insp.get_table_names()
