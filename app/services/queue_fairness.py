"""Per-user / global concurrency caps for Celery heavy jobs (Redis NX counters)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

_LOG = logging.getLogger(__name__)


def _redis():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
        )
    except Exception:
        return None


def _limits(kind: str) -> tuple[int, int]:
    """Return (per_user_max, global_max)."""
    if kind == "technical":
        per = int(os.getenv("QUEUE_TECHNICAL_PER_USER", "1"))
        glob = int(os.getenv("QUEUE_TECHNICAL_GLOBAL", "2"))
    elif kind == "generation":
        per = int(os.getenv("QUEUE_GENERATION_PER_USER", "2"))
        glob = int(os.getenv("QUEUE_GENERATION_GLOBAL", "20"))
    else:
        per = int(os.getenv("QUEUE_BULK_PER_USER", "1"))
        glob = int(os.getenv("QUEUE_BULK_GLOBAL", "1"))
    return max(1, per), max(1, glob)


def _user_key(kind: str, user_id: int, organization_id: int | None = None) -> str:
    uid = int(user_id)
    if kind == "generation" and organization_id is not None:
        return f"queue:slots:{kind}:org:{int(organization_id)}:user:{uid}"
    return f"queue:slots:{kind}:user:{uid}"


def try_acquire_slot(
    kind: str,
    user_id: int,
    job_id: str,
    *,
    org_id: int | None = None,
    ttl_sec: int = 900,
) -> bool:
    """
    Acquire a fairness slot. Returns False if user or global cap exceeded.
    Slots auto-expire (TTL) so crashed workers release capacity.
    """
    r = _redis()
    if r is None:
        return True  # best-effort when Redis down (Celery broker may still work)
    per_user, global_max = _limits(kind)
    uid = int(user_id)
    jid = str(job_id)
    user_key = _user_key(kind, uid, org_id)
    global_key = f"queue:slots:{kind}:global"
    member = jid
    ttl = max(120, min(int(ttl_sec), 7200))
    now = time.time()
    expire_at = now + ttl
    lua = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
    redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
    local uc = redis.call('ZCARD', KEYS[1])
    local gc = redis.call('ZCARD', KEYS[2])
    if tonumber(uc) >= tonumber(ARGV[2]) or tonumber(gc) >= tonumber(ARGV[3]) then
      return 0
    end
    redis.call('ZADD', KEYS[1], ARGV[4], ARGV[5])
    redis.call('ZADD', KEYS[2], ARGV[4], ARGV[5])
    redis.call('EXPIRE', KEYS[1], ARGV[6])
    redis.call('EXPIRE', KEYS[2], ARGV[6])
    return 1
    """
    try:
        ok = r.eval(
            lua,
            2,
            user_key,
            global_key,
            str(now),
            str(per_user),
            str(global_max),
            str(expire_at),
            member,
            str(ttl + 60),
        )
        return bool(int(ok or 0))
    except Exception as exc:
        _LOG.warning("queue_fairness_acquire_failed kind=%s err=%s", kind, exc)
        return True


def release_slot(kind: str, user_id: int, job_id: str, *, org_id: int | None = None) -> None:
    r = _redis()
    if r is None:
        return
    try:
        uid = int(user_id)
        jid = str(job_id)
        r.zrem(_user_key(kind, uid, org_id), jid)
        r.zrem(f"queue:slots:{kind}:global", jid)
    except Exception as exc:
        _LOG.debug("queue_fairness_release_failed: %s", exc)


def slot_stats(kind: str, user_id: int | None = None) -> dict[str, Any]:
    r = _redis()
    per_user, global_max = _limits(kind)
    if r is None:
        return {"redis": False, "per_user_max": per_user, "global_max": global_max}
    try:
        now = time.time()
        gkey = f"queue:slots:{kind}:global"
        r.zremrangebyscore(gkey, 0, now)
        out: dict[str, Any] = {
            "redis": True,
            "global_active": int(r.zcard(gkey) or 0),
            "global_max": global_max,
            "per_user_max": per_user,
        }
        if user_id is not None:
            ukey = f"queue:slots:{kind}:user:{int(user_id)}"
            r.zremrangebyscore(ukey, 0, now)
            out["user_active"] = int(r.zcard(ukey) or 0)
        return out
    except Exception as e:
        return {"redis": False, "error": type(e).__name__}
