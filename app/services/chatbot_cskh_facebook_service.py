"""Chatbot CSKH — Facebook Fanpage / Messenger (beta, Pro+)."""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import requests
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.core.security import create_cskh_facebook_oauth_state, decode_cskh_facebook_oauth_state
from app.models.chatbot_cskh import ChatbotBot, ChatbotConversation, ChatbotFacebookPage, ChatbotMessage
from app.models.user import User
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.chatbot_cskh_ai_service import generate_ai_reply
from app.services.chatbot_cskh_credits import build_usage_snapshot, increment_reply_usage
from app.services.chatbot_cskh_entitlement import NO_DATA_REPLY
from app.services.chatbot_cskh_inbox_service import mark_conversation_needs_staff, upsert_detected_lead
from app.services.chatbot_cskh_logging import log_widget_error
from app.services.social_auto_facebook_oauth_config import effective_login_config_id
from app.services.social_auto_facebook_store import is_mock_mode

_LOG = logging.getLogger("chatbot_cskh.facebook")

GRAPH = "https://graph.facebook.com/v21.0"
CSKH_FB_SCOPES = "pages_show_list,pages_messaging,pages_manage_metadata"
MESSAGING_WINDOW_HOURS = 24
_MIN_REPLY_INTERVAL_SEC = 3

_rate_lock = Lock()
_last_reply: dict[str, float] = {}
_reply_buckets: dict[str, deque[float]] = defaultdict(deque)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _app_id() -> str:
    return str(os.getenv("FACEBOOK_APP_ID", "")).strip()


def _app_secret() -> str:
    return str(os.getenv("FACEBOOK_APP_SECRET", "")).strip()


def oauth_configured() -> bool:
    return not is_mock_mode()


