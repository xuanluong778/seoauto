"""Chat tab: hỏi đáp thường, gợi ý chuyển tab workflow — không chạy workflow / trừ credit."""

from __future__ import annotations

import re
from typing import Any

from app.services.chatbot_command_parser import WorkflowParseResult, _is_workflow_command
from app.services.chatbot_tab_registry import (
    CHATBOT_TABS,
    TAB_RESEARCH,
    TAB_SEO_SCORE,
    TAB_TECHNICAL,
    TAB_WRITE,
    tab_for_intent,
)

_TAB_LABELS = {str(t.get("id") or ""): str(t.get("label") or "") for t in CHATBOT_TABS}


def _label_for_tab(tab_id: str) -> str:
    return _TAB_LABELS.get(str(tab_id or "").strip(), str(tab_id or "Workflow"))


def _guess_tab_from_text(text: str) -> tuple[str, str] | None:
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not t:
        return None
    write_kw = (
        "viết bài",
        "viết nhanh",
        "gom nhóm",
        "gom cụm",
        "outline",
        "viết seo",
        "tạo bài",
    )
    score_kw = ("chấm điểm", "seo score", "scoreboard", "điểm seo")
    tech_kw = ("audit", "technical", "kiểm tra url", "crawl web", "robots.txt", "sitemap")
    research_kw = ("research từ khóa", "từ khóa liên quan", "mở rộng từ khóa", "gom nhóm từ khóa")

    if any(k in t for k in write_kw):
        return TAB_WRITE, _label_for_tab(TAB_WRITE)
    if any(k in t for k in score_kw):
        return TAB_SEO_SCORE, _label_for_tab(TAB_SEO_SCORE)
    if any(k in t for k in tech_kw):
        return TAB_TECHNICAL, _label_for_tab(TAB_TECHNICAL)
    if any(k in t for k in research_kw):
        return TAB_RESEARCH, _label_for_tab(TAB_RESEARCH)
    return None


def detect_workflow_tab_suggestion(
    message: str,
    workflow: WorkflowParseResult | None = None,
) -> tuple[str, str] | None:
    """Trả (tab_id, tab_label) nếu tin nhắn giống yêu cầu workflow."""
    wf = workflow or WorkflowParseResult()
    if wf.is_workflow and wf.intent:
        tab_id = tab_for_intent(str(wf.intent))
        return tab_id, _label_for_tab(tab_id)
    if _is_workflow_command(message):
        guessed = _guess_tab_from_text(message)
        if guessed:
            return guessed
        return TAB_WRITE, _label_for_tab(TAB_WRITE)
    return _guess_tab_from_text(message)


def build_chat_mode_workflow_reply(tab_id: str, tab_label: str) -> str:
    return (
        f"Yêu cầu của bạn thuộc tính năng **{tab_label}** (workflow AI, có thể tính credit).\n\n"
        f"Tab **Chat** chỉ dùng để hỏi đáp thông thường — tôi **không tự chạy** workflow từ đây.\n\n"
        f"Bấm **Chuyển sang {tab_label}** để mở form, xem credit và xác nhận trước khi chạy."
    )


def chat_mode_workflow_response(
    *,
    message: str,
    workflow: WorkflowParseResult,
    session_id: str,
    page_context: str | None,
) -> dict[str, Any] | None:
    """Nếu tin nhắn giống workflow, trả gợi ý chuyển tab (không chạy workflow)."""
    hit = detect_workflow_tab_suggestion(message, workflow)
    if not hit:
        return None
    tab_id, tab_label = hit
    return {
        "reply": build_chat_mode_workflow_reply(tab_id, tab_label),
        "session_id": session_id,
        "page_context": page_context,
        "chat_mode": True,
        "suggest_tab": tab_id,
        "suggest_tab_label": tab_label,
        "workflow": None,
    }
