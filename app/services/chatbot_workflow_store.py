"""In-memory store cho workflow chatbot (pending confirm → running → result)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

# Giữ alias tương thích; message chi tiết dùng chatbot_workflow_credit.format_insufficient_credit_message
INSUFFICIENT_CREDIT_MSG = "Bạn cần {required} credit, tài khoản hiện có {balance} credit."

UI_PROGRESS_DEFS: tuple[tuple[str, str], ...] = (
    ("research", "Đang research từ khóa"),
    ("clustering", "Đang gom nhóm từ khóa"),
    ("outline", "Đang tạo outline"),
    ("writing", "Đang viết bài SEO"),
    ("internal_links", "Đang chèn internal link"),
    ("images", "Đang chèn hình ảnh"),
    ("saving", "Đang lưu bài viết"),
    ("complete", "Hoàn thành"),
)

_LOCK = Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def init_ui_progress(intent: str | None = None) -> list[dict[str, str]]:
    from app.services.chatbot_tab_registry import init_progress_for_intent

    if intent:
        return init_progress_for_intent(intent)
    return [{"id": sid, "label": label, "status": "pending"} for sid, label in UI_PROGRESS_DEFS]


def _now() -> float:
    return time.time()


@dataclass
class ChatbotWorkflowRecord:
    workflow_id: str
    user_id: int
    session_id: str
    intent: str
    phase: str
    params: dict[str, Any]
    credits: dict[str, int]
    balance: int
    sufficient: bool
    progress: list[dict[str, str]] = field(default_factory=init_ui_progress)
    run: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_public_dict(self, *, include_run: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "intent": self.intent,
            "phase": self.phase,
            "params": dict(self.params),
            "credits": dict(self.credits),
            "balance": self.balance,
            "sufficient": self.sufficient,
            "progress": [dict(x) for x in self.progress],
            "error": self.error,
            "updated_at": self.updated_at,
        }
        if include_run and self.run is not None:
            out["run"] = self.run
        return out


def _record_from_dict(data: dict[str, Any]) -> ChatbotWorkflowRecord:
    return ChatbotWorkflowRecord(
        workflow_id=str(data["workflow_id"]),
        user_id=int(data["user_id"]),
        session_id=str(data.get("session_id") or ""),
        intent=str(data.get("intent") or ""),
        phase=str(data.get("phase") or "pending_confirm"),
        params=dict(data.get("params") or {}),
        credits=dict(data.get("credits") or {}),
        balance=int(data.get("balance") or 0),
        sufficient=bool(data.get("sufficient")),
        progress=[dict(x) for x in (data.get("progress") or init_ui_progress())],
        run=data.get("run"),
        error=data.get("error"),
        created_at=float(data.get("created_at") or _now()),
        updated_at=float(data.get("updated_at") or _now()),
    )


def create_workflow_record(
    *,
    user_id: int,
    session_id: str,
    intent: str,
    params: dict[str, Any],
    credits: dict[str, int],
    balance: int,
    sufficient: bool,
) -> ChatbotWorkflowRecord:
    wf_id = "wf_" + uuid.uuid4().hex
    rec = ChatbotWorkflowRecord(
        workflow_id=wf_id,
        user_id=int(user_id),
        session_id=str(session_id or ""),
        intent=intent,
        phase="denied" if not sufficient else "pending_confirm",
        params=params,
        credits=credits,
        balance=balance,
        sufficient=sufficient,
        progress=init_ui_progress(intent),
    )
    with _LOCK:
        _JOBS[wf_id] = {
            "workflow_id": rec.workflow_id,
            "user_id": rec.user_id,
            "session_id": rec.session_id,
            "intent": rec.intent,
            "phase": rec.phase,
            "params": rec.params,
            "credits": rec.credits,
            "balance": rec.balance,
            "sufficient": rec.sufficient,
            "progress": rec.progress,
            "run": None,
            "error": None,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
        }
    return rec


def get_workflow_for_user(workflow_id: str, user_id: int) -> ChatbotWorkflowRecord | None:
    with _LOCK:
        raw = _JOBS.get(str(workflow_id or ""))
    if not raw:
        return None
    if int(raw.get("user_id") or 0) != int(user_id):
        return None
    return _record_from_dict(raw)


def update_workflow(workflow_id: str, **patch: Any) -> ChatbotWorkflowRecord | None:
    with _LOCK:
        raw = _JOBS.get(str(workflow_id or ""))
        if not raw:
            return None
        raw.update(patch)
        raw["updated_at"] = _now()
        return _record_from_dict(raw)


def set_ui_progress(workflow_id: str, step_id: str, status: str, label: str | None = None) -> None:
    with _LOCK:
        raw = _JOBS.get(str(workflow_id or ""))
        if not raw:
            return
        progress = [dict(x) for x in (raw.get("progress") or init_ui_progress())]
        for item in progress:
            if item.get("id") == step_id:
                item["status"] = status
                if label:
                    item["label"] = label
                break
        raw["progress"] = progress
        raw["updated_at"] = _now()


def cancel_workflow(workflow_id: str, user_id: int) -> bool:
    rec = get_workflow_for_user(workflow_id, user_id)
    if not rec:
        return False
    if rec.phase in ("completed", "failed", "cancelled", "running"):
        return rec.phase == "cancelled"
    update_workflow(workflow_id, phase="cancelled", error=None)
    return True
