"""Create chatbot_workflow_credit_logs table."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_chatbot_workflow_credit_logs_table() -> bool:
    from app.models.chatbot_workflow_credit_log import ChatbotWorkflowCreditLog  # noqa: F401

    _ = ChatbotWorkflowCreditLog
    Base.metadata.create_all(bind=engine, tables=[ChatbotWorkflowCreditLog.__table__])
    insp = inspect(engine)
    return "chatbot_workflow_credit_logs" in insp.get_table_names()


def ensure_chatbot_workflow_credit_logs() -> dict[str, object]:
    created = ensure_chatbot_workflow_credit_logs_table()
    return {"chatbot_workflow_credit_logs_table": created}
