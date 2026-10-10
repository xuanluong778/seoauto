"""WAVE 3 — supplemental indexes for hot query paths."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import engine

_LOG = logging.getLogger(__name__)

INDEX_DDLS = [
    (
        "ix_content_ai_generations_user_state_updated",
        "CREATE INDEX IF NOT EXISTS ix_content_ai_generations_user_state_updated "
        "ON content_ai_generations (user_id, state, updated_at DESC)",
    ),
    (
        "ix_content_ai_projects_list_cover",
        "CREATE INDEX IF NOT EXISTS ix_content_ai_projects_list_cover "
        "ON content_ai_projects (organization_id, user_id, created_at DESC) "
        "WHERE deleted_at IS NULL AND legacy_orphan IS FALSE",
    ),
    (
        "ix_credit_reservations_user_status",
        "CREATE INDEX IF NOT EXISTS ix_credit_reservations_user_status "
        "ON credit_reservations (user_id, status, created_at DESC)",
    ),
    (
        "ix_wordpress_publish_jobs_status_created",
        "CREATE INDEX IF NOT EXISTS ix_wordpress_publish_jobs_status_created "
        "ON wordpress_publish_jobs (status, created_at DESC)",
    ),
]


def schema_status() -> dict[str, Any]:
    if engine.dialect.name != "postgresql":
        return {"ok": True, "skipped": "not_postgresql"}
    missing = []
    names = {idx["name"] for tbl in inspect(engine).get_table_names() for idx in inspect(engine).get_indexes(tbl)}
    for name, _ in INDEX_DDLS:
        if name not in names:
            missing.append(name)
    return {"ok": not missing, "missing": missing}


def apply_wave3_index_migration() -> dict[str, Any]:
    if engine.dialect.name != "postgresql":
        return {"applied": [], "status": {"ok": True, "skipped": "not_postgresql"}}
    applied = []
    for name, ddl in INDEX_DDLS:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            applied.append(name)
        except Exception as exc:
            _LOG.warning("wave3 index %s failed: %s", name, exc)
    st = schema_status()
    return {"applied": applied, "status": st}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_wave3_index_migration())
