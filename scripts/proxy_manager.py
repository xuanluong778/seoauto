"""
HTTP(S) proxies with Redis-backed health, per-domain block memory, and selection by score.

Env:
  PROXY_LIST / PROXY_URLS — comma-separated proxy URLs
  PROXY_BAD_TTL_SECONDS — TTL on global bad set
  PROXY_DOMAIN_BLOCK_TTL — TTL for (domain, proxy) soft block after block outcome
"""

from __future__ import annotations

import hashlib
import os
import random
import time
from typing import Any, Literal

_BAD_KEY = "crawl:bad_proxies"
_BAD_TTL = int(os.getenv("PROXY_BAD_TTL_SECONDS", "86400"))
_DOMAIN_BLOCK_TTL = int(os.getenv("PROXY_DOMAIN_BLOCK_TTL", "2100"))
_STAT_TTL = int(os.getenv("PROXY_STAT_TTL_SECONDS", "1209600"))  # 14d


def _redis_client():
    try:
        import redis

        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        return redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def _proxy_list_from_env() -> list[str]:
    raw = (os.getenv("PROXY_LIST") or os.getenv("PROXY_URLS") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _server_fingerprint(server: str) -> str:
    return hashlib.sha256(server.strip().encode()).hexdigest()[:20]


def _domain_block_key(domain: str, server: str) -> str:
    dh = hashlib.sha256(domain.lower().encode()).hexdigest()[:24]
    ph = _server_fingerprint(server)
    return f"crawl:proxy_domain_block:{dh}:{ph}"


def _stat_key(server: str) -> str:
    return f"crawl:proxy_stat:{_server_fingerprint(server)}"


def mark_proxy_domain_blocked(domain: str, server: str | None) -> None:
    if not server or not domain:
        return
    r = _redis_client()
    if not r:
        return
    try:
        r.setex(_domain_block_key(domain, server), max(60, _DOMAIN_BLOCK_TTL), str(int(time.time())))
    except Exception:
        pass


def is_proxy_blocked_for_domain(domain: str, server: str) -> bool:
    r = _redis_client()
    if not r:
        return False
    try:
        return bool(r.exists(_domain_block_key(domain, server)))
    except Exception:
        return False


def mark_proxy_bad(server: str | None) -> None:
    if not server:
        return
    r = _redis_client()
    if not r:
        return
    try:
        r.sadd(_BAD_KEY, server)
        if _BAD_TTL > 0:
            r.expire(_BAD_KEY, _BAD_TTL)
    except Exception:
        pass


def record_proxy_crawl_feedback(
    proxy_server: str | None,
    domain: str,
    *,
    outcome: Literal["success", "blocked", "timeout", "partial"],
    response_time_ms: float,
) -> None:
    """Update rolling success/block/time stats for ``get_best_proxy``."""
    if not proxy_server:
        return
    r = _redis_client()
    if not r:
        return
    sk = _stat_key(proxy_server)
    try:
        pipe = r.pipeline()
        if outcome == "success":
            pipe.hincrby(sk, "success", 1)
        elif outcome == "blocked":
            pipe.hincrby(sk, "block", 1)
        elif outcome in ("timeout", "partial"):
            pipe.hincrby(sk, "soft_fail", 1)
        pipe.hincrbyfloat(sk, "time_sum_ms", max(0.0, float(response_time_ms)))
        pipe.hincrby(sk, "n", 1)
        pipe.execute()
        if _STAT_TTL > 0:
            r.expire(sk, _STAT_TTL)
    except Exception:
        pass


def proxy_reliability_score(proxy_server: str | None) -> float:
    """0–1 for confidence blending (no proxy → neutral)."""
    if not proxy_server:
        return 0.66
    r = _redis_client()
    if not r:
        return 0.66
    try:
        h = r.hgetall(_stat_key(proxy_server))
        if not h:
            return 0.66
        s = float(h.get("success") or 0)
        b = float(h.get("block") or 0)
        sf = float(h.get("soft_fail") or 0)
        n = s + b + sf
        if n <= 0:
            return 0.66
        success_rate = s / n
        block_rate = b / max(1.0, n)
        # Decay implicit: older samples diluted as n grows with steady success
        score = success_rate * (1.0 - 0.55 * block_rate) * (1.0 - 0.12 * min(1.0, sf / max(1.0, n)))
        return max(0.08, min(0.99, round(score, 4)))
    except Exception:
        return 0.66


def _proxy_selection_score(server: str, domain: str | None) -> float:
    r = _redis_client()
    pr = proxy_reliability_score(server)
    if not r:
        return pr + random.uniform(0, 0.02)  # noqa: S311
    try:
        h = r.hgetall(_stat_key(server))
        tsum = float(h.get("time_sum_ms") or 0)
        n = float(h.get("n") or 0)
        avg = tsum / max(1.0, n)
        # Prefer lower latency slightly
        latency_bonus = max(0.0, min(0.12, (8000.0 - avg) / 8000.0 * 0.12))
        penalty = 0.0
        if domain and is_proxy_blocked_for_domain(domain, server):
            penalty = 0.95
        return pr + latency_bonus - penalty + random.uniform(0, 0.015)  # noqa: S311
    except Exception:
        return pr


def _parse_proxy_entry(server: str) -> dict[str, Any]:
    if "@" in server and "://" in server:
        scheme, rest = server.split("://", 1)
        auth, hostport = rest.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
            return {"server": f"{scheme}://{hostport}", "username": user, "password": pwd}
    return {"server": server}


def get_best_proxy(domain: str | None = None) -> dict[str, Any] | None:
    """
    Pick proxy with best historical score for this registrable host.
    Avoids proxies recently blocked on the same domain (TTL decay).
    """
    servers = _proxy_list_from_env()
    if not servers:
        return None

    r = _redis_client()
    candidates: list[str] = []
    for s in servers:
        if r and r.sismember(_BAD_KEY, s):
            continue
        if domain and is_proxy_blocked_for_domain(domain, s):
            continue
        candidates.append(s)
    pool = candidates or [s for s in servers if not (r and r.sismember(_BAD_KEY, s))] or servers

    scored = [( _proxy_selection_score(s, domain), s) for s in pool]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, best = scored[0]
    # Small exploration: sometimes pick 2nd best
    if len(scored) > 1 and random.random() < float(os.getenv("PROXY_EXPLORE_RATE", "0.08")):  # noqa: S311
        _, best = scored[1]
    _ = top_score
    return _parse_proxy_entry(best)


def get_proxy(domain: str | None = None) -> dict[str, Any] | None:
    """Backward-compatible alias for :func:`get_best_proxy`."""
    return get_best_proxy(domain)


def proxy_fingerprint(proxy: dict[str, Any] | None) -> str | None:
    if not proxy:
        return None
    raw = proxy.get("server", "") + "|" + proxy.get("username", "")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
