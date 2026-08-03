"""Additive migration: project_name for check-free sessions."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_check_free_project_column() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "index_control_checks" not in tables:
        return
    cols = {c["name"] for c in insp.get_columns("index_control_checks")}
    if "project_name" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE index_control_checks ADD COLUMN project_name VARCHAR(255)"
                )
            )
