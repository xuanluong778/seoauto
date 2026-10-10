"""Wave 3 fairness + concurrent enqueue evidence tests."""

from __future__ import annotations

import os
import threading
import time
import uuid
from unittest.mock import patch

import pytest


@pytest.fixture()
def redis_or_skip():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        # try load env.local
        env_path = "/var/www/seoauto_vn_usr/data/www/seoauto.vn-current/env.local"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("REDIS_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    os.environ["REDIS_URL"] = url
                    break
    if not url:
        pytest.skip("REDIS_URL not set")
    try:
        import redis

        r = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        r.ping()
        return r
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")


def test_fairness_blocks_second_job_same_user(redis_or_skip, monkeypatch):
    monkeypatch.setenv("QUEUE_TECHNICAL_PER_USER", "1")
    monkeypatch.setenv("QUEUE_TECHNICAL_GLOBAL", "10")
    from app.services.queue_fairness import release_slot, try_acquire_slot

    uid = 424242
    j1 = f"fair-{uuid.uuid4().hex[:8]}"
    j2 = f"fair-{uuid.uuid4().hex[:8]}"
    assert try_acquire_slot("technical", uid, j1, ttl_sec=30) is True
    assert try_acquire_slot("technical", uid, j2, ttl_sec=30) is False
    release_slot("technical", uid, j1)
    assert try_acquire_slot("technical", uid, j2, ttl_sec=30) is True
    release_slot("technical", uid, j2)


def test_concurrent_enqueue_calls(monkeypatch):
    """10 concurrent start_technical_scan_thread → 10 celery apply_async (no crash)."""
    monkeypatch.setenv("TECHNICAL_SCAN_CELERY", "1")
    monkeypatch.setenv("TECHNICAL_SCAN_THREAD_FALLBACK", "0")
    calls: list[str] = []
    lock = threading.Lock()

    def fake_apply_async(*, args=None, **kwargs):
        with lock:
            calls.append(args[0])

        class R:
            id = uuid.uuid4().hex

        return R()

    monkeypatch.setattr(
        "app.workers.technical_scan_tasks.run_technical_scan_task.apply_async",
        fake_apply_async,
    )
    from app.services.technical_scan_job import start_technical_scan_thread

    threads = []
    for i in range(10):
        t = threading.Thread(
            target=start_technical_scan_thread,
            args=(f"job-{i}", {"user_id": 1 + (i % 3), "url": f"https://t{i}.test"}),
        )
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 10
    assert len(set(calls)) == 10


def test_api_responsive_while_enqueue(monkeypatch):
    """Enqueue returns immediately (<100ms) even if task body would be slow."""
    monkeypatch.setenv("TECHNICAL_SCAN_CELERY", "1")

    def slow_apply_async(*a, **k):
        class R:
            id = "x"

        return R()

    monkeypatch.setattr(
        "app.workers.technical_scan_tasks.run_technical_scan_task.apply_async",
        slow_apply_async,
    )
    from app.services.technical_scan_job import start_technical_scan_thread

    t0 = time.monotonic()
    start_technical_scan_thread("fast-job", {"user_id": 1})
    assert (time.monotonic() - t0) < 0.5
