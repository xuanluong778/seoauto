"""Additive columns + jobs table for Chatbot CSKH unread email notifications."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def _try_sql(sql: str) -> bool:
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        return True
    except Exception:
        _LOG.warning("cskh email notify migration skipped: %s", sql.split("\n", 1)[0][:120])
        return False


def ensure_chatbot_cskh_email_notify() -> dict[str, object]:
    from app.models.chatbot_cskh import (
        ChatbotEmailNotifyJob,
        ChatbotEmailNotifyLog,
        ChatbotEmailNotifySetting,
    )
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    dialect = engine.dialect.name
    ts = "DATETIME" if dialect == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    added_msg: list[str] = []
    added_conv: list[str] = []

    if "chatbot_messages" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chatbot_messages")}
        if "read_at" not in cols and _try_sql(f"ALTER TABLE chatbot_messages ADD COLUMN read_at {ts}"):
            added_msg.append("read_at")

    insp = inspect(engine)
    if "chatbot_conversations" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chatbot_conversations")}
        if "last_email_notified_at" not in cols and _try_sql(
            f"ALTER TABLE chatbot_conversations ADD COLUMN last_email_notified_at {ts}"
        ):
            added_conv.append("last_email_notified_at")
        if "organization_id" not in cols and _try_sql(
            "ALTER TABLE chatbot_conversations ADD COLUMN organization_id INTEGER"
        ):
            added_conv.append("organization_id")
        _try_sql(
            "UPDATE chatbot_conversations SET organization_id = user_id "
            "WHERE organization_id IS NULL AND user_id IS NOT NULL"
        )
        _try_sql(
            "CREATE INDEX IF NOT EXISTS ix_chatbot_conversations_organization_id "
            "ON chatbot_conversations (organization_id)"
        )

    created_jobs = False
    created_settings = False
    created_logs = False

    insp = inspect(engine)
    if "chatbot_email_notify_jobs" not in insp.get_table_names():
        Base.metadata.create_all(bind=engine, tables=[ChatbotEmailNotifyJob.__table__])
        created_jobs = True

    insp = inspect(engine)
    if "chatbot_email_notify_settings" not in insp.get_table_names():
        Base.metadata.create_all(bind=engine, tables=[ChatbotEmailNotifySetting.__table__])
        created_settings = True

    insp = inspect(engine)
    if "chatbot_email_notify_logs" not in insp.get_table_names():
        Base.metadata.create_all(bind=engine, tables=[ChatbotEmailNotifyLog.__table__])
        created_logs = True

    _try_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cskh_notify_pending_org_conv "
        "ON chatbot_email_notify_jobs (organization_id, conversation_id) "
        "WHERE status = 'pending'"
    )

    return {
        "jobs_table_created": created_jobs,
        "settings_table_created": created_settings,
        "logs_table_created": created_logs,
        "message_columns_added": added_msg,
        "conversation_columns_added": added_conv,
        "dialect": dialect,
    }
