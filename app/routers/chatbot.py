"""Floating chatbot API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user, get_optional_current_user
from app.services.chatbot_service import (
    get_history,
    list_quick_prompts,
    process_message,
    sanitize_user_text,
)
from app.services.chatbot_workflow_credit import InsufficientCreditError
from app.services.chatbot_workflow_service import (
    cancel_workflow,
    get_workflow_result,
    get_workflow_status,
    prepare_workflow_from_params,
    preview_workflow_outline,
    start_workflow,
)
from app.services.chatbot_tab_registry import CHATBOT_TABS
from sqlalchemy.orm import Session

router = APIRouter(tags=["chatbot"])


class ChatTurn(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list)
    page_path: str = Field(default="/", max_length=512)
    session_id: str | None = Field(default=None, max_length=64)
    chat_mode: bool = Field(default=False, description="Tab Chat: FAQ only, suggest workflow tabs")


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    page_context: str | None = None
    workflow: dict[str, Any] | None = None
    chat_mode: bool | None = None
    suggest_tab: str | None = None
    suggest_tab_label: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatTurn]


class QuickPromptsResponse(BaseModel):
    prompts: list[dict[str, str]]


class WorkflowPrepareBody(BaseModel):
    intent: str = Field(..., min_length=3, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=64)
    planning_snapshot: dict[str, Any] | None = None


class WorkflowPreviewOutlineBody(BaseModel):
    intent: str = Field(..., min_length=3, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowPreviewOutlineResponse(BaseModel):
    intent: str
    params: dict[str, Any]
    planning: dict[str, Any]
    credits: dict[str, int]
    balance: int
    sufficient: bool
    credit_required: int | None = None
    credit_balance: int | None = None
    credit_estimate_message: str | None = None
    insufficient_message: str | None = None
    image_count_preview: int | None = None


class WorkflowPrepareResponse(BaseModel):
    workflow_id: str
    intent: str
    tab_id: str
    phase: str
    params: dict[str, Any]
    credits: dict[str, int]
    balance: int
    sufficient: bool
    credit_required: int | None = None
    credit_balance: int | None = None
    credit_estimate_message: str | None = None
    insufficient_message: str | None = None
    image_count_preview: int | None = None
    planning: dict[str, Any] | None = None


class ChatbotTabsResponse(BaseModel):
    tabs: list[dict[str, Any]]


@router.get("/tabs", response_model=ChatbotTabsResponse)
def get_chatbot_tabs() -> ChatbotTabsResponse:
    return ChatbotTabsResponse(tabs=CHATBOT_TABS)


@router.post("/workflows/preview-outline", response_model=WorkflowPreviewOutlineResponse)
def post_workflow_preview_outline(
    body: WorkflowPreviewOutlineBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowPreviewOutlineResponse:
    try:
        out = preview_workflow_outline(
            db,
            user_id=current_user.id,
            intent=body.intent.strip(),
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WorkflowPreviewOutlineResponse(**out)


@router.post("/workflows/prepare", response_model=WorkflowPrepareResponse)
def post_workflow_prepare(
    body: WorkflowPrepareBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowPrepareResponse:
    try:
        out = prepare_workflow_from_params(
            db,
            user_id=current_user.id,
            session_id=str(body.session_id or ""),
            intent=body.intent.strip(),
            params=body.params,
            planning_snapshot=body.planning_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return WorkflowPrepareResponse(**out)


class WorkflowStartBody(BaseModel):
    workflow_id: str = Field(..., min_length=8, max_length=80)


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    intent: str | None = None
    phase: str
    progress: list[dict[str, str]] = Field(default_factory=list)
    credits: dict[str, int] | None = None
    balance: int | None = None
    sufficient: bool | None = None
    error: str | None = None


class WorkflowResultResponse(BaseModel):
    workflow_id: str
    phase: str
    ready: bool
    progress: list[dict[str, str]] = Field(default_factory=list)
    run: dict[str, Any] | None = None
    reply: str | None = None
    error: str | None = None
    actions: list[dict[str, str]] | None = None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return str(request.client.host or "")[:64]
    return ""


def _workflow_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow không tồn tại.")


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
        chat_mode=bool(body.chat_mode),
    )
    return ChatResponse(
        reply=out["reply"],
        session_id=out["session_id"],
        page_context=out.get("page_context"),
        workflow=out.get("workflow"),
        chat_mode=out.get("chat_mode"),
        suggest_tab=out.get("suggest_tab"),
        suggest_tab_label=out.get("suggest_tab_label"),
    )


@router.post("/workflows/start", response_model=WorkflowStatusResponse)
def post_workflow_start(
    body: WorkflowStartBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowStatusResponse:
    try:
        rec = start_workflow(db, user_id=current_user.id, workflow_id=body.workflow_id.strip())
    except PermissionError as exc:
        raise _workflow_not_found() from exc
    except InsufficientCreditError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": exc.message,
                "required": exc.required,
                "balance": exc.balance,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    pub = rec.to_public_dict()
    return WorkflowStatusResponse(
        workflow_id=pub["workflow_id"],
        intent=pub.get("intent"),
        phase=pub["phase"],
        progress=pub.get("progress") or [],
        credits=pub.get("credits"),
        balance=pub.get("balance"),
        sufficient=pub.get("sufficient"),
        error=pub.get("error"),
    )


@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse)
def get_workflow_status_endpoint(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
) -> WorkflowStatusResponse:
    try:
        pub = get_workflow_status(current_user.id, workflow_id.strip())
    except PermissionError as exc:
        raise _workflow_not_found() from exc
    return WorkflowStatusResponse(
        workflow_id=pub["workflow_id"],
        intent=pub.get("intent"),
        phase=pub["phase"],
        progress=pub.get("progress") or [],
        credits=pub.get("credits"),
        balance=pub.get("balance"),
        sufficient=pub.get("sufficient"),
        error=pub.get("error"),
    )


@router.get("/workflows/{workflow_id}/result", response_model=WorkflowResultResponse)
def get_workflow_result_endpoint(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
) -> WorkflowResultResponse:
    try:
        pub = get_workflow_result(current_user.id, workflow_id.strip())
    except PermissionError as exc:
        raise _workflow_not_found() from exc

    run = pub.get("run") if isinstance(pub.get("run"), dict) else None
    actions = list(run.get("actions") or []) if run else None
    return WorkflowResultResponse(
        workflow_id=pub["workflow_id"],
        phase=pub["phase"],
        ready=bool(pub.get("ready")),
        progress=pub.get("progress") or [],
        run=run,
        reply=pub.get("reply"),
        error=pub.get("error"),
        actions=actions,
    )


@router.post("/workflows/{workflow_id}/cancel")
def post_workflow_cancel(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ok = cancel_workflow(current_user.id, workflow_id.strip())
    if not ok:
        raise _workflow_not_found()
    return {"ok": True, "workflow_id": workflow_id.strip(), "phase": "cancelled"}
