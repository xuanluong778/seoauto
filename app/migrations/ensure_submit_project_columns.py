"""Additive migration: project_name + payload_json for submit projects."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_submit_project_columns() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "indexnow_submits" in tables:
        cols = {c["name"] for c in insp.get_columns("indexnow_submits")}
        if "project_name" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE indexnow_submits ADD COLUMN project_name VARCHAR(255)"
                    )
                )
    if "indexnow_submit_logs" in tables:
        cols = {c["name"] for c in insp.get_columns("indexnow_submit_logs")}
        if "payload_json" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE indexnow_submit_logs ADD COLUMN payload_json TEXT")
                )
