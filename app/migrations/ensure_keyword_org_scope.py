"""Additive migration: organization_id on keyword research/cluster project tables."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db import engine

_LOG = logging.getLogger(__name__)


def _add_org_column(table: str) -> None:
    insp = inspect(engine)
    if table not in set(insp.get_table_names()):
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if "organization_id" in cols:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN organization_id INTEGER"))
            conn.execute(
                text(
                    f"UPDATE {table} SET organization_id = user_id "
                    "WHERE organization_id IS NULL AND user_id IS NOT NULL"
                )
            )
    except Exception:
        _LOG.warning("skip organization_id on %s (no privilege or already exists)", table)
        return
    _LOG.info("added organization_id to %s", table)


def ensure_keyword_org_scope() -> None:
    _add_org_column("keyword_research_projects")
    _add_org_column("keyword_cluster_projects")
