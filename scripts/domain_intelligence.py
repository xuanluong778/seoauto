"""
Per-domain crawl learning (Redis): profiles, timing, blocks, JS level.

Cold domains get conservative defaults; outcomes update rolling stats.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from urllib.parse import urlparse

_KEY_PREFIX = "crawl:domain_intel:"
_TTL = int(os.getenv("DOMAIN_INTEL_TTL_SECONDS", "2592000"))  # 30d


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)
    except Exception:
        return None


def _norm_domain(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if "://" in s:
        try:
            s = urlparse(s).hostname or s
        except Exception:
            pass
    if s.startswith("www."):
        s = s[4:]
    return s or "unknown"


def _key(domain: str) -> str:
    d = _norm_domain(domain)
    return _KEY_PREFIX + hashlib.sha256(d.encode()).hexdigest()[:40]


def get_best_crawl_strategy(domain: str) -> dict[str, Any]:
    """
    Returns strategy for Playwright worker / crawler.

    ``timeout_strategy`` uses multipliers applied in ``playwright_crawler``.
    ``proxy_type`` hints proxy selection (tags not enforced unless provider maps them).
    """
    r = _redis()
    base = {
        "preferred_profile": "mobile",
        "timeout_strategy": {"initial_scale": 1.0, "label": "normal", "max_scale": 2.5},
        "proxy_type": os.getenv("CRAWL_DEFAULT_PROXY_TYPE", "any"),
        "interaction_delay_scale": 1.0,
    }
    if not r:
        return base
    try:
        h = r.hgetall(_key(domain))
        if not h:
            return base
        prof = (h.get("preferred_profile") or "mobile").strip()
        if prof not in ("mobile", "desktop", "desktop_nojs"):
            prof = "mobile"
        avg_load = float(h.get("avg_load_sec") or 0.0)
        block_n = float(h.get("block_count") or 0)
        ok_n = float(h.get("success_count") or 0)
        tlabel = "normal"
        initial = 1.0
        if avg_load > 18:
            initial, tlabel = 1.25, "patient"
        elif avg_load > 10:
            initial, tlabel = 1.12, "cautious"
        if block_n > 0 and ok_n + block_n > 0 and block_n / (ok_n + block_n) > 0.35:
            initial = min(2.2, initial * 1.2)
            tlabel = "patient"
        js_avg = float(h.get("js_dep_avg") or 0.0)
        interaction = 1.0 + min(0.9, js_avg) * 0.25
        return {
            "preferred_profile": prof,
            "timeout_strategy": {"initial_scale": round(initial, 3), "label": tlabel, "max_scale": 2.6},
            "proxy_type": (h.get("proxy_type") or base["proxy_type"]),
            "interaction_delay_scale": round(interaction, 3),
        }
    except Exception:
        return base


def rotate_profile_preference(pref: str) -> str:
    order = ["mobile", "desktop", "desktop_nojs"]
    p = (pref or "mobile").strip().lower()
    if p not in order:
        p = "mobile"
    return order[(order.index(p) + 1) % len(order)]


def domain_reliability_score(domain: str) -> float:
    """0–1 prior for confidence blending (cold domain → neutral 0.62)."""
    r = _redis()
    if not r:
        return 0.62
    try:
        h = r.hgetall(_key(domain))
        if not h:
            return 0.62
        ok_n = float(h.get("success_count") or 0)
        bl = float(h.get("block_count") or 0)
        tot = ok_n + bl
        if tot <= 0:
            return 0.62
        p_ok = ok_n / tot
        return max(0.15, min(0.98, 0.35 + 0.65 * p_ok))
    except Exception:
        return 0.62


def record_domain_crawl_outcome(
    domain: str,
    page_record: dict[str, Any],
    *,
    latency_seconds: float | None = None,
) -> None:
    """Feedback after a page crawl (worker or sync path)."""
    r = _redis()
    if not r:
        return
    key = _key(domain)
    try:
        st = str(page_record.get("crawl_status") or "").lower()
        prof = str(page_record.get("profile_used") or "desktop")
        js_dep = 1.0 if page_record.get("js_dependency") is True else 0.0
        pipe = r.pipeline()
        if st == "blocked":
            pipe.hincrby(key, "block_count", 1)
        elif st in ("success", "") or page_record.get("status") == 200:
            pipe.hincrby(key, "success_count", 1)
            pipe.hincrby(key, f"prof_ok:{prof}", 1)
        if latency_seconds is not None and latency_seconds > 0:
            pipe.hincrbyfloat(key, "load_sum", float(latency_seconds))
            pipe.hincrby(key, "load_n", 1)
        pipe.hincrbyfloat(key, "js_dep_sum", js_dep)
        pipe.hincrby(key, "js_dep_n", 1)
        pipe.execute()

        # Re-read for EWMA-style aggregates (simple)
        h = r.hgetall(key)
        ok = float(h.get("success_count") or 0)
        blk = float(h.get("block_count") or 0)
        # Preferred profile = most successful profile counts
        best_p, best_c = "mobile", -1.0
        for cand in ("mobile", "desktop", "desktop_nojs"):
            c = float(h.get(f"prof_ok:{cand}") or 0)
            if c > best_c:
                best_c, best_p = c, cand
        if best_c > 0:
            r.hset(key, "preferred_profile", best_p)
        load_n = float(h.get("load_n") or 0)
        if load_n > 0:
            r.hset(key, "avg_load_sec", float(h.get("load_sum") or 0) / load_n)
        jn = float(h.get("js_dep_n") or 0)
        if jn > 0:
            r.hset(key, "js_dep_avg", float(h.get("js_dep_sum") or 0) / jn)
        if _TTL > 0:
            r.expire(key, _TTL)
    except Exception:
        pass
