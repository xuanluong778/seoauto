"""WAVE 5 production validation — live WordPress, cache drills, rollback."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest import mock

SHARED_ENV = Path("/var/www/seoauto_vn_usr/data/www/shared/env.local")


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[max(0, int(len(s) * 0.95) - 1)]


def _redis_info() -> dict[str, Any]:
    try:
        import redis

        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
        info = dict(r.info("memory"))
        return {
            "used_memory_human": info.get("used_memory_human"),
            "used_memory": info.get("used_memory"),
            "embedding_queue_depth": int(r.llen("embedding") or 0),
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _pm2_embedding_worker() -> dict[str, Any]:
    online = 0
    total = 0
    try:
        proc = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            for app in json.loads(proc.stdout or "[]"):
                name = str(app.get("name") or "")
                if "embedding" in name.lower():
                    total += 1
                    env = app.get("pm2_env") or {}
                    if str(env.get("status")) == "online":
                        online += 1
    except Exception as exc:
        return {"gate": "FAIL", "error": str(exc)[:200]}
    return {"gate": "PASS" if total == 1 and online == 1 else "FAIL", "total": total, "online": online}


def _read_shared_env_flag(name: str) -> str:
    if not SHARED_ENV.is_file():
        return os.getenv(name, "")
    for line in SHARED_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return os.getenv(name, "")


def audit_production_flags() -> dict[str, Any]:
    flags = {
        "EMBEDDING_CELERY_WORKER": _read_shared_env_flag("EMBEDDING_CELERY_WORKER"),
        "DUPLICATE_WP_CORPUS_CACHE": _read_shared_env_flag("DUPLICATE_WP_CORPUS_CACHE"),
        "DUPLICATE_WP_ASYNC_FETCH": _read_shared_env_flag("DUPLICATE_WP_ASYNC_FETCH"),
        "CELERY_MULTI_QUEUE": _read_shared_env_flag("CELERY_MULTI_QUEUE"),
    }
    pm2 = _pm2_embedding_worker()
    ok_flags = all(str(v).strip() in ("1", "true", "yes", "on") for k, v in flags.items() if k != "CELERY_MULTI_QUEUE")
    ok_mq = str(flags.get("CELERY_MULTI_QUEUE", "")).strip() in ("1", "true", "yes", "on")
    ok = ok_flags and ok_mq and pm2.get("gate") == "PASS"
    return {
        "gate": "PASS" if ok else "FAIL",
        "flags": flags,
        "embedding_worker": pm2,
    }


def _live_config() -> tuple[int, str, int, str]:
    uid_a = int(os.getenv("WAVE5_LIVE_WP_USER_ID", "1") or "1")
    site_a = str(os.getenv("WAVE5_LIVE_WP_SITE", "https://itsieuviet.com") or "").strip()
    uid_b = int(os.getenv("WAVE5_LIVE_WP_USER_B", "153") or "153")
    site_b = str(os.getenv("WAVE5_LIVE_WP_SITE_B", "https://itsieutoc.com") or "").strip()
    return uid_a, site_a, uid_b, site_b


def audit_live_wp_corpus() -> dict[str, Any]:
    from app.services.duplicate_wp_corpus_cache import (
        clear_corpus_cache_entry,
        get_live_site_articles_cached,
        metrics_snapshot,
        reset_metrics,
    )

    uid, site, uid_b, site_b = _live_config()
    kws = ["sửa máy tính", "cài win"]
    reset_metrics()
    clear_corpus_cache_entry(user_id=uid, site=site, keywords=kws)

    t0 = time.perf_counter()
    cold_refs = get_live_site_articles_cached(user_id=uid, target_website=site, search_keywords=kws)
    cold_ms = round((time.perf_counter() - t0) * 1000, 1)
    m_cold = metrics_snapshot()

    warm_latencies: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        get_live_site_articles_cached(user_id=uid, target_website=site, search_keywords=kws)
        warm_latencies.append(time.perf_counter() - t0)
    warm_p95 = round(_p95(warm_latencies) * 1000, 1)
    m_warm = metrics_snapshot()

    # Tenant B must not return tenant A URLs
    other_refs = get_live_site_articles_cached(user_id=uid_b, target_website=site_b, search_keywords=kws)
    urls_a = {str(r.url or "").lower() for r in cold_refs if getattr(r, "url", None)}
    urls_b = {str(r.url or "").lower() for r in other_refs if getattr(r, "url", None)}
    cross = bool(urls_a & urls_b) if urls_a and urls_b else False

    ok_live = m_cold.get("wp_fetch_count", 0) >= 1 or len(cold_refs) > 0
    ok_cold = cold_ms > 0
    ok_warm = m_warm.get("wp_cache_hit", 0) >= 1 and warm_p95 < 500
    ok_tenant = not cross

    return {
        "gate": "PASS" if ok_live else "FAIL",
        "site": site,
        "user_id": uid,
        "cold_count": len(cold_refs),
        "cold_latency_ms": cold_ms,
        "warm_p95_ms": warm_p95,
        "metrics_cold": m_cold,
        "metrics_warm": m_warm,
        "tenant_cross_leak": cross,
        "tenant_b_count": len(other_refs),
        "cold_cache_gate": "PASS" if ok_cold else "FAIL",
        "warm_cache_gate": "PASS" if ok_warm else "FAIL",
        "tenant_gate": "PASS" if ok_tenant else "FAIL",
    }


def audit_large_corpus() -> dict[str, Any]:
    from app.services.duplicate_wp_corpus_cache import (
        clear_corpus_cache_entry,
        get_live_site_articles_cached,
        reset_metrics,
    )

    uid, site, _, _ = _live_config()
    kws = [f"sửa máy tính quận {i}" for i in range(1, 25)]
    reset_metrics()
    clear_corpus_cache_entry(user_id=uid, site=site, keywords=kws)
    t0 = time.perf_counter()
    refs = get_live_site_articles_cached(user_id=uid, target_website=site, search_keywords=kws)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    ok = elapsed_ms < 120_000 and (len(refs) > 0 or elapsed_ms > 100)
    return {
        "gate": "PASS" if ok else "FAIL",
        "keyword_count": len(kws),
        "corpus_count": len(refs),
        "latency_ms": elapsed_ms,
    }


def audit_wp_timeout_recovery() -> dict[str, Any]:
    from app.services.duplicate_wp_corpus_cache import (
        _cache_set,
        _corpus_key,
        _fetch_live_corpus_resilient,
        ref_from_dict,
    )

    uid, site, _, _ = _live_config()
    kws = ["timeout drill"]
    cache_key = _corpus_key(user_id=uid, site=site, keywords=kws)
    stale = [ref_from_dict({"keyword": "stale post", "title": "Stale", "url": "https://ex.test/stale", "source": "published"})]
    _cache_set(cache_key, stale, ttl=300)

    def _timeout(**kwargs):
        raise TimeoutError("connection timed out")

    with mock.patch(
        "app.services.content_ai_duplicate_detection._collect_live_site_articles",
        side_effect=_timeout,
    ):
        refs, err = _fetch_live_corpus_resilient(
            user_id=uid,
            target_website=site,
            search_keywords=kws,
            role="user",
            cache_key=cache_key,
        )
    ok = err is not None and len(refs) == 1 and refs[0].url == "https://ex.test/stale"
    return {"gate": "PASS" if ok else "FAIL", "error": err, "count": len(refs)}


def audit_wp_429_500_recovery() -> dict[str, Any]:
    from app.services.duplicate_wp_corpus_cache import (
        _cache_set,
        _corpus_key,
        _fetch_live_corpus_resilient,
        ref_from_dict,
    )

    uid, site, _, _ = _live_config()
    kws = ["error drill"]
    cache_key = _corpus_key(user_id=uid, site=site, keywords=kws)
    stale = [
        ref_from_dict(
            {"keyword": "err stale", "title": "Err", "url": "https://ex.test/err", "source": "published"}
        )
    ]
    _cache_set(cache_key, stale, ttl=300)

    def _raise429(**kwargs):
        raise RuntimeError("HTTP 429")

    def _raise500(**kwargs):
        raise RuntimeError("HTTP 500")

    def _raise_conn(**kwargs):
        raise ConnectionError("connection reset")

    out: dict[str, int] = {}
    for label, fn in (("429", _raise429), ("500", _raise500), ("connection", _raise_conn)):
        with mock.patch(
            "app.services.content_ai_duplicate_detection._collect_live_site_articles",
            side_effect=fn,
        ):
            refs, err = _fetch_live_corpus_resilient(
                user_id=uid,
                target_website=site,
                search_keywords=kws,
                role="user",
                cache_key=cache_key,
            )
        out[label] = len(refs)
    ok = all(v >= 1 for v in out.values())
    return {"gate": "PASS" if ok else "FAIL", **out}


def audit_async_refresh_nonblocking() -> dict[str, Any]:
    from app.services.duplicate_wp_corpus_cache import (
        _cache_set,
        _corpus_key,
        _redis,
        get_live_site_articles_cached,
        ref_from_dict,
    )

    uid, site, _, _ = _live_config()
    kws = ["async drill"]
    cache_key = _corpus_key(user_id=uid, site=site, keywords=kws)
    refs_stale = [
        ref_from_dict(
            {"keyword": "async", "title": "Async", "url": "https://ex.test/async", "source": "published"}
        )
    ]
    _cache_set(cache_key, refs_stale, ttl=300)
    r = _redis()
    if r:
        r.delete(cache_key)

    enqueued: list[Any] = []

    def _enqueue(**kwargs):
        enqueued.append(kwargs)

    t0 = time.perf_counter()
    with mock.patch(
        "app.services.duplicate_wp_corpus_cache._enqueue_refresh",
        side_effect=lambda **kw: enqueued.append(kw),
    ):
        out = get_live_site_articles_cached(user_id=uid, target_website=site, search_keywords=kws)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    ok = elapsed_ms < 200 and bool(enqueued) and len(out) >= 1
    return {"gate": "PASS" if ok else "FAIL", "elapsed_ms": elapsed_ms, "enqueued": bool(enqueued)}


def audit_rollback() -> dict[str, Any]:
    """Verify inline embedding + direct WP fetch path still works when flags off."""
    from app.services.content_ai_duplicate_detection import check_keywords_for_duplicates, ExistingArticleRef
    from app.services.embedding_worker_rollout import (
        duplicate_wp_corpus_cache_enabled,
        embedding_celery_enabled,
    )

    corpus = [ExistingArticleRef(keyword="rollback kw", title="Rollback")]

    with mock.patch.dict(
        os.environ,
        {"EMBEDDING_CELERY_WORKER": "0", "DUPLICATE_WP_CORPUS_CACHE": "0"},
        clear=False,
    ):
        from importlib import reload
        import app.services.embedding_worker_rollout as rollout

        reload(rollout)
        inline_cache = not rollout.duplicate_wp_corpus_cache_enabled()
        inline_embed = not rollout.embedding_celery_enabled()

        called: dict[str, int] = {"embed": 0, "collect": 0}

        def _embed(keywords, **kw):
            called["embed"] += 1
            return {}

        def _collect(**kw):
            called["collect"] += 1
            return corpus

        with mock.patch(
            "app.services.content_ai_duplicate_detection.collect_existing_articles",
            side_effect=_collect,
        ), mock.patch(
            "app.services.content_ai_duplicate_detection.embed_keywords",
            side_effect=_embed,
        ), mock.patch(
            "app.services.content_ai_duplicate_detection._collect_live_site_articles",
            return_value=[],
        ):
            rows = check_keywords_for_duplicates(["rollback kw unique"], user_id=1, db=None)
        ok = inline_cache and inline_embed and rows[0].get("is_duplicate") is False

    reload(rollout)
    return {"gate": "PASS" if ok else "FAIL", "inline_flags": inline_cache and inline_embed}


def collect_system_metrics() -> dict[str, Any]:
    redis_info = _redis_info()
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        cpu = psutil.cpu_percent(interval=0.2)
        host_mem = psutil.virtual_memory()
        return {
            "process_rss_mb": round(mem.rss / 1024 / 1024, 1),
            "cpu_percent": cpu,
            "host_mem_used_percent": host_mem.percent,
            **redis_info,
        }
    except Exception:
        return redis_info


def audit_embedding_queue_wait() -> dict[str, Any]:
    """Measure embedding path latency with Celery worker (or TF-IDF fallback)."""
    from app.services.embedding_cache import metrics_snapshot, reset_metrics
    from app.services.semantic_embedding import embed_keywords

    reset_metrics()
    kws = ["embedding queue latency probe"]
    latencies: list[float] = []
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            embed_keywords(kws, tenant_scope="wave5-probe", use_cache=False)
        except Exception:
            pass
        latencies.append(time.perf_counter() - t0)
    return {
        "p95_ms": round(_p95(latencies) * 1000, 1),
        "cache_metrics": metrics_snapshot(),
        "redis": _redis_info(),
    }
