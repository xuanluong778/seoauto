"""Chatbot CSKH — knowledge source management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chatbot_cskh import ChatbotBot, ChatbotKnowledgeSource
from app.models.user import User
from app.services.chatbot_cskh_page_crawler import CrawlFetchError, CrawlValidationError, fetch_and_extract_url
from app.services.cost_control.module_gates import chatbot_cskh_crawl_gate
from app.services.chatbot_cskh_logging import log_crawl_error

SOURCE_TYPES = frozenset({"faq", "business", "website"})
SOURCE_STATUSES = frozenset({"pending", "ready", "failed"})
MANUAL_SOURCE_TYPES = frozenset({"faq", "business"})

_LEGACY_TYPE_MAP = {
    "manual": "faq",
    "url": "website",
    "file": "business",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_source_type(source_type: str) -> str:
    st = str(source_type or "").strip().lower()
    st = _LEGACY_TYPE_MAP.get(st, st)
    if st not in SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_type không hợp lệ.")
    return st


def _get_user_bot(db: Session, user_id: int, bot_id: int) -> ChatbotBot:
    row = db.execute(
        select(ChatbotBot).where(ChatbotBot.id == int(bot_id), ChatbotBot.user_id == int(user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    return row


def _get_user_source(db: Session, user_id: int, source_id: int) -> ChatbotKnowledgeSource:
    row = db.execute(
        select(ChatbotKnowledgeSource).where(
            ChatbotKnowledgeSource.id == int(source_id),
            ChatbotKnowledgeSource.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nguồn dữ liệu.")
    return row


def knowledge_source_to_dict(row: ChatbotKnowledgeSource, *, full_content: bool = False) -> dict[str, Any]:
    content = row.content or ""
    return {
        "source_id": row.id,
        "id": row.id,
        "bot_id": row.bot_id,
        "source_type": row.source_type,
        "type": row.source_type,
        "title": row.title,
        "url": row.url or "",
        "content": content if full_content else content[:500],
        "content_preview": content[:280],
        "status": row.status,
        "error_message": row.crawl_error or "",
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at or row.created_at),
    }


def list_knowledge_for_bot(db: Session, user_id: int, bot_id: int) -> list[dict[str, Any]]:
    _get_user_bot(db, user_id, bot_id)
    rows = db.execute(
        select(ChatbotKnowledgeSource)
        .where(
            ChatbotKnowledgeSource.user_id == int(user_id),
            ChatbotKnowledgeSource.bot_id == int(bot_id),
        )
        .order_by(ChatbotKnowledgeSource.updated_at.desc(), ChatbotKnowledgeSource.id.desc())
    ).scalars().all()
    return [knowledge_source_to_dict(r, full_content=True) for r in rows]


def add_knowledge_source(
    db: Session,
    user_id: int,
    *,
    bot_id: int,
    source_type: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    st = _normalize_source_type(source_type)
    if st not in MANUAL_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ thêm thủ công loại faq hoặc business. Dùng crawl cho website.",
        )
    title_s = str(title or "").strip()
    if not title_s:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title không được để trống.")
    body = str(content or "").strip()
    if len(body) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nội dung quá ngắn (tối thiểu 10 ký tự).")

    row = ChatbotKnowledgeSource(
        bot_id=int(bot_id),
        user_id=int(user_id),
        source_type=st,
        title=title_s[:160],
        content=body,
        status="ready",
        crawl_error=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return knowledge_source_to_dict(row, full_content=True)


def update_knowledge_source(
    db: Session,
    user_id: int,
    source_id: int,
    *,
    title: str | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    row = _get_user_source(db, user_id, source_id)
    if row.source_type == "website":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nguồn quét website — dùng «Quét lại» để cập nhật nội dung.",
        )
    if title is not None:
        title_s = str(title).strip()
        if not title_s:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title không được để trống.")
        row.title = title_s[:160]
    if content is not None:
        body = str(content).strip()
        if len(body) < 10:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nội dung quá ngắn.")
        row.content = body
        row.status = "ready"
        row.crawl_error = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return knowledge_source_to_dict(row, full_content=True)


def delete_knowledge_source(db: Session, user_id: int, source_id: int) -> None:
    row = _get_user_source(db, user_id, source_id)
    db.delete(row)
    db.commit()


def _apply_crawl_result(row: ChatbotKnowledgeSource, *, url: str, result: dict[str, Any]) -> None:
    row.url = url[:2000]
    row.content = str(result.get("content") or "").strip()
    page_title = str(result.get("title") or "").strip()
    if page_title and (not row.title or row.title == url):
        row.title = page_title[:160]
    row.status = "ready"
    row.crawl_error = None
    row.updated_at = datetime.now(timezone.utc)


def _apply_crawl_failure(row: ChatbotKnowledgeSource, message: str) -> None:
    row.status = "failed"
    row.crawl_error = str(message or "Quét thất bại.")[:500]
    row.updated_at = datetime.now(timezone.utc)


def crawl_website_knowledge(
    db: Session,
    user_id: int,
    *,
    bot_id: int,
    url: str,
    title: str = "",
    source_id: int | None = None,
) -> dict[str, Any]:
    _get_user_bot(db, user_id, bot_id)
    url_s = str(url or "").strip()

    if source_id is not None:
        row = _get_user_source(db, user_id, int(source_id))
        if row.bot_id != int(bot_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source_id không thuộc bot này.")
        if row.source_type != "website":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chỉ quét lại nguồn loại website.")
        crawl_url = url_s or str(row.url or "").strip()
        if not crawl_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nguồn website không có URL để quét lại.")
    else:
        if not url_s:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url không được để trống.")
        title_s = str(title or "").strip() or url_s
        row = ChatbotKnowledgeSource(
            bot_id=int(bot_id),
            user_id=int(user_id),
            source_type="website",
            title=title_s[:160],
            url=url_s[:2000],
            content=None,
            status="pending",
            crawl_error=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        crawl_url = url_s

    row.status = "pending"
    row.crawl_error = None
    row.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        owner = db.get(User, int(user_id))
        if owner is None:
            raise CrawlFetchError("Không tìm thấy tài khoản.")
        with chatbot_cskh_crawl_gate(db, owner, action="knowledge_crawl", url=crawl_url):
            result = fetch_and_extract_url(crawl_url)
        _apply_crawl_result(row, url=crawl_url, result=result)
    except (CrawlValidationError, CrawlFetchError) as exc:
        log_crawl_error(bot_id=bot_id, url=crawl_url, error=str(exc), exc=exc)
        _apply_crawl_failure(row, str(exc))
        db.commit()
        db.refresh(row)
        return knowledge_source_to_dict(row, full_content=True)

    db.commit()
    db.refresh(row)
    return knowledge_source_to_dict(row, full_content=True)
