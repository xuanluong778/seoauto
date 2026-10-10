"""Shared async task ownership (PostgreSQL + Redis) — multi-worker / multi-process safe."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.user_scope import is_admin_role

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "seoauto:async_task_owner:"
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def _ttl_seconds() -> int:
    raw = (os.getenv("ASYNC_TASK_OWNER_TTL_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECONDS


def _redis():
    try:
        import redis

        url = (os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
        return redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def _resolve_org_id(user_id: int, organization_id: int | None, db: Session | None) -> int:
    from app.services.tenant_org import OrganizationForbiddenError, personal_organization_id, resolve_organization_id

    if organization_id is None:
        return personal_organization_id(int(user_id))
    try:
        return resolve_organization_id(int(user_id), organization_id, db=db)
    except OrganizationForbiddenError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy task.",
        ) from None


def _redis_key(task_id: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{task_id}"


def _cache_set(task_id: str, user_id: int, organization_id: int) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(
            _redis_key(task_id),
            _ttl_seconds(),
            json.dumps({"user_id": int(user_id), "organization_id": int(organization_id)}),
        )
    except Exception:
        logger.debug("async_task_owner_redis_set_failed", exc_info=True)


def _cache_get(task_id: str) -> dict[str, int] | None:
    r = _redis()
    if r is None:
        return None
    try:
        raw = r.get(_redis_key(task_id))
    except Exception:
        logger.debug("async_task_owner_redis_get_failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return {"user_id": int(data["user_id"]), "organization_id": int(data["organization_id"])}
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _cache_delete(task_id: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.delete(_redis_key(task_id))
    except Exception:
        logger.debug("async_task_owner_redis_del_failed", exc_info=True)


def get_task_owner(
    task_id: str,
    *,
    db: Session | None = None,
) -> dict[str, int] | None:
    """Return ``{user_id, organization_id}`` or None. Shared across workers via Redis/PG."""
    tid = str(task_id or "").strip()
    if not tid:
        return None
    cached = _cache_get(tid)
    if cached is not None:
        return cached

    own = db is None
    session = db or SessionLocal()
    try:
        from app.models.async_task_owner import AsyncTaskOwner

        row = session.get(AsyncTaskOwner, tid)
        if row is None:
            return None
        out = {"user_id": int(row.user_id), "organization_id": int(row.organization_id)}
        _cache_set(tid, out["user_id"], out["organization_id"])
        return out
    finally:
        if own:
            session.close()


def register_task_owner(
    task_id: str,
    user_id: int,
    *,
    organization_id: int | None = None,
    db: Session | None = None,
) -> None:
    """Persist task ownership for multi-worker poll/cancel IDOR guards."""
    tid = str(task_id or "").strip()
    if not tid:
        return
    uid = int(user_id)
    if uid <= 0:
        return

    own = db is None
    session = db or SessionLocal()
    try:
        org_id = _resolve_org_id(uid, organization_id, session)
        from app.models.async_task_owner import AsyncTaskOwner

        row = session.get(AsyncTaskOwner, tid)
        if row is None:
            session.add(
                AsyncTaskOwner(
                    task_id=tid,
                    user_id=uid,
                    organization_id=int(org_id),
                )
            )
        else:
            # Do not reassign to another tenant
            if int(row.user_id) != uid or int(row.organization_id) != int(org_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Task ownership conflict.",
                )
        if own:
            session.commit()
        else:
            session.flush()
        _cache_set(tid, uid, int(org_id))
    except HTTPException:
        if own:
            try:
                session.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own:
            try:
                session.rollback()
            except Exception:
                pass
        logger.exception("async_task_owner_register_failed task_id=%s", tid)
        raise
    finally:
        if own:
            session.close()


def assert_task_owner(
    task_id: str,
    user_id: int,
    *,
    role: str = "user",
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, int]:
    """Raise 404 unless the caller owns the task (admins bypass)."""
    tid = str(task_id or "").strip()
    if not tid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy task.")
    if is_admin_role(role):
        owner = get_task_owner(tid, db=db) or {"user_id": int(user_id), "organization_id": int(user_id)}
        return owner

    owner = get_task_owner(tid, db=db)
    if owner is None or int(owner["user_id"]) != int(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy task.")

    if organization_id is not None:
        own = db is None
        session = db or SessionLocal()
        try:
            expected = _resolve_org_id(int(user_id), organization_id, session)
        finally:
            if own:
                session.close()
        if int(owner["organization_id"]) != int(expected):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy task.")
    return owner


def revoke_owned_task(
    task_id: str,
    user_id: int,
    *,
    role: str = "user",
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Cancel/revoke a Celery task after ownership check.
    Blocks cross-tenant revoke; returns Celery revoke acknowledgement.
    """
    owner = assert_task_owner(
        task_id, user_id, role=role, organization_id=organization_id, db=db
    )
    try:
        from celery.result import AsyncResult

        from app.queue.celery_app import celery_app
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    AsyncResult(str(task_id).strip(), app=celery_app).revoke(terminate=False)
    _cache_delete(str(task_id).strip())
    return {"task_id": str(task_id).strip(), "revoked": True, "owner": owner}
