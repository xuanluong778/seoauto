"""Chatbot CSKH Facebook Fanpage tables + conversation channel columns."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine


def ensure_chatbot_cskh_facebook() -> dict[str, object]:
    from app.models.chatbot_cskh import ChatbotFacebookPage  # noqa: F401
    from app.models.user import User  # noqa: F401

    created_fb = False
    insp = inspect(engine)
    if "chatbot_facebook_pages" not in insp.get_table_names():
        Base.metadata.create_all(bind=engine, tables=[ChatbotFacebookPage.__table__])
        created_fb = True

    added_conv: list[str] = []
    if "chatbot_conversations" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chatbot_conversations")}
        additions = (
            ("channel", "VARCHAR(32) NOT NULL DEFAULT 'website'"),
            ("external_user_id", "VARCHAR(64)"),
            ("channel_ref", "VARCHAR(64)"),
            ("last_user_message_at", "TIMESTAMP WITH TIME ZONE"),
        )
        dialect = engine.dialect.name
        with engine.begin() as conn:
            for name, col_type in additions:
                if name in cols:
                    continue
                if dialect == "sqlite":
                    if "NOT NULL" in col_type and "DEFAULT" in col_type:
                        conn.execute(text(f"ALTER TABLE chatbot_conversations ADD COLUMN {name} {col_type}"))
                    else:
                        conn.execute(text(f"ALTER TABLE chatbot_conversations ADD COLUMN {name} {col_type}"))
                else:
                    conn.execute(text(f"ALTER TABLE chatbot_conversations ADD COLUMN {name} {col_type}"))
                added_conv.append(name)

    return {
        "facebook_pages_table_created": created_fb,
        "conversation_columns_added": added_conv,
    }
