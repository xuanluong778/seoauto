"""Chatbot CSKH bonus credits column + audit log table."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine


def ensure_chatbot_cskh_credit_columns() -> dict[str, object]:
    insp = inspect(engine)
    dialect = engine.dialect.name
    added_user_cols: list[str] = []

    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "chatbot_cskh_bonus_credits" not in cols:
            col_type = "INTEGER NOT NULL DEFAULT 0"
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN chatbot_cskh_bonus_credits {col_type}"))
            added_user_cols.append("chatbot_cskh_bonus_credits")

    from app.models.chatbot_cskh_credit_log import ChatbotCskhCreditLog  # noqa: F401
    from app.models.user import User  # noqa: F401 — register users table for FK

    created_log = False
    if "chatbot_cskh_credit_logs" not in insp.get_table_names():
        Base.metadata.create_all(bind=engine, tables=[ChatbotCskhCreditLog.__table__])
        created_log = True

    return {
        "dialect": dialect,
        "user_columns_added": added_user_cols,
        "credit_log_table_created": created_log,
    }
