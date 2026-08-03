"""Security audit trail (login, secrets, publish, projects, knowledge base)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from app.db import SessionLocal
from app.models.security_audit_log import SecurityAuditLog


def _client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client:
        return str(request.client.host or "")[:64]
    return ""


def log_audit_event(
    *,
    action: str,
    user_id: int | None = None,
    resource_type: str = "",
    resource_id: str = "",
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    try:
        detail_json = json.dumps(detail or {}, ensure_ascii=False)[:8000]
    except (TypeError, ValueError):
        detail_json = "{}"
    row = SecurityAuditLog(
        user_id=int(user_id) if user_id else None,
        action=str(action or "")[:64],
        resource_type=str(resource_type or "")[:64],
        resource_id=str(resource_id or "")[:128],
        detail_json=detail_json,
        ip_address=_client_ip(request),
    )
    db = SessionLocal()
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
