"""In-process worker: auto-publish Content AI schedules when due (server-side)."""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("content_ai.publish_worker")

_started = False
_lock = threading.Lock()


def _poll_seconds() -> float:
    raw = os.getenv("CONTENT_AI_PUBLISH_WORKER_SECONDS") or os.getenv(
        "CONTENT_AI_PUBLISH_SCHEDULER_SECONDS", "20"
    )
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = 20.0
    return max(10.0, min(60.0, val))


def _batch_size() -> int:
    raw = os.getenv("CONTENT_AI_PUBLISH_WORKER_BATCH") or os.getenv(
        "CONTENT_AI_PUBLISH_SCHEDULER_BATCH", "10"
    )
    try:
        return max(1, min(int(raw), 100))
    except (TypeError, ValueError):
        return 10


def _stale_seconds() -> int:
    raw = os.getenv("CONTENT_AI_PUBLISH_STALE_SECONDS", str(900))
    try:
        return max(120, int(raw))
    except (TypeError, ValueError):
        return 900


def _worker_auto_enabled() -> bool:
    flag = os.getenv("CONTENT_AI_PUBLISH_WORKER_AUTO")
    if flag is None:
        flag = os.getenv("CONTENT_AI_PUBLISH_SCHEDULER_AUTO", "1")
    return str(flag or "1").strip().lower() not in {"0", "false", "no", "off"}


def content_ai_publish_worker_loop() -> None:
    from app.db import SessionLocal
    from app.services.content_ai_publish_schedule_service import (
        arm_due_schedule_timers,
        run_publish_worker_tick,
    )

    poll = _poll_seconds()
    batch = _batch_size()
    stale = _stale_seconds()
    msg = "content_ai publish worker started poll=%.0fs batch=%s stale=%ss" % (
        poll,
        batch,
        stale,
    )
    logger.warning(msg)
    print(msg, flush=True)

    # Catch up any schedules that were due while the server was down.
    try:
        db = SessionLocal()
        try:
            armed = arm_due_schedule_timers(db, limit=100)
            logger.info("startup due schedules armed=%s", armed)
            summary = run_publish_worker_tick(db, limit=batch, stale_seconds=stale)
            logger.info(
                "startup tick processed=%s reclaimed=%s",
                summary.get("count"),
                summary.get("reclaimed"),
            )
        finally:
            db.close()
    except Exception:
        logger.exception("publish worker startup catch-up failed")

    while True:
        db = SessionLocal()
        try:
            summary = run_publish_worker_tick(db, limit=batch, stale_seconds=stale)
            reclaimed = int(summary.get("reclaimed") or 0)
            if reclaimed:
                logger.warning("reclaimed %s stale publishing row(s)", reclaimed)
            for item in summary.get("processed") or []:
                sid = item.get("id")
                if item.get("ok"):
                    logger.info(
                        "published schedule_id=%s status=%s wp_post_id=%s",
                        sid,
                        item.get("status"),
                        item.get("wp_post_id"),
                    )
                else:
                    logger.warning(
                        "publish failed schedule_id=%s status=%s retry=%s err=%s",
                        sid,
                        item.get("status"),
                        item.get("retry_count"),
                        item.get("error"),
                    )
        except Exception:
            logger.exception("publish worker tick failed")
        finally:
            db.close()
        time.sleep(poll)


def start_content_ai_publish_worker_background() -> None:
    global _started
    if not _worker_auto_enabled():
        msg = "content_ai publish worker auto-start disabled (CONTENT_AI_PUBLISH_WORKER_AUTO=0)"
        logger.warning(msg)
        print(msg, flush=True)
        return
    with _lock:
        if _started:
            return
        _started = True
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    logger.info("content_ai publish worker auto-start enabled")
    print("content_ai publish worker auto-start enabled", flush=True)
    t = threading.Thread(
        target=content_ai_publish_worker_loop,
        name="content-ai-publish-worker",
        daemon=True,
    )
    t.start()
