"""Backward-compatible aliases — prefer content_ai_publish_worker_loop."""

from __future__ import annotations

from app.services.content_ai_publish_worker_loop import (
    content_ai_publish_worker_loop as content_ai_publish_scheduler_loop,
    start_content_ai_publish_worker_background as start_content_ai_publish_scheduler_background,
)

__all__ = [
    "content_ai_publish_scheduler_loop",
    "start_content_ai_publish_scheduler_background",
]
