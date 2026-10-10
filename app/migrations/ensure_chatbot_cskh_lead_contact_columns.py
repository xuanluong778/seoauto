"""Additive email columns for Chatbot CSKH lead/contact capture."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_chatbot_cskh_lead_contact_columns() -> dict[str, object]:
    insp = inspect(engine)
    added: list[str] = []
    dialect = engine.dialect.name
    targets = (
        ("chatbot_conversations", "visitor_email", "VARCHAR(255)"),
        ("chatbot_leads", "email", "VARCHAR(255)"),
    )
    with engine.begin() as conn:
        for table, column, col_type in targets:
            if table not in insp.get_table_names():
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            added.append(f"{table}.{column}")
    return {"added": added}
