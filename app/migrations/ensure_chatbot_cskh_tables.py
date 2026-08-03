"""Create Chatbot CSKH platform tables (idempotent)."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_chatbot_cskh_tables() -> dict[str, object]:
    from app.models.chatbot_cskh import (  # noqa: F401
        ChatbotBot,
        ChatbotConversation,
        ChatbotKnowledgeSource,
        ChatbotLead,
        ChatbotMessage,
        ChatbotUsage,
    )

    tables = [
        ChatbotBot.__table__,
        ChatbotKnowledgeSource.__table__,
        ChatbotConversation.__table__,
        ChatbotMessage.__table__,
        ChatbotLead.__table__,
        ChatbotUsage.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    insp = inspect(engine)
    names = set(insp.get_table_names())
    expected = {t.name for t in tables}
    return {"chatbot_cskh_tables": expected.issubset(names), "tables": sorted(expected & names)}
