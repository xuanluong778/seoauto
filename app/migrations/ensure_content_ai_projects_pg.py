"""Deploy-time: content_ai_projects table (org-scoped)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def _has_table(name: str) -> bool:
    return name in inspect(engine).get_table_names()


def schema_status() -> dict[str, Any]:
    missing: list[str] = []
    if not _has_table("content_ai_projects"):
        missing.append("table:content_ai_projects")
    return {"ok": not missing, "missing": missing}


def apply_content_ai_projects_migration() -> dict[str, Any]:
    import app.models.content_ai_project  # noqa: F401
    import app.models.user  # noqa: F401

    from app.models.content_ai_project import ContentAiProject

    Base.metadata.create_all(bind=engine, tables=[ContentAiProject.__table__])

    applied: list[str] = []
    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE INDEX IF NOT EXISTS ix_content_ai_projects_org_active "
            "ON content_ai_projects (organization_id) WHERE deleted_at IS NULL",
            "CREATE INDEX IF NOT EXISTS ix_content_ai_projects_org_user_active "
            "ON content_ai_projects (organization_id, user_id) WHERE deleted_at IS NULL",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(ddl.split()[5] if "INDEX" in ddl else "index")
            except Exception as exc:
                _LOG.warning("index: %s", exc)

    st = schema_status()
    _LOG.info("content_ai_projects migration applied=%s status=%s", applied, st)
    return {"applied": applied, "status": st}


def ensure_content_ai_projects_schema() -> None:
    apply_content_ai_projects_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_content_ai_projects_migration())
