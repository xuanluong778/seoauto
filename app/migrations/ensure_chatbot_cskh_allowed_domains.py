"""Additive allowed_domains column for Chatbot CSKH origin validation."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import engine


def ensure_chatbot_cskh_allowed_domains() -> dict[str, object]:
    insp = inspect(engine)
    if "chatbot_bots" not in insp.get_table_names():
        return {"chatbot_bots": False, "added": []}
    cols = {c["name"] for c in insp.get_columns("chatbot_bots")}
    if "allowed_domains" in cols:
        return {"chatbot_bots": True, "added": []}
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE chatbot_bots ADD COLUMN allowed_domains VARCHAR(2000)"))
    return {"chatbot_bots": True, "added": ["allowed_domains"]}