def webhook_verify_token() -> str:
    return str(os.getenv("CSKH_FB_WEBHOOK_VERIFY_TOKEN") or os.getenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN") or "seoauto_cskh_fb").strip()


def _redirect_uri(request: Request) -> str:
    custom = str(os.getenv("CSKH_FB_REDIRECT_URI", "")).strip()
    if custom:
        return custom
    base = str(os.getenv("APP_BASE_URL") or "https://seoauto.vn").rstrip("/")
    return f"{base}/api/chatbot/facebook/oauth/callback"


def _get_user_bot(db: Session, user_id: int, bot_id: int) -> ChatbotBot:
    row = db.execute(
        select(ChatbotBot).where(ChatbotBot.id == int(bot_id), ChatbotBot.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    return row


def _page_token(row: ChatbotFacebookPage) -> str:
    return decrypt_secret(str(row.page_access_token_encrypted or "")).strip()


def page_to_public_dict(row: ChatbotFacebookPage) -> dict[str, Any]:
    return {
        "id": row.id,
        "page_id": row.page_id,
        "page_name": row.page_name,
        "bot_id": row.bot_id,
        "ai_enabled": bool(row.ai_enabled),
        "status": row.status,
        "webhook_subscribed": bool(row.webhook_subscribed),
        "has_token": bool(row.page_access_token_encrypted),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def list_facebook_pages(db: Session, user_id: int, *, bot_id: int | None = None) -> list[dict[str, Any]]:
    q = select(ChatbotFacebookPage).where(ChatbotFacebookPage.user_id == int(user_id))
    if bot_id is not None:
        q = q.where(ChatbotFacebookPage.bot_id == int(bot_id))
    rows = db.execute(q.order_by(ChatbotFacebookPage.updated_at.desc())).scalars().all()
    return [page_to_public_dict(r) for r in rows]


def list_channels_overview(db: Session, user_id: int) -> dict[str, Any]:
    """Website widgets (active bots) + Facebook pages for channels UI."""
    bots = db.execute(
        select(ChatbotBot).where(ChatbotBot.user_id == int(user_id)).order_by(ChatbotBot.updated_at.desc())
    ).scalars().all()
    website = [
        {
            "channel_type": "website",
            "bot_id": b.id,
            "bot_name": b.bot_name,
            "status": b.status,
            "label": f"Widget — {b.bot_name}",
        }
        for b in bots
    ]
    facebook = list_facebook_pages(db, user_id)
    for fb in facebook:
        fb["channel_type"] = "facebook"
        fb["label"] = fb.get("page_name") or fb.get("page_id")
    return {"website": website, "facebook": facebook}


def oauth_start_url(request: Request, user_id: int, bot_id: int) -> dict[str, Any]:
    if not oauth_configured():
        return {
            "mock": True,
            "url": f"/api/chatbot/facebook/oauth/mock-callback?state={create_cskh_facebook_oauth_state(user_id, bot_id)}",
        }
    app_id = _app_id()
    if not app_id:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Facebook App chưa cấu hình.")
    state = create_cskh_facebook_oauth_state(user_id, bot_id)
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "response_type": "code",
    }
    config_id = effective_login_config_id()
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = str(os.getenv("CSKH_FB_OAUTH_SCOPES", CSKH_FB_SCOPES)).strip() or CSKH_FB_SCOPES
    url = "https://www.facebook.com/v21.0/dialog/oauth?" + urllib.parse.urlencode(params)
    return {"mock": False, "url": url, "state": state}


def _exchange_code(code: str, redirect_uri: str) -> str:
    r = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Facebook token error: {(r.text or '')[:200]}")
    return str(r.json().get("access_token") or "").strip()


def _fetch_pages(user_token: str) -> list[dict[str, Any]]:
    r = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Không lấy được Fanpage: {(r.text or '')[:200]}")
    return [x for x in (r.json().get("data") or []) if isinstance(x, dict)]


def _subscribe_webhook(page_id: str, page_token: str) -> bool:
    try:
        r = requests.post(
            f"{GRAPH}/{page_id}/subscribed_apps",
            params={
                "access_token": page_token,
                "subscribed_fields": "messages,messaging_postbacks",
            },
            timeout=20,
        )
        return r.status_code < 400 and bool(r.json().get("success"))
    except Exception as exc:
        _LOG.warning("webhook subscribe failed page=%s: %s", page_id, exc)
        return False


def connect_page(
    db: Session,
    user_id: int,
    *,
    bot_id: int,
    page_id: str,
    page_name: str,
    page_access_token: str,
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    pid = str(page_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="page_id không hợp lệ.")
    token = str(page_access_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Thiếu page access token.")

    existing = db.execute(
        select(ChatbotFacebookPage).where(ChatbotFacebookPage.page_id == pid)
    ).scalar_one_or_none()
    if existing and (existing.user_id != int(user_id) or existing.bot_id != int(bot_id)):
        raise HTTPException(status_code=409, detail="Fanpage này đã được kết nối bởi bot khác.")

    subscribed = _subscribe_webhook(pid, token)
    if existing:
        row = existing
        row.page_name = str(page_name or pid)[:200]
        row.page_access_token_encrypted = encrypt_secret(token)
        row.status = "connected"
        row.ai_enabled = True
        row.webhook_subscribed = subscribed
        row.updated_at = _now()
    else:
        row = ChatbotFacebookPage(
            user_id=int(user_id),
            bot_id=int(bot_id),
            page_id=pid,
            page_name=str(page_name or pid)[:200],
            page_access_token_encrypted=encrypt_secret(token),
            ai_enabled=True,
            status="connected",
            webhook_subscribed=subscribed,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return page_to_public_dict(row)


def handle_oauth_callback(db: Session, request: Request, code: str, state: str) -> dict[str, Any]:
    try:
        user_id, bot_id = decode_cskh_facebook_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="State OAuth không hợp lệ.") from exc

    _get_user_bot(db, user_id, bot_id)
    if is_mock_mode():
        return connect_page(
            db,
            user_id,
            bot_id=bot_id,
            page_id="mock_page_001",
            page_name="Fanpage Demo CSKH",
            page_access_token="mock_token",
        )

    user_token = _exchange_code(code, _redirect_uri(request))
    pages = _fetch_pages(user_token)
    if not pages:
        raise HTTPException(status_code=400, detail="Không tìm thấy Fanpage nào bạn quản lý.")

    saved = []
    for pg in pages[:10]:
        pid = str(pg.get("id") or "")
        ptok = str(pg.get("access_token") or "").strip()
        pname = str(pg.get("name") or pid)
        if not pid or not ptok:
            continue
        saved.append(connect_page(db, user_id, bot_id=bot_id, page_id=pid, page_name=pname, page_access_token=ptok))
    if not saved:
        raise HTTPException(status_code=400, detail="Không lấy được token Fanpage.")
    return {"pages": saved, "count": len(saved)}


def mock_oauth_connect(db: Session, state: str) -> dict[str, Any]:
    user_id, bot_id = decode_cskh_facebook_oauth_state(state)
    return connect_page(
        db,
        user_id,
        bot_id=bot_id,
        page_id="mock_page_001",
        page_name="Fanpage Demo CSKH",
        page_access_token="mock_token",
    )


def set_ai_enabled(db: Session, user_id: int, page_row_id: int, *, enabled: bool) -> dict[str, Any]:
    row = db.execute(
        select(ChatbotFacebookPage).where(
            ChatbotFacebookPage.id == int(page_row_id),
            ChatbotFacebookPage.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy kết nối Fanpage.")
    row.ai_enabled = bool(enabled)
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return page_to_public_dict(row)


def disconnect_page(db: Session, user_id: int, page_row_id: int) -> None:
    row = db.execute(
        select(ChatbotFacebookPage).where(
            ChatbotFacebookPage.id == int(page_row_id),
            ChatbotFacebookPage.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy kết nối Fanpage.")
    db.delete(row)
    db.commit()


def _within_messaging_window(conv: ChatbotConversation) -> bool:
    ts = conv.last_user_message_at
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (_now() - ts) <= timedelta(hours=MESSAGING_WINDOW_HOURS)


def _can_auto_reply(page_id: str, psid: str) -> bool:
    key = f"{page_id}:{psid}"
    now = time.time()
    with _rate_lock:
        last = _last_reply.get(key, 0.0)
        if now - last < _MIN_REPLY_INTERVAL_SEC:
            return False
        bucket = _reply_buckets[key]
        while bucket and bucket[0] < now - 3600:
            bucket.popleft()
        if len(bucket) >= 30:
            return False
        _last_reply[key] = now
        bucket.append(now)
    return True


def _session_id(page_id: str, psid: str) -> str:
    return f"fb_{page_id}_{psid}"[:64]


def _get_or_create_fb_conversation(
    db: Session,
    *,
    bot: ChatbotBot,
    page_id: str,
    psid: str,
) -> ChatbotConversation:
    sid = _session_id(page_id, psid)
    row = db.execute(
        select(ChatbotConversation).where(
            ChatbotConversation.bot_id == bot.id,
            ChatbotConversation.session_id == sid,
        )
    ).scalar_one_or_none()
    if row:
        return row
    row = ChatbotConversation(
        bot_id=bot.id,
        user_id=bot.user_id,
        session_id=sid,
        channel="facebook",
        external_user_id=str(psid)[:64],
        channel_ref=str(page_id)[:64],
        status="open",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _send_text_message(page_id: str, page_token: str, psid: str, text: str) -> bool:
    if is_mock_mode() or str(page_token).startswith("mock"):
        _LOG.info("mock send page=%s psid=%s text=%s", page_id, psid, text[:80])
        return True
    try:
        r = requests.post(
            f"{GRAPH}/{page_id}/messages",
            params={"access_token": page_token},
            json={"recipient": {"id": psid}, "message": {"text": str(text or "")[:2000]}},
            timeout=25,
        )
        if r.status_code >= 400:
            _LOG.warning("send failed page=%s: %s", page_id, (r.text or "")[:300])
            return False
        return True
    except Exception as exc:
        _LOG.warning("send exception page=%s: %s", page_id, exc)
        return False


def process_messenger_webhook(db: Session, payload: dict[str, Any]) -> None:
    """Handle Meta Messenger webhook — only reply inside 24h window, no proactive spam."""
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id") or "")
        if not page_id:
            continue
        fb_page = db.execute(
            select(ChatbotFacebookPage).where(
                ChatbotFacebookPage.page_id == page_id,
                ChatbotFacebookPage.status == "connected",
            )
        ).scalar_one_or_none()
        if fb_page is None:
            continue

        bot = db.get(ChatbotBot, fb_page.bot_id)
        if bot is None or str(bot.status or "").lower() != "active":
            continue

        for event in entry.get("messaging") or []:
            if not isinstance(event, dict):
                continue
            _handle_messaging_event(db, fb_page=fb_page, bot=bot, event=event)


def _handle_messaging_event(
    db: Session,
    *,
    fb_page: ChatbotFacebookPage,
    bot: ChatbotBot,
    event: dict[str, Any],
) -> None:
    sender = event.get("sender") or {}
    psid = str(sender.get("id") or "")
    if not psid:
        return

    message = event.get("message") or {}
    if message.get("is_echo"):
        return
    text = str(message.get("text") or "").strip()
    if not text:
        return

    if not _can_auto_reply(fb_page.page_id, psid):
        log_widget_error(bot_id=bot.id, code="fb_rate_limited", detail=f"page={fb_page.page_id}")
        return

    conv = _get_or_create_fb_conversation(db, bot=bot, page_id=fb_page.page_id, psid=psid)
    conv.channel_ref = str(fb_page.page_name or fb_page.page_id)[:128]
    conv.last_user_message_at = _now()
    conv.updated_at = _now()
    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=bot.user_id,
            role="user",
            message=text[:2000],
        )
    )
    db.commit()

    upsert_detected_lead(db, bot=bot, conversation=conv, text=text, page_url=f"facebook:{fb_page.page_id}")

    if not fb_page.ai_enabled:
        mark_conversation_needs_staff(db, conv)
        return

    owner = db.get(User, bot.user_id)
    plan_slug = resolve_cau_ai_plan_slug(db, owner) if owner else None
    usage = build_usage_snapshot(db, bot.user_id, plan_slug)
    if not usage.get("allowed"):
        _send_text_message(
            fb_page.page_id,
            _page_token(fb_page),
            psid,
            "Hiện bot đã đạt giới hạn trả lời tháng này. Nhân viên sẽ hỗ trợ bạn sớm.",
        )
        mark_conversation_needs_staff(db, conv)
        return

    if not _within_messaging_window(conv):
        mark_conversation_needs_staff(db, conv)
        return

    try:
        ai_result = generate_ai_reply(
            db,
            bot=bot,
            conversation_id=conv.id,
            user_text=text,
            greeting_fallback="",
        )
    except Exception as exc:
        log_widget_error(bot_id=bot.id, code="fb_ai_error", detail=str(exc))
        ai_result = {"reply": NO_DATA_REPLY, "used_ai": False, "show_lead": False}

    reply = str(ai_result.get("reply") or NO_DATA_REPLY)
    show_lead = bool(ai_result.get("show_lead")) or bool(ai_result.get("no_data"))
    if show_lead:
        mark_conversation_needs_staff(db, conv)

    db.add(
        ChatbotMessage(
            conversation_id=conv.id,
            user_id=bot.user_id,
            role="assistant",
            message=reply[:2000],
        )
    )
    conv.updated_at = _now()
    db.commit()

    if ai_result.get("used_ai"):
        increment_reply_usage(db, bot.user_id, bot.id, replies=1)

    if _within_messaging_window(conv):
        _send_text_message(fb_page.page_id, _page_token(fb_page), psid, reply)
