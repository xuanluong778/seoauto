"""Chatbot CSKH unread email notifications: delay, batch, cooldown, tenant isolation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.chatbot_cskh import (
    ChatbotBot,
    ChatbotConversation,
    ChatbotEmailNotifyJob,
    ChatbotEmailNotifyLog,
    ChatbotEmailNotifySetting,
    ChatbotMessage,
)
from app.models.user import User
from app.services.chatbot_cskh_email_notify import (
    execute_notify_job,
    hook_inbound_saved,
    mark_conversation_read,
    schedule_unread_email_job,
)


@pytest.fixture()
def db(monkeypatch):
    import app.models.knowledge  # noqa: F401
    import app.models.seo  # noqa: F401

    monkeypatch.setenv("CHATBOT_NOTIFY_DELAY_SECONDS", "120")
    monkeypatch.setenv("CHATBOT_NOTIFY_COOLDOWN_SECONDS", "900")
    monkeypatch.setenv("APP_BASE_URL", "https://seoauto.vn")
    monkeypatch.setenv("RESEND_API_KEY", "")
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
            ChatbotEmailNotifyJob.__table__,
            ChatbotEmailNotifySetting.__table__,
            ChatbotEmailNotifyLog.__table__,
        ],
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_cskh_notify_pending_org_conv "
                "ON chatbot_email_notify_jobs (organization_id, conversation_id) "
                "WHERE status = 'pending'"
            )
        )
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _user(db, email: str = "owner@test.local") -> User:
    u = User(email=email, password_hash="x", has_password=True, role="user", status="active")
    db.add(u)
    db.flush()
    return u


def _bot(db, user: User) -> ChatbotBot:
    bot = ChatbotBot(user_id=user.id, bot_name="Bot test", status="active")
    db.add(bot)
    db.flush()
    return bot


def _conv(db, user: User, bot: ChatbotBot, *, channel: str = "website") -> ChatbotConversation:
    conv = ChatbotConversation(
        bot_id=bot.id,
        user_id=user.id,
        organization_id=user.id,
        session_id=f"sess-{user.id}-{bot.id}",
        channel=channel,
        visitor_name="Khách A",
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


def _pending_jobs(db):
    return list(db.execute(select(ChatbotEmailNotifyJob).where(ChatbotEmailNotifyJob.status == "pending")).scalars())


def test_unread_inbound_schedules_one_job(db, monkeypatch):
    enqueued = []
    monkeypatch.setattr(
        "app.services.chatbot_cskh_email_notify._enqueue_celery",
        lambda job_id, countdown: enqueued.append((job_id, countdown)) or f"task-{job_id}",
    )
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    m1 = _inbound(db, conv, "Xin chào, cần sửa laptop")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=m1)
    assert job is not None
    assert job.status == "pending"
    assert job.organization_id == owner.id
    assert job.user_id == owner.id
    assert job.conversation_id == conv.id
    assert enqueued and enqueued[0][1] >= 100
    m2 = _inbound(db, conv, "Giá bao nhiêu?")
    db.commit()
    job2 = schedule_unread_email_job(db, conversation=conv, message=m2)
    assert job2.id == job.id
    assert len(_pending_jobs(db)) == 1
    assert len(enqueued) == 1


def test_assistant_outbound_does_not_schedule(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    assistant = ChatbotMessage(
        conversation_id=conv.id,
        user_id=owner.id,
        role="assistant",
        message="Dạ em hỗ trợ ạ",
    )
    db.add(assistant)
    db.flush()
    assert schedule_unread_email_job(db, conversation=conv, message=assistant) is None
    assert db.execute(select(ChatbotEmailNotifyJob)).scalars().all() == []


def test_read_cancels_send(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent: list = []
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "Chưa đọc")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)
    mark_conversation_read(db, owner.id, conv.id, commit=True)
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert out.get("skipped") is True
    assert out.get("reason") == "already_read"
    assert sent == []
    db.refresh(job)
    assert job.status == "cancelled"


def test_unread_sends_batched_email(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent: list = []
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    m1 = _inbound(db, conv, "Tin 1")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=m1)
    _inbound(db, conv, "Tin 2 mới nhất")
    db.commit()
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw) or {"id": "re_1"})
    assert out.get("reason") == "sent"
    assert out.get("unread_count") == 2
    assert len(sent) == 1
    body = sent[0]["html_body"]
    assert "Tin 2 mới nhất" in body
    assert "Số tin chưa đọc" in body
    assert "Xem cuộc trò chuyện" in body
    assert f"conversation_id={conv.id}" in body
    assert sent[0]["to"] == owner.email
    db.refresh(job)
    assert job.status == "sent"
    retry = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert retry.get("duplicate") is True
    assert len(sent) == 1


def test_handled_counts_as_replied(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent: list = []
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "Cần tư vấn")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)
    conv.status = "handled"
    db.commit()
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert out.get("reason") == "already_replied"
    assert sent == []


def test_cooldown_blocks_second_send(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent: list = []
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    m1 = _inbound(db, conv, "Lần 1")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=m1)
    execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    m2 = _inbound(db, conv, "Lần 2 ngay sau đó")
    db.commit()
    job2 = schedule_unread_email_job(db, conversation=conv, message=m2)
    out = execute_notify_job(db, job2.id, send_fn=lambda **kw: sent.append(kw))
    assert out.get("reason") == "cooldown"
    assert len(sent) == 1


def test_tenant_mismatch_skips(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent: list = []
    a = _user(db, "a@test.local")
    b = _user(db, "b@test.local")
    bot_a = _bot(db, a)
    conv_a = _conv(db, a, bot_a)
    msg = _inbound(db, conv_a, "Của A")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv_a, message=msg)
    job.user_id = b.id
    job.organization_id = b.id
    db.commit()
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert out.get("reason") == "tenant_mismatch"
    assert sent == []


def test_hook_swallows_enqueue_errors(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.chatbot_cskh_email_notify.schedule_unread_email_job",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "ok")
    hook_inbound_saved(db, conv, msg)


def _log_statuses(db, *, user_id=None):
    q = select(ChatbotEmailNotifyLog)
    if user_id is not None:
        q = q.where(ChatbotEmailNotifyLog.user_id == int(user_id))
    return [r.status for r in db.execute(q.order_by(ChatbotEmailNotifyLog.id.asc())).scalars().all()]


def test_settings_toggle_delay_and_email(db, monkeypatch):
    enqueued = []
    monkeypatch.setattr(
        "app.services.chatbot_cskh_email_notify._enqueue_celery",
        lambda job_id, countdown: enqueued.append((job_id, countdown)) or f"task-{job_id}",
    )
    from app.services.chatbot_cskh_email_settings import save_notify_settings

    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    save_notify_settings(
        db,
        user_id=owner.id,
        organization_id=owner.id,
        enabled=True,
        notify_email="alerts@inbox.test",
        delay_seconds=0,
        owner=owner,
    )
    msg = _inbound(db, conv, "Gửi ngay")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)
    assert job is not None
    assert enqueued and enqueued[0][1] <= 1
    assert "queued" in _log_statuses(db, user_id=owner.id)
    sent = []
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw) or {"id": "re_1"})
    assert out["to"] == "alerts@inbox.test"
    assert sent[0]["to"] == "alerts@inbox.test"
    assert "sent" in _log_statuses(db, user_id=owner.id)

    save_notify_settings(db, user_id=owner.id, organization_id=owner.id, delay_seconds=600, owner=owner)
    conv2 = ChatbotConversation(
        bot_id=bot.id,
        user_id=owner.id,
        organization_id=owner.id,
        session_id="sess-delay-10",
        channel="website",
        visitor_name="Khách B",
        status="open",
    )
    db.add(conv2)
    db.flush()
    m2 = _inbound(db, conv2, "Chờ 10 phút")
    db.commit()
    job2 = schedule_unread_email_job(db, conversation=conv2, message=m2)
    assert job2 is not None
    assert enqueued[-1][1] >= 590

    save_notify_settings(db, user_id=owner.id, organization_id=owner.id, enabled=False, owner=owner)
    conv3 = ChatbotConversation(
        bot_id=bot.id,
        user_id=owner.id,
        organization_id=owner.id,
        session_id="sess-off",
        channel="website",
        status="open",
    )
    db.add(conv3)
    db.flush()
    m3 = _inbound(db, conv3, "Khi tắt")
    db.commit()
    assert schedule_unread_email_job(db, conversation=conv3, message=m3) is None
    assert "skipped_disabled" in _log_statuses(db, user_id=owner.id)


def test_disabled_cancels_pending_job(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    from app.services.chatbot_cskh_email_settings import save_notify_settings

    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "pending")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)
    save_notify_settings(db, user_id=owner.id, organization_id=owner.id, enabled=False, owner=owner)
    db.refresh(job)
    assert job.status == "cancelled"
    sent = []
    out = execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert out.get("skipped") is True
    assert sent == []
    assert "skipped_disabled" in _log_statuses(db, user_id=owner.id)


def test_two_tenants_do_not_cross_send(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    from app.services.chatbot_cskh_email_settings import save_notify_settings

    a = _user(db, "a@test.local")
    b = _user(db, "b@test.local")
    save_notify_settings(db, user_id=a.id, organization_id=a.id, notify_email="inbox-a@x.test", owner=a)
    save_notify_settings(db, user_id=b.id, organization_id=b.id, enabled=False, owner=b)
    bot_a = _bot(db, a)
    bot_b = _bot(db, b)
    conv_a = _conv(db, a, bot_a)
    conv_b = ChatbotConversation(
        bot_id=bot_b.id,
        user_id=b.id,
        organization_id=b.id,
        session_id="sess-b",
        channel="website",
        status="open",
    )
    db.add(conv_b)
    db.flush()
    ma = _inbound(db, conv_a, "A unread")
    mb = _inbound(db, conv_b, "B unread")
    db.commit()
    job_a = schedule_unread_email_job(db, conversation=conv_a, message=ma)
    assert schedule_unread_email_job(db, conversation=conv_b, message=mb) is None
    sent = []
    out = execute_notify_job(db, job_a.id, send_fn=lambda **kw: sent.append(kw) or {"id": "ok"})
    assert out["to"] == "inbox-a@x.test"
    assert sent[0]["to"] == "inbox-a@x.test"
    assert "inbox-b" not in str(sent)


def test_read_logs_skipped_read(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "đọc")
    db.commit()
    schedule_unread_email_job(db, conversation=conv, message=msg)
    mark_conversation_read(db, owner.id, conv.id, commit=True)
    assert "skipped_read" in _log_statuses(db, user_id=owner.id)


def test_failed_send_is_logged_without_secrets(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    from app.services.chatbot_cskh_email_settings import sanitize_log_detail

    assert "re_" not in (sanitize_log_detail("Authorization Bearer re_SECRETX123") or "")
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "fail")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)

    def boom(**kw):
        raise RuntimeError("resend_http_401:Authorization Bearer re_SECRETX123")

    out = execute_notify_job(db, job.id, send_fn=boom)
    assert out.get("reason") == "resend_http_401"
    db.refresh(job)
    assert job.status == "failed"
    logs = list(db.execute(select(ChatbotEmailNotifyLog).where(ChatbotEmailNotifyLog.job_id == job.id)).scalars())
    details = " ".join(str(x.detail or "") for x in logs)
    assert "re_SECRETX123" not in details
    assert "Bearer" not in details
    retry = execute_notify_job(db, job.id, send_fn=boom)
    assert retry.get("skipped") is True or retry.get("duplicate") is True


def test_worker_restart_does_not_resend(db, monkeypatch):
    monkeypatch.setattr("app.services.chatbot_cskh_email_notify._enqueue_celery", lambda *a, **k: "t")
    sent = []
    owner = _user(db)
    bot = _bot(db, owner)
    conv = _conv(db, owner, bot)
    msg = _inbound(db, conv, "một lần")
    db.commit()
    job = schedule_unread_email_job(db, conversation=conv, message=msg)
    execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw) or {"id": "re_1"})
    execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    execute_notify_job(db, job.id, send_fn=lambda **kw: sent.append(kw))
    assert len(sent) == 1
    sent_logs = [s for s in _log_statuses(db, user_id=owner.id) if s == "sent"]
    assert sent_logs == ["sent"]
