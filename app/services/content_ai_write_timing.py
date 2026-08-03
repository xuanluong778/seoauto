"""Step timing for Content AI / chatbot write flows — safe logs (no secrets, no full HTML)."""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

_LOG = logging.getLogger("content_ai.write_timing")

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "content_ai_write_request_id", default=None
)
_TIMER: contextvars.ContextVar["ContentAiWriteTimer | None"] = contextvars.ContextVar(
    "content_ai_write_timer", default=None
)


def bind_write_timer(timer: ContentAiWriteTimer) -> None:
    _TIMER.set(timer)
    _REQUEST_ID.set(timer.request_id)


def current_write_timer() -> ContentAiWriteTimer | None:
    return _TIMER.get()


def mark_step(step: str, **extra: Any) -> None:
    timer = current_write_timer()
    if timer is not None:
        timer.mark(step, **extra)

# Canonical step names (for reports & dashboards)
STEP_VALIDATE = "validate_input"
STEP_PLAN_CREDIT = "check_plan_credit"
STEP_WEBSITE_CONTEXT = "fetch_website_context"
STEP_RESEARCH = "research"
STEP_OUTLINE = "outline"
STEP_LLM = "llm_generate"
STEP_WORD_COUNT = "word_count_check"
STEP_REPAIR = "repair_word_count"
STEP_IMAGES = "process_images"
STEP_SAVE = "save_project"
STEP_RESPONSE = "return_response"


def get_write_request_id() -> str | None:
    return _REQUEST_ID.get()


class ContentAiWriteTimer:
    """Accumulates per-step elapsed ms from flow start."""

    def __init__(self, *, endpoint: str, request_id: str | None = None, user_id: int | None = None):
        self.request_id = (request_id or uuid.uuid4().hex[:16])[:32]
        self.endpoint = str(endpoint or "")[:80]
        self.user_id = int(user_id) if user_id else None
        self._t0 = time.perf_counter()
        self._last = self._t0
        self._steps: list[dict[str, Any]] = []
        _REQUEST_ID.set(self.request_id)

    def mark(self, step: str, **extra: Any) -> int:
        now = time.perf_counter()
        delta_ms = int((now - self._last) * 1000)
        total_ms = int((now - self._t0) * 1000)
        self._last = now
        row = {"step": str(step), "delta_ms": delta_ms, "total_ms": total_ms}
        if extra:
            row.update({k: v for k, v in extra.items() if v is not None})
        self._steps.append(row)
        _LOG.info(
            "content_ai_timing request_id=%s user_id=%s endpoint=%s step=%s delta_ms=%s total_ms=%s extra=%s",
            self.request_id,
            self.user_id or "",
            self.endpoint,
            step,
            delta_ms,
            total_ms,
            json.dumps({k: v for k, v in extra.items() if k not in ("html", "content")}, ensure_ascii=False)[:200],
        )
        return delta_ms

    def finish(self, **extra: Any) -> dict[str, Any]:
        total_ms = int((time.perf_counter() - self._t0) * 1000)
        summary = {
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "user_id": self.user_id,
            "total_ms": total_ms,
            "steps": self._steps,
        }
        if extra:
            summary.update(extra)
        _LOG.info(
            "content_ai_timing_summary request_id=%s endpoint=%s total_ms=%s steps=%s",
            self.request_id,
            self.endpoint,
            total_ms,
            len(self._steps),
        )
        return summary
