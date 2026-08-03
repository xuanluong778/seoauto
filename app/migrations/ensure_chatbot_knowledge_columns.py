"""Additive columns for Chatbot CSKH knowledge sources."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def _timestamp_sql_type() -> str:
    if engine.dialect.name == "sqlite":
        return "DATETIME"
    return "TIMESTAMP WITH TIME ZONE"


def _varchar_sql_type(length: int) -> str:
    if engine.dialect.name == "sqlite":
        return "TEXT"
    return f"VARCHAR({length})"


def ensure_chatbot_knowledge_columns() -> dict[str, object]:
    insp = inspect(engine)
    if "chatbot_knowledge_sources" not in insp.get_table_names():
        return {"chatbot_knowledge_sources": False, "added": [], "migrated_status": 0}

    cols = {c["name"] for c in insp.get_columns("chatbot_knowledge_sources")}
    added: list[str] = []
    dialect = engine.dialect.name

    additions = (
        ("updated_at", _timestamp_sql_type()),
        ("crawl_error", _varchar_sql_type(500)),
    )
    with engine.begin() as conn:
        for name, col_type in additions:
            if name in cols:
                continue
            if dialect == "sqlite" and name == "updated_at":
                conn.execute(
                    text(f"ALTER TABLE chatbot_knowledge_sources ADD COLUMN {name} {col_type} DEFAULT (CURRENT_TIMESTAMP)")
                )
            else:
                conn.execute(text(f"ALTER TABLE chatbot_knowledge_sources ADD COLUMN {name} {col_type}"))
            added.append(name)

        migrated = conn.execute(
            text(
                """
                UPDATE chatbot_knowledge_sources
                SET status = CASE
                    WHEN status IN ('active', 'ready') THEN 'ready'
                    WHEN status IN ('processing', 'pending') THEN 'pending'
                    WHEN status IN ('inactive', 'failed') THEN 'failed'
                    ELSE status
                END
                WHERE status IN ('active', 'inactive', 'processing', 'ready', 'failed', 'pending')
                """
            )
        ).rowcount

        if "updated_at" in (cols | set(added)):
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "UPDATE chatbot_knowledge_sources SET updated_at = created_at "
                        "WHERE updated_at IS NULL"
                    )
                )
            else:
                conn.execute(
                    text(
                        "UPDATE chatbot_knowledge_sources SET updated_at = created_at "
                        "WHERE updated_at IS NULL"
                    )
                )

    return {
        "chatbot_knowledge_sources": True,
        "added": added,
        "migrated_status": int(migrated or 0),
    }
