"""Additive columns for Chatbot CSKH website widget."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_chatbot_cskh_widget_columns() -> dict[str, object]:
    insp = inspect(engine)
    if "chatbot_bots" not in insp.get_table_names():
        return {"chatbot_bots": False, "added": []}
    cols = {c["name"] for c in insp.get_columns("chatbot_bots")}
    added: list[str] = []
    dialect = engine.dialect.name
    additions = (
        ("main_services", "TEXT"),
        ("consultation_tone", "VARCHAR(64)"),
        ("greeting", "VARCHAR(500)"),
    )
    with engine.begin() as conn:
        for name, col_type in additions:
            if name in cols:
                continue
            if dialect == "sqlite":
                conn.execute(text(f"ALTER TABLE chatbot_bots ADD COLUMN {name} {col_type}"))
            else:
                conn.execute(text(f"ALTER TABLE chatbot_bots ADD COLUMN {name} {col_type}"))
            added.append(name)
    return {"chatbot_bots": True, "added": added}
