"""Chatbot CSKH inbox notification list + mark-read (badge source of truth)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.chatbot_cskh import (
    ChatbotBot,
    ChatbotConversation,
    ChatbotEmailNotifyJob,
    ChatbotLead,
    ChatbotMessage,
)
from app.models.user import User
from app.services.chatbot_cskh_email_notify import mark_conversation_read
from app.services.chatbot_cskh_inbox_service import (
    count_unread_conversations,
    list_unread_notifications,
)


@pytest.fixture()
def db():
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            ChatbotBot.__table__,
            ChatbotConversation.__table__,
            ChatbotMessage.__table__,
            ChatbotLead.__table__,
            ChatbotEmailNotifyJob.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _user(db) -> User:
    u = User(email="owner-inbox@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    return u


def _bot(db, user: User) -> ChatbotBot:
    bot = ChatbotBot(user_id=user.id, bot_name="Bot inbox", status="active")
    db.add(bot)
    db.flush()
    return bot


def _conv(db, user: User, bot: ChatbotBot, *, name: str, session_id: str) -> ChatbotConversation:
    conv = ChatbotConversation(
        bot_id=bot.id,
        user_id=user.id,
        session_id=session_id,
        channel="website",
        visitor_name=name,
        status="open",
    )
    db.add(conv)
    db.flush()
    return conv


def _inbound(db, conv: ChatbotConversation, text: str) -> ChatbotMessage:
    msg = ChatbotMessage(
        conversation_id=conv.id,
        user_id=conv.user_id,
        role="user",
        message=text,
    )
    db.add(msg)
    db.flush()
    return msg


def test_unread_groups_by_conversation_and_keeps_latest_preview(db):
    owner = _user(db)
    bot = _bot(db, owner)
    c1 = _conv(db, owner, bot, name="An", session_id="s1")
    c2 = _conv(db, owner, bot, name="Bình", session_id="s2")
    _inbound(db, c1, "xin chào")
    _inbound(db, c1, "cần báo giá máy tính")
    _inbound(db, c2, "còn bảo hành không")
    db.commit()

    snap = list_unread_notifications(db, owner.id)
    assert snap["unread_count"] == 2
    assert count_unread_conversations(db, owner.id) == 2
    by_name = {it["visitor_name"]: it for it in snap["items"]}
    assert by_name["An"]["preview"] == "cần báo giá máy tính"
    assert by_name["Bình"]["preview"] == "còn bảo hành không"


def test_mark_read_drops_that_conversation_from_badge(db):
    owner = _user(db)
    bot = _bot(db, owner)
    c1 = _conv(db, owner, bot, name="An", session_id="s1")
    c2 = _conv(db, owner, bot, name="Bình", session_id="s2")
    _inbound(db, c1, "tin 1")
    _inbound(db, c2, "tin 2")
    db.commit()

    n = mark_conversation_read(db, owner.id, c1.id, commit=True)
    assert n == 1
    snap = list_unread_notifications(db, owner.id)
    assert snap["unread_count"] == 1
    assert [it["visitor_name"] for it in snap["items"]] == ["Bình"]


def test_assistant_messages_do_not_count_as_unread(db):
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot, name="An", session_id="s1")
    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=owner.id,
            role="assistant",
            message="Xin chào, mình hỗ trợ gì được ạ?",
        )
    )
    db.commit()
    snap = list_unread_notifications(db, owner.id)
    assert snap["unread_count"] == 0
    assert snap["items"] == []
