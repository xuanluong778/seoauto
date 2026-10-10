"""WAVE 5 — dedicated embedding + WP corpus sync Celery tasks."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from app.queue.celery_app import celery_app
from app.services.duplicate_wp_corpus_cache import sync_wp_corpus_incremental

log = logging.getLogger(__name__)

_MODEL_LOAD_COUNT = 0


def model_load_count() -> int:
    return int(_MODEL_LOAD_COUNT)


def _job_result_key(job_id: str) -> str:
    return f"emb:job:result:{job_id}"


def _redis():
    try:
        import redis

        return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    except Exception:
        return None


def _embedding_job_id(keywords: list[str], tenant_scope: str) -> str:
    raw = f"{tenant_scope}|{'|'.join(sorted(k.strip().lower() for k in keywords if k.strip()))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _serialize_embeddings(emb: dict[str, Any]) -> bytes:
    payload = {k: v.tolist() for k, v in emb.items()}
    return json.dumps(payload).encode("utf-8")


def _deserialize_embeddings(raw: bytes) -> dict[str, Any]:
    import numpy as np

    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        return {}
    return {k: np.asarray(v, dtype=np.float32) for k, v in data.items()}


@celery_app.task(
    name="embedding.embed_keywords",
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def embed_keywords_task(
    self,
    keywords: list[str],
    tenant_scope: str = "global",
    job_id: str = "",
) -> dict[str, Any]:
    """Compute embeddings in dedicated worker; idempotent via job_id + result cache."""
    global _MODEL_LOAD_COUNT
    from app.services.semantic_embedding import embed_keywords_local

    jid = str(job_id or _embedding_job_id(keywords, tenant_scope))
    r = _redis()
    if r:
        try:
            cached = r.get(_job_result_key(jid))
            if cached:
                return {"ok": True, "job_id": jid, "cached": True, "count": len(keywords)}
        except Exception:
            pass

    lock_key = f"emb:job:lock:{jid}"
    if r:
        try:
            if not r.set(lock_key, "1", nx=True, ex=300):
                for _ in range(30):
                    cached = r.get(_job_result_key(jid))
                    if cached:
                        return {"ok": True, "job_id": jid, "cached": True, "count": len(keywords)}
                    import time

                    time.sleep(0.2)
        except Exception:
            pass

    try:
        emb = embed_keywords_local(keywords, tenant_scope=tenant_scope, use_cache=True)
        _MODEL_LOAD_COUNT += 1
        if r:
            try:
                r.setex(_job_result_key(jid), 600, _serialize_embeddings(emb))
            except Exception:
                pass
        return {"ok": True, "job_id": jid, "count": len(emb), "backend": "worker"}
    except Exception as exc:
        log.exception("embed_keywords_task failed job_id=%s", jid)
        if r:
            try:
                r.delete(lock_key)
            except Exception:
                pass
        raise self.retry(exc=exc, countdown=5)
    finally:
        if r:
            try:
                r.delete(lock_key)
            except Exception:
                pass


def embed_keywords_via_worker(
    keywords: list[str],
    *,
    tenant_scope: str = "global",
    timeout: float | None = None,
) -> dict[str, Any]:
    """Sync call from Uvicorn — model runs on embedding worker, not web process."""
    import numpy as np

    uniq = [k for k in dict.fromkeys(k.strip() for k in keywords if k and k.strip())]
    if not uniq:
        return {}

    jid = _embedding_job_id(uniq, tenant_scope)
    r = _redis()
    if r:
        try:
            cached = r.get(_job_result_key(jid))
            if cached:
                return _deserialize_embeddings(cached)
        except Exception:
            pass

    wait = float(timeout or os.getenv("EMBEDDING_CELERY_TIMEOUT", "45"))
    async_result = embed_keywords_task.apply_async(
        args=[uniq, tenant_scope, jid],
        task_id=f"emb-{jid[:32]}",
        queue=os.getenv("CELERY_EMBEDDING_QUEUE", "embedding"),
    )
    try:
        async_result.get(timeout=wait, propagate=True)
    except Exception as exc:
        log.warning("embed_keywords_via_worker timeout/error: %s", exc)
        from app.services.semantic_embedding import embed_keywords_tfidf_only

        return embed_keywords_tfidf_only(uniq)

    if r:
        try:
            cached = r.get(_job_result_key(jid))
            if cached:
                return _deserialize_embeddings(cached)
        except Exception:
            pass
    return {}


def enqueue_wp_corpus_sync(
    *,
    user_id: int,
    target_website: str,
    keywords: list[str],
    role: str = "user",
) -> None:
    sync_wp_corpus_task.apply_async(
        kwargs={
            "user_id": int(user_id),
            "target_website": str(target_website),
            "search_keywords": list(keywords),
            "role": str(role or "user"),
        },
        queue=os.getenv("CELERY_EMBEDDING_QUEUE", "embedding"),
    )


@celery_app.task(
    name="duplicate.sync_wp_corpus",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def sync_wp_corpus_task(
    self,
    *,
    user_id: int,
    target_website: str,
    search_keywords: list[str] | None = None,
    role: str = "user",
) -> dict[str, Any]:
    try:
        return sync_wp_corpus_incremental(
            user_id=int(user_id),
            target_website=str(target_website),
            search_keywords=list(search_keywords or []),
            role=str(role or "user"),
        )
    except Exception as exc:
        log.exception("sync_wp_corpus_task failed user=%s site=%s", user_id, target_website)
        return {"ok": False, "error": str(exc)[:500]}
