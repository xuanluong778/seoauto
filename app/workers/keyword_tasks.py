"""Celery tasks: keyword research / clustering (batch, async)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.queue.celery_app import celery_app

_LOG = logging.getLogger(__name__)


def _payload_to_research_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    seeds = payload.get("seeds") or []
    if not isinstance(seeds, list):
        seeds = []
    seeds = [str(s).strip() for s in seeds if str(s).strip()][:50]
    out: dict[str, Any] = {"seed_keywords": seeds}
    for key in (
        "domain",
        "url",
        "gsc_queries",
        "pages",
        "engine",
        "language",
        "country",
        "device",
        "cluster_mode",
        "cluster_strictness",
        "cluster_fetch_serp",
        "cluster_max_keywords",
    ):
        if key in payload:
            out[key] = payload[key]
    return out


def _max_retries() -> int:
    try:
        return max(0, int(os.getenv("KEYWORD_RESEARCH_MAX_RETRIES", "2")))
    except (TypeError, ValueError):
        return 2


def _finalize_reservation(payload: dict[str, Any], *, success: bool) -> None:
    """Commit on success; release on final failure. Retries keep hold (no re-charge)."""
    rid = payload.get("_credit_reservation_id")
    uid = payload.get("_owner_user_id")
    if not rid or not uid:
        return
    from app.db import SessionLocal
    from app.services.credits import commit_reservation, release_reservation

    db = SessionLocal()
    try:
        if success:
            commit_reservation(db, reservation_id=int(rid), user_id=int(uid))
        else:
            release_reservation(
                db,
                reservation_id=int(rid),
                user_id=int(uid),
                reason="celery_final_failure",
            )
        db.commit()
    except Exception:
        _LOG.exception("keyword_task reservation finalize failed rid=%s success=%s", rid, success)
        db.rollback()
    finally:
        db.close()


@celery_app.task(
    name="keywords.research_run",
    bind=True,
    max_retries=_max_retries(),
    acks_late=True,
)
def run_keyword_research_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.keyword_research_pipeline import build_keyword_research_api_response

    payload = dict(payload or {})
    kwargs = _payload_to_research_kwargs(payload)
    if not kwargs.get("seed_keywords"):
        _finalize_reservation(payload, success=False)
        return {
            "clusters": [],
            "meta": {"error": "seed_keyword_required", "task": "keywords.research_run", "entity": "cluster"},
        }
    try:
        result = build_keyword_research_api_response(**kwargs)
        if isinstance(result, dict) and (result.get("meta") or {}).get("error"):
            # Business error — refund credit
            _finalize_reservation(payload, success=False)
            return result
        _finalize_reservation(payload, success=True)
        return result
    except Exception as exc:
        retries = int(getattr(self.request, "retries", 0) or 0)
        max_r = int(getattr(self, "max_retries", 0) or 0)
        if retries < max_r:
            # Keep reservation reserved; retry does not re-debit (idempotency/hold).
            _LOG.warning(
                "keyword_research_task retry %s/%s: %s",
                retries + 1,
                max_r,
                exc,
            )
            raise self.retry(exc=exc, countdown=min(60, 2 ** max(0, retries)))
        _finalize_reservation(payload, success=False)
        raise
