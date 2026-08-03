"""Floating chatbot API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.models.user import User
from app.services.auth import get_current_user, get_optional_current_user
from app.services.chatbot_service import (
    get_history,
    list_quick_prompts,
    process_message,
    sanitize_user_text,
)

router = APIRouter(tags=["chatbot"])


class ChatTurn(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list)
    page_path: str = Field(default="/", max_length=512)
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    page_context: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatTurn]


class QuickPromptsResponse(BaseModel):
    prompts: list[dict[str, str]]


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return str(request.client.host or "")[:64]
    return ""


@router.get("/prompts", response_model=QuickPromptsResponse)
def get_quick_prompts() -> QuickPromptsResponse:
    return QuickPromptsResponse(prompts=list_quick_prompts())


@router.get("/history", response_model=HistoryResponse)
def get_chat_history(
    session_id: str = Query(..., min_length=8, max_length=64),
    current_user: User = Depends(get_current_user),
) -> HistoryResponse:
    from app.services.chatbot_service import assert_session_access

    try:
        assert_session_access(session_id, current_user.id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    rows = get_history(session_id, user_id=current_user.id)
    return HistoryResponse(
        session_id=session_id,
        messages=[ChatTurn(role=r["role"], content=r["content"]) for r in rows],
    )


@router.post("/message", response_model=ChatResponse)
def post_message(
    body: ChatRequest,
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
) -> ChatResponse:
    safe = sanitize_user_text(body.message)
    if not safe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tin nhắn không hợp lệ.")

    history = [{"role": t.role, "content": sanitize_user_text(t.content, max_len=2000)} for t in body.history]
    page_path = sanitize_user_text(body.page_path, max_len=512) or "/"

    out = process_message(
        message=safe,
        history=history,
        page_path=page_path,
        user=current_user,
        client_ip=_client_ip(request),
        session_id=body.session_id,
    )
    return ChatResponse(
        reply=out["reply"],
        session_id=out["session_id"],
        page_context=out.get("page_context"),
    )
