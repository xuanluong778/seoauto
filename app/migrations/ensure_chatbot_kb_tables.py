"""Create Chatbot CSKH knowledge map tables (idempotent, additive)."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_chatbot_kb_tables() -> dict[str, object]:
    from app.models.user import User  # noqa: F401
    from app.models.chatbot_cskh import ChatbotBot  # noqa: F401
    from app.models.chatbot_cskh_kb import (  # noqa: F401
        ChatbotKbEdge,
        ChatbotKbMap,
        ChatbotKbNode,
    )

    tables = [
        ChatbotKbMap.__table__,
        ChatbotKbNode.__table__,
        ChatbotKbEdge.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    insp = inspect(engine)
    names = set(insp.get_table_names())
    expected = {t.name for t in tables}
    return {"chatbot_kb_tables": expected.issubset(names), "tables": sorted(expected & names)}
