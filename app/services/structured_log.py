"""Structured request logs with secret/PII redaction (WAVE 9)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

_LOG = logging.getLogger("seoauto.request")

_REDACT_KEYS = frozenset(
    {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "api_key",
        "authorization",
        "cookie",
        "jwt",
        "credit_card",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]+", re.I),
    re.compile(r"sk-[A-Za-z0-9]{16,}", re.I),
    re.compile(r"JWT_SECRET\s*=\s*\S+", re.I),
)


def redact_string(value: str) -> str:
    out = str(value or "")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for k, v in data.items():
        lk = str(k).lower()
        if lk in _REDACT_KEYS or "password" in lk or "secret" in lk or "token" in lk:
            safe[k] = "[REDACTED]"
        elif isinstance(v, dict):
            safe[k] = redact_dict(v)
        elif isinstance(v, str):
            safe[k] = redact_string(v)[:500]
        else:
            safe[k] = v
    return safe


def log_request_event(**fields: Any) -> None:
    """JSON line — tenant-safe: user_id/org_id only, no email/token."""
    payload = redact_dict({k: v for k, v in fields.items() if v is not None})
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        line = json.dumps({"event": "request", "error": "serialize_failed"})
    _LOG.info(line)
