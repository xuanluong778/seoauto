"""Chatbot CSKH public API — rate limit, origin check, bot_id validation."""

from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from app.models.chatbot_cskh import ChatbotBot

_SESSION_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")

_lock = Lock()
_buckets: dict[str, deque[float]] = defaultdict(deque)
_last_message: dict[str, float] = {}


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


# Per IP + bot (hourly)
RATE_MSG_IP_HOUR = _int_env("CSKH_RATE_MSG_IP_HOUR", 120)
RATE_LEAD_IP_HOUR = _int_env("CSKH_RATE_LEAD_IP_HOUR", 30)
RATE_CONFIG_IP_HOUR = _int_env("CSKH_RATE_CONFIG_IP_HOUR", 60)

# Per session + bot (hourly)
RATE_MSG_SESSION_HOUR = _int_env("CSKH_RATE_MSG_SESSION_HOUR", 60)
RATE_LEAD_SESSION_HOUR = _int_env("CSKH_RATE_LEAD_SESSION_HOUR", 10)

# Min seconds between messages from same session
MIN_MESSAGE_INTERVAL_SEC = _int_env("CSKH_MIN_MESSAGE_INTERVAL_SEC", 2)

RATE_LIMIT_MESSAGE = "Bạn gửi tin nhắn quá nhanh. Vui lòng đợi vài giây rồi thử lại."
ORIGIN_DENIED_MESSAGE = "Chatbot không khả dụng trên website này."
INVALID_BOT_MESSAGE = "Chatbot không hợp lệ."


@dataclass(frozen=True)
class PublicRequestContext:
    client_ip: str
    origin: str = ""
    referer: str = ""
    user_agent: str = ""


def client_ip_from_headers(*, forwarded_for: str = "", direct_host: str = "") -> str:
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:64]
    return str(direct_host or "unknown")[:64]


def validate_bot_id(bot_id: Any) -> int | None:
    try:
        bid = int(bot_id)
    except (TypeError, ValueError):
        return None
    if bid < 1 or bid > 2_147_483_647:
        return None
    return bid


def normalize_session_id(session_id: str | None) -> str:
    s = str(session_id or "").strip()
    if _SESSION_RE.match(s):
        return s
    return ""


def _normalize_host(host: str) -> str:
    h = str(host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _host_from_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
        return _normalize_host(parsed.hostname or "")
    except Exception:
        return ""


def allowed_domains_for_bot(bot: ChatbotBot) -> list[str]:
    domains: list[str] = []
    primary = _host_from_url(bot.website_url or "")
    if primary:
        domains.append(primary)
    extra = str(getattr(bot, "allowed_domains", None) or "").strip()
    if extra:
        for part in re.split(r"[\s,;]+", extra):
            h = _normalize_host(part)
            if h and h not in domains:
                domains.append(h)
    return domains


def validate_request_origin(
    bot: ChatbotBot,
    *,
    origin: str = "",
    referer: str = "",
    page_url: str = "",
) -> tuple[bool, str]:
    """If bot has allowed domains configured, require matching Origin/Referer/page_url."""
    allowed = allowed_domains_for_bot(bot)
    if not allowed:
        return True, ""

    candidates: list[str] = []
    for raw in (origin, referer, page_url):
        h = _host_from_url(raw)
        if h:
            candidates.append(h)

    if not candidates:
        return False, ORIGIN_DENIED_MESSAGE

    for host in candidates:
        if host in allowed:
            return True, ""
        for domain in allowed:
            if host == domain or host.endswith("." + domain):
                return True, ""

    return False, ORIGIN_DENIED_MESSAGE


def _hit_bucket(key: str, *, max_calls: int, window_sec: int) -> bool:
    if max_calls <= 0:
        return True
    now = time.time()
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < now - window_sec:
            bucket.popleft()
        if len(bucket) >= max_calls:
            return False
        bucket.append(now)
    return True


def _check_min_interval(session_key: str) -> bool:
    if MIN_MESSAGE_INTERVAL_SEC <= 0 or not session_key:
        return True
    now = time.time()
    with _lock:
        last = _last_message.get(session_key, 0.0)
        if now - last < MIN_MESSAGE_INTERVAL_SEC:
            return False
        _last_message[session_key] = now
    return True


def check_public_rate_limit(
    *,
    endpoint: str,
    bot_id: int,
    ctx: PublicRequestContext,
    session_id: str | None = None,
) -> tuple[bool, str]:
    """Return (allowed, error_message)."""
    ip = (ctx.client_ip or "unknown")[:64]
    sid = normalize_session_id(session_id)
    ep = str(endpoint or "message").strip().lower()

    if ep == "message":
        if sid and not _check_min_interval(f"s:{bot_id}:{sid}"):
            return False, RATE_LIMIT_MESSAGE
        if not _hit_bucket(f"msg:ip:{bot_id}:{ip}", max_calls=RATE_MSG_IP_HOUR, window_sec=3600):
            return False, RATE_LIMIT_MESSAGE
        if sid and not _hit_bucket(f"msg:sid:{bot_id}:{sid}", max_calls=RATE_MSG_SESSION_HOUR, window_sec=3600):
            return False, RATE_LIMIT_MESSAGE
    elif ep == "lead":
        if not _hit_bucket(f"lead:ip:{bot_id}:{ip}", max_calls=RATE_LEAD_IP_HOUR, window_sec=3600):
            return False, RATE_LIMIT_MESSAGE
        if sid and not _hit_bucket(f"lead:sid:{bot_id}:{sid}", max_calls=RATE_LEAD_SESSION_HOUR, window_sec=3600):
            return False, RATE_LIMIT_MESSAGE
    elif ep == "config":
        if not _hit_bucket(f"cfg:ip:{bot_id}:{ip}", max_calls=RATE_CONFIG_IP_HOUR, window_sec=3600):
            return False, RATE_LIMIT_MESSAGE

    return True, ""


def sanitize_public_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Strip fields that must never appear on public widget API."""
    if not isinstance(data, dict):
        return {"ok": False, "message": "Lỗi hệ thống."}
    blocked_keys = frozenset({
        "content",
        "knowledge",
        "knowledge_text",
        "chunks",
        "system_prompt",
        "api_key",
        "fallback_reply",
        "usage",
        "main_services",
        "embed_code",
    })
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k in blocked_keys:
            continue
        if isinstance(v, dict):
            out[k] = sanitize_public_payload(v)
        else:
            out[k] = v
    return out
