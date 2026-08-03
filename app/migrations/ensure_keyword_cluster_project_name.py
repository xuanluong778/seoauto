"""Additive migration: project_name for keyword cluster projects."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_keyword_cluster_project_name() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "keyword_cluster_projects" not in tables:
        return
    cols = {c["name"] for c in insp.get_columns("keyword_cluster_projects")}
    if "project_name" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE keyword_cluster_projects ADD COLUMN project_name VARCHAR(255)"
                )
            )
