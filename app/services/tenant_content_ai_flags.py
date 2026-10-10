"""Feature flags: Content AI projects JSON → PostgreSQL."""

from __future__ import annotations

import os


def _truthy(name: str, default: str = "") -> bool:
    raw = os.getenv(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def content_ai_pg_enabled() -> bool:
    """PostgreSQL is primary for Content AI projects (default on after Prompt 9)."""
    return _truthy("TENANT_CONTENT_AI_PG", "1")


def content_ai_dual_read() -> bool:
    """JSON fallback on PG miss/error (temporary dual-read). Default on."""
    return _truthy("TENANT_CONTENT_AI_DUAL_READ", "1")


def content_ai_json_write() -> bool:
    """JSON writes after cutover. Default off — PostgreSQL is sole write authority."""
    return _truthy("TENANT_CONTENT_AI_JSON_WRITE", "0")
