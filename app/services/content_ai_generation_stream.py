"""Redis ordered event stream for Content AI generation (TTL, reconnect-safe)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator

_LOG = logging.getLogger(__name__)

STREAM_TTL_SEC = int(os.getenv("CONTENT_AI_GEN_STREAM_TTL_SEC", "7200"))
POLL_INTERVAL_SEC = float(os.getenv("CONTENT_AI_GEN_SSE_POLL_SEC", "0.15"))


def _redis():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
        )
    except Exception:
        return None


def _events_key(generation_id: str) -> str:
    return f"cai:gen:{generation_id}:events"


def _seq_key(generation_id: str) -> str:
    return f"cai:gen:{generation_id}:seq"


def append_event(generation_id: str, event_type: str, data: Any) -> int:
    """Append one ordered event; returns monotonic seq (1-based)."""
    r = _redis()
    gid = str(generation_id or "").strip()
    if not gid or r is None:
        return 0
    seq = int(r.incr(_seq_key(gid)) or 0)
    payload = json.dumps(
        {"seq": seq, "event": str(event_type), "data": data, "ts": time.time()},
        ensure_ascii=False,
    )
    key = _events_key(gid)
    pipe = r.pipeline()
    pipe.rpush(key, payload)
    pipe.expire(key, STREAM_TTL_SEC)
    pipe.expire(_seq_key(gid), STREAM_TTL_SEC)
    pipe.execute()
    return seq


def read_events(generation_id: str, *, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    r = _redis()
    gid = str(generation_id or "").strip()
    if not gid or r is None:
        return []
    try:
        raw = r.lrange(_events_key(gid), 0, -1) or []
    except Exception as exc:
        _LOG.debug("read_events failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for line in raw:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        seq = int(row.get("seq") or 0)
        if seq <= int(after_seq):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def max_seq(generation_id: str) -> int:
    r = _redis()
    gid = str(generation_id or "").strip()
    if not gid or r is None:
        return 0
    try:
        return int(r.get(_seq_key(gid)) or 0)
    except Exception:
        return 0


def clear_stream(generation_id: str) -> None:
    r = _redis()
    gid = str(generation_id or "").strip()
    if not gid or r is None:
        return
    try:
        r.delete(_events_key(gid), _seq_key(gid))
    except Exception:
        pass


def iter_events_until_terminal(
    generation_id: str,
    *,
    after_seq: int = 0,
    is_terminal: Any,
    timeout_sec: float = 3600.0,
) -> Iterator[dict[str, Any]]:
    """Poll Redis for new events until terminal state or timeout."""
    seen = int(after_seq)
    deadline = time.time() + max(30.0, float(timeout_sec))
    while time.time() < deadline:
        if is_terminal():
            break
        rows = read_events(generation_id, after_seq=seen)
        for row in rows:
            seq = int(row.get("seq") or 0)
            if seq > seen:
                seen = seq
                yield row
            if str(row.get("event") or "") in ("done", "error"):
                return
        if is_terminal():
            break
        time.sleep(POLL_INTERVAL_SEC)
