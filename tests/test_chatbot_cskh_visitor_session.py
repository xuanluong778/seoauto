"""Chatbot CSKH anonymous visitor session persistence (24h TTL, bot isolation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.chatbot_cskh import ChatbotBot, ChatbotConversation, ChatbotLead, ChatbotMessage
from app.models.user import User
from app.services.chatbot_cskh_visitor_session import (
    VISITOR_SESSION_TTL_HOURS,
    find_visitor_conversation,
    get_or_create_visitor_conversation,
    is_conversation_expired,
    load_public_history,
    new_visitor_id,
    normalize_visitor_id,
    purge_visitor_conversation,
)
from app.services.chatbot_cskh_widget_service import process_public_message


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
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _owner(db) -> User:
    u = User(email="visitor@test.local", password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    return u


def _bot(db, user: User, name: str = "Site A") -> ChatbotBot:
    bot = ChatbotBot(user_id=user.id, bot_name=name, business_name=name, status="active")
    db.add(bot)
    db.flush()
    return bot


def test_normalize_visitor_id_accepts_uuid_hex():
    vid = new_visitor_id()
    assert normalize_visitor_id(vid) == vid
    assert normalize_visitor_id("  " + vid + "  ") == vid
    assert normalize_visitor_id("bad!") == ""


def test_same_visitor_same_bot_reuses_conversation(db):
    user = _owner(db)
    bot = _bot(db, user)
    vid = new_visitor_id()
    c1, out1, _ = get_or_create_visitor_conversation(db, bot, vid)
    c2, out2, _ = get_or_create_visitor_conversation(db, bot, vid)
    assert out1 == out2 == vid
    assert c1.id == c2.id


def test_different_bots_do_not_share_conversation(db):
    user = _owner(db)
    bot_a = _bot(db, user, "A")
    bot_b = _bot(db, user, "B")
    vid = new_visitor_id()
    ca, _, _ = get_or_create_visitor_conversation(db, bot_a, vid)
    cb, _, _ = get_or_create_visitor_conversation(db, bot_b, vid)
    assert ca.id != cb.id
    assert find_visitor_conversation(db, bot_id=bot_a.id, visitor_id=vid).id == ca.id
    assert find_visitor_conversation(db, bot_id=bot_b.id, visitor_id=vid).id == cb.id


def test_different_visitors_do_not_share_conversation(db):
    user = _owner(db)
    bot = _bot(db, user)
    c1, v1, _ = get_or_create_visitor_conversation(db, bot, new_visitor_id())
    c2, v2, _ = get_or_create_visitor_conversation(db, bot, new_visitor_id())
    assert v1 != v2
    assert c1.id != c2.id


def test_expired_conversation_is_purged_and_recreated(db):
    user = _owner(db)
    bot = _bot(db, user)
    vid = new_visitor_id()
    conv, _, _ = get_or_create_visitor_conversation(db, bot, vid)
    conv.last_user_message_at = datetime.now(timezone.utc) - timedelta(hours=VISITOR_SESSION_TTL_HOURS + 1)
    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            message="hello",
        )
    )
    db.commit()

    assert is_conversation_expired(conv) is True
    hist = load_public_history(db, bot=bot, visitor_id=vid)
    assert hist["expired"] is True
    assert hist["messages"] == []
    assert find_visitor_conversation(db, bot_id=bot.id, visitor_id=vid) is None

    conv2, out, expired_reset = get_or_create_visitor_conversation(db, bot, vid)
    assert out == vid
    assert expired_reset is False
    msgs2 = db.execute(select(ChatbotMessage).where(ChatbotMessage.conversation_id == conv2.id)).scalars().all()
    assert msgs2 == []


def test_public_history_returns_messages_within_ttl(db):
    user = _owner(db)
    bot = _bot(db, user)
    vid = new_visitor_id()
    conv, _, _ = get_or_create_visitor_conversation(db, bot, vid)
    db.add(ChatbotMessage(conversation_id=conv.id, user_id=user.id, role="user", message="xin chào"))
    db.add(ChatbotMessage(conversation_id=conv.id, user_id=user.id, role="assistant", message="chào bạn"))
    conv.last_user_message_at = datetime.now(timezone.utc)
    db.commit()

    hist = load_public_history(db, bot=bot, visitor_id=vid)
    assert hist["visitor_id"] == vid
    assert len(hist.get("messages") or []) == 2
    assert hist["messages"][0]["role"] == "user"
    assert hist["messages"][1]["role"] == "bot"


def test_process_message_persists_for_reload(db):
    """Simulate chat → reload history (F5 / page change)."""
    from unittest.mock import patch

    user = _owner(db)
    bot = _bot(db, user)
    vid = new_visitor_id()

    ai_reply = {
        "reply": "Chúng tôi có khóa đào tạo SEO.",
        "used_ai": False,
        "show_lead": False,
        "no_data": False,
        "debug": {},
    }
    allowed = {
        "allowed": True,
        "code": "ok",
        "greeting": "Xin chào",
        "bot_id": bot.id,
        "bot_name": bot.bot_name,
    }
    with patch("app.services.chatbot_cskh_widget_service.evaluate_public_bot", return_value=allowed), patch(
        "app.services.chatbot_cskh_widget_service.generate_ai_reply", return_value=ai_reply
    ):
        sent = process_public_message(
            db,
            bot_id=bot.id,
            message="Tôi muốn hỏi về dịch vụ đào tạo SEO",
            visitor_id=vid,
            session_id=None,
        )
    assert sent.get("visitor_id") == vid

    hist = load_public_history(db, bot=bot, visitor_id=vid)
    texts = [m["text"] for m in hist.get("messages") or []]
    assert "Tôi muốn hỏi về dịch vụ đào tạo SEO" in texts
    assert "Chúng tôi có khóa đào tạo SEO." in texts


def test_purge_visitor_conversation_deletes_messages_and_leads(db):
    user = _owner(db)
    bot = _bot(db, user)
    vid = new_visitor_id()
    conv, _, _ = get_or_create_visitor_conversation(db, bot, vid)
    db.add(ChatbotMessage(conversation_id=conv.id, user_id=user.id, role="user", message="hi"))
    db.add(
        ChatbotLead(
            bot_id=bot.id,
            conversation_id=conv.id,
            user_id=user.id,
            phone="0900000000",
            status="new",
        )
    )
    db.commit()
    purge_visitor_conversation(db, conv)
    assert find_visitor_conversation(db, bot_id=bot.id, visitor_id=vid) is None
    assert db.execute(select(ChatbotMessage)).scalars().all() == []
