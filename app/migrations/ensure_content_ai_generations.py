"""Deploy-time: content_ai_generations table (async LLM WAVE 2)."""

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
    if not _has_table("content_ai_generations"):
        missing.append("table:content_ai_generations")
    return {"ok": not missing, "missing": missing}


def apply_content_ai_generations_migration() -> dict[str, Any]:
    import app.models.content_ai_generation  # noqa: F401
    import app.models.user  # noqa: F401

    from app.models.content_ai_generation import ContentAiGeneration

    Base.metadata.create_all(bind=engine, tables=[ContentAiGeneration.__table__])

    applied: list[str] = []
    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_content_ai_generations_user_idempotency "
            "ON content_ai_generations (user_id, idempotency_key)",
            "CREATE INDEX IF NOT EXISTS ix_content_ai_generations_org_state "
            "ON content_ai_generations (organization_id, state)",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(ddl.split()[5] if "INDEX" in ddl else "index")
            except Exception as exc:
                _LOG.warning("content_ai_generations index: %s", exc)

    st = schema_status()
    _LOG.info("content_ai_generations migration applied=%s status=%s", applied, st)
    return {"applied": applied, "status": st}


def ensure_content_ai_generations_schema() -> None:
    apply_content_ai_generations_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_content_ai_generations_migration())
