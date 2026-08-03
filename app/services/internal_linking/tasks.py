from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.queue.celery_app import celery_app
from app.services.internal_linking.crawler import sync_wordpress_site
from app.services.internal_linking.embeddings import embed_chunks_for_site
from app.services.site_ownership import user_owns_wp_site

log = logging.getLogger(__name__)


def _assert_site_task_access(wp_site: str, user_id: int, role: str) -> bool:
    if int(user_id or 0) <= 0:
        return False
    return user_owns_wp_site(int(user_id), wp_site, role=role or "user")


@celery_app.task(name="internal_links.sync_site", bind=True, max_retries=1)
def task_sync_site(
    self,
    wp_site: str,
    limit_per_type: int = 400,
    user_id: int = 0,
    role: str = "user",
) -> dict[str, Any]:
    if not _assert_site_task_access(wp_site, user_id, role):
        return {"ok": False, "error": "forbidden", "wp_site": wp_site}
    db: Session = SessionLocal()
    try:
        res = sync_wordpress_site(db=db, wp_site=wp_site, limit_per_type=int(limit_per_type), recreate_chunks=True)
        return {
            "ok": True,
            "wp_site": res.wp_site,
            "fetched": res.fetched,
            "upserted_articles": res.upserted_articles,
            "upserted_chunks": res.upserted_chunks,
        }
    except Exception as exc:
        log.exception("task_sync_site failed wp_site=%s", wp_site)
        return {"ok": False, "error": str(exc)[:900], "wp_site": wp_site}
    finally:
        db.close()


@celery_app.task(name="internal_links.embed_site", bind=True, max_retries=1)
def task_embed_site(
    self,
    wp_site: str,
    model_name: str = "",
    only_missing: bool = True,
    user_id: int = 0,
    role: str = "user",
) -> dict[str, Any]:
    if not _assert_site_task_access(wp_site, user_id, role):
        return {"ok": False, "error": "forbidden", "wp_site": wp_site}
    db: Session = SessionLocal()
    try:
        res = embed_chunks_for_site(db=db, wp_site=wp_site, model_name=(model_name or None), only_missing=bool(only_missing))
        return {
            "ok": True,
            "wp_site": wp_site,
            "embedding_model": res.embedding_model,
            "embedded_chunks": res.embedded_chunks,
            "skipped_chunks": res.skipped_chunks,
        }
    except Exception as exc:
        log.exception("task_embed_site failed wp_site=%s", wp_site)
        return {"ok": False, "error": str(exc)[:900], "wp_site": wp_site}
    finally:
        db.close()
