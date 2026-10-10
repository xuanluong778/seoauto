"""Job store for long-running tasks (progress + result).

This store is **persisted** in the database (SQLite by default) so that:
- jobs survive server reload/restart (fixes "Job not found" in the UI)
- polling endpoints remain stable even when dev reloader is enabled
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import os
import json
import base64
import gzip
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models.keyword_cluster_job import KeywordClusterJob
from sqlalchemy import text


def _dialect_name(db) -> str:
    bind = db.get_bind()
    return str(getattr(getattr(bind, "dialect", None), "name", "") or "sqlite")


def _table_column_names(db, table_name: str) -> set[str]:
    dialect = _dialect_name(db)
    if dialect == "sqlite":
        cols = db.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return {str(c[1]) for c in (cols or [])}
    rows = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name"
        ),
        {"table_name": table_name},
    ).fetchall()
    return {str(r[0]) for r in (rows or [])}

@dataclass
class JobState:
    job_id: str
    job_type: str  # "keyword_cluster" | "wp_bulk_update" | ...
    state: str  # QUEUED | RUNNING | SUCCESS | ERROR
    progress: int
    message: str
    created_at: float
    updated_at: float
    result: dict[str, Any] | None = None
    error: str | None = None
    payload: dict[str, Any] | None = None
    user_id: int | None = None
    organization_id: int | None = None


_LOCK = threading.Lock()
_JOBS: dict[str, JobState] = {}


def _row_to_state(row: KeywordClusterJob) -> JobState:
    result: dict[str, Any] | None = None
    if row.result_json:
        try:
            raw = str(row.result_json or "")
            if raw.startswith("gz:"):
                b = base64.b64decode(raw[3:].encode("ascii"))
                js = gzip.decompress(b).decode("utf-8", errors="replace")
                result = json.loads(js)
            else:
                result = json.loads(raw)
        except Exception:
            result = None
    payload: dict[str, Any] | None = None
    if getattr(row, "payload_json", None):
        try:
            payload = json.loads(row.payload_json) if row.payload_json else None
        except Exception:
            payload = None
    return JobState(
        job_id=row.job_id,
        job_type=str(getattr(row, "job_type", "") or "generic"),
        state=row.state,
        progress=int(row.progress or 0),
        message=str(row.message or "")[:500],
        created_at=row.created_at.timestamp() if row.created_at else time.time(),
        updated_at=row.updated_at.timestamp() if row.updated_at else time.time(),
        result=result,
        error=row.error,
        payload=payload,
        user_id=int(row.user_id) if getattr(row, "user_id", None) is not None else None,
        organization_id=int(row.organization_id) if getattr(row, "organization_id", None) is not None else None,
    )


def _encode_result_json(result: dict[str, Any]) -> str:
    """
    Store job results safely without producing invalid JSON.
    If the JSON is large, gzip+base64 it with `gz:` prefix.
    """
    max_chars = int(os.getenv("JOB_RESULT_MAX_CHARS", "5000000"))  # 5MB default
    max_blob = int(os.getenv("JOB_RESULT_MAX_BLOB_CHARS", "9000000"))  # 9MB for gz payload
    raw = json.dumps(result or {}, ensure_ascii=False)
    if len(raw) <= max_chars:
        return raw
    comp = gzip.compress(raw.encode("utf-8"), compresslevel=6)
    b64 = base64.b64encode(comp).decode("ascii")
    out = "gz:" + b64
    if len(out) > max_blob:
        raise ValueError(f"Job result too large to store ({len(out)} chars)")
    return out

def ensure_job_schema() -> None:
    """
    Lightweight migration: add new columns if missing (SQLite + PostgreSQL).
    This keeps the system stable without an external migration tool.
    """
    db = SessionLocal()
    try:
        names = _table_column_names(db, "keyword_cluster_jobs")
        if not names:
            return
        dialect = _dialect_name(db)
        ts_type = "DATETIME" if dialect == "sqlite" else "TIMESTAMP WITH TIME ZONE"
        alters: list[str] = []
        if "job_type" not in names:
            alters.append(
                "ALTER TABLE keyword_cluster_jobs ADD COLUMN job_type VARCHAR(32) NOT NULL DEFAULT 'generic'"
            )
        if "payload_json" not in names:
            alters.append("ALTER TABLE keyword_cluster_jobs ADD COLUMN payload_json TEXT")
        if "started_at" not in names:
            alters.append(f"ALTER TABLE keyword_cluster_jobs ADD COLUMN started_at {ts_type}")
        if "finished_at" not in names:
            alters.append(f"ALTER TABLE keyword_cluster_jobs ADD COLUMN finished_at {ts_type}")
        if "user_id" not in names:
            alters.append("ALTER TABLE keyword_cluster_jobs ADD COLUMN user_id INTEGER")
        if "organization_id" not in names:
            alters.append("ALTER TABLE keyword_cluster_jobs ADD COLUMN organization_id INTEGER")
        for sql in alters:
            db.execute(text(sql))
        if alters:
            db.commit()
        # indexes (best-effort)
        try:
            dialect = _dialect_name(db)
            if dialect == "postgresql":
                db.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_keyword_cluster_jobs_user "
                        "ON keyword_cluster_jobs (user_id)"
                    )
                )
                db.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_keyword_cluster_jobs_org "
                        "ON keyword_cluster_jobs (organization_id)"
                    )
                )
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _db_upsert(
    job_id: str,
    *,
    state: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        row = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == job_id).first()
        if not row:
            row = KeywordClusterJob(job_id=job_id)
            db.add(row)
        if state is not None:
            row.state = str(state)[:16]
        if progress is not None:
            row.progress = max(0, min(100, int(progress)))
        if message is not None:
            row.message = str(message)[:500]
        if result is not None:
            row.result_json = _encode_result_json(result)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


def create_job(
    *,
    job_type: str = "generic",
    message: str = "Queued",
    payload: dict[str, Any] | None = None,
    user_id: int | None = None,
    organization_id: int | None = None,
) -> JobState:
    jid = uuid.uuid4().hex
    now = time.time()
    # Resolve owner from explicit args or payload (args win)
    uid: int | None = int(user_id) if user_id is not None and int(user_id) > 0 else None
    oid: int | None = int(organization_id) if organization_id is not None and int(organization_id) > 0 else None
    if payload:
        if uid is None:
            try:
                puid = int(payload.get("user_id") or 0)
                uid = puid if puid > 0 else None
            except (TypeError, ValueError):
                uid = None
        if oid is None:
            try:
                poid = int(payload.get("organization_id") or 0)
                oid = poid if poid > 0 else None
            except (TypeError, ValueError):
                oid = None
    if uid is not None:
        from app.services.tenant_org import OrganizationForbiddenError, resolve_organization_id

        _org_db = SessionLocal()
        try:
            oid = resolve_organization_id(uid, oid, db=_org_db)
        except OrganizationForbiddenError:
            raise
        finally:
            _org_db.close()
    # Always put ownership into payload for workers
    merged_payload = dict(payload or {})
    if uid is not None:
        merged_payload["user_id"] = uid
    if oid is not None:
        merged_payload["organization_id"] = oid

    st = JobState(
        job_id=jid,
        job_type=str(job_type or "generic")[:32],
        state="QUEUED",
        progress=0,
        message=message,
        created_at=now,
        updated_at=now,
        result=None,
        error=None,
        payload=merged_payload or None,
        user_id=uid,
        organization_id=oid,
    )
    with _LOCK:
        _JOBS[jid] = st
    # Persist immediately so polling works across reloads (single transaction; avoid race with worker claim).
    db = SessionLocal()
    try:
        row = KeywordClusterJob(job_id=jid)
        try:
            row.job_type = st.job_type
        except Exception:
            pass
        row.state = st.state
        row.progress = st.progress
        row.message = st.message
        if uid is not None:
            row.user_id = uid
        if oid is not None:
            row.organization_id = oid
        if merged_payload:
            row.payload_json = json.dumps(merged_payload, ensure_ascii=False)[:400000]
        db.add(row)
        db.commit()
    finally:
        db.close()
    return st


def get_job(job_id: str) -> JobState | None:
    # Prefer DB so jobs survive reload/restart.
    db = SessionLocal()
    try:
        row = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == job_id).first()
        if row:
            st = _row_to_state(row)
            with _LOCK:
                _JOBS[job_id] = st
            return st
    finally:
        db.close()
    with _LOCK:
        return _JOBS.get(job_id)


def find_recent_job_by_fingerprint(
    user_id: int,
    job_type: str,
    fingerprint: str,
    *,
    max_age_seconds: int = 900,
) -> JobState | None:
    """Reuse an in-flight job for the same user + type + fingerprint (no cross-tenant)."""
    uid = int(user_id or 0)
    fp = str(fingerprint or "").strip()
    jt = str(job_type or "").strip()[:32]
    if uid <= 0 or not fp or not jt:
        return None
    try:
        age = max(30, int(max_age_seconds or 900))
    except (TypeError, ValueError):
        age = 900
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=age)
    db = SessionLocal()
    try:
        rows = (
            db.query(KeywordClusterJob)
            .filter(KeywordClusterJob.user_id == uid)
            .filter(KeywordClusterJob.job_type == jt)
            .filter(KeywordClusterJob.state.in_(("QUEUED", "PENDING")))
            .filter(KeywordClusterJob.created_at >= cutoff)
            .order_by(KeywordClusterJob.created_at.desc())
            .limit(40)
            .all()
        )
        for row in rows or []:
            st = _row_to_state(row)
            payload = st.payload if isinstance(st.payload, dict) else {}
            if str(payload.get("job_fingerprint") or "").strip() == fp:
                with _LOCK:
                    _JOBS[st.job_id] = st
                return st
        return None
    finally:
        db.close()


def get_job_for_user(
    job_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
) -> JobState | None:
    """Load job only if DB ownership columns match tenant (not payload-only)."""
    uid = int(user_id or 0)
    if uid <= 0 or not str(job_id or "").strip():
        return None
    db = SessionLocal()
    try:
        from app.services.tenant_org import (
            OrganizationForbiddenError,
            personal_organization_id,
            resolve_organization_id,
        )

        try:
            org_id = resolve_organization_id(uid, organization_id, db=db)
        except OrganizationForbiddenError:
            return None

        q = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == str(job_id))
        row = q.first()
        if not row:
            return None
        row_uid = getattr(row, "user_id", None)
        row_org = getattr(row, "organization_id", None)
        # Legacy rows: fall back to payload user_id only if column empty — still require match
        if row_uid is None:
            try:
                payload = json.loads(row.payload_json) if row.payload_json else {}
            except Exception:
                payload = {}
            try:
                row_uid = int((payload or {}).get("user_id") or 0) or None
            except (TypeError, ValueError):
                row_uid = None
            if row_uid is None:
                return None
            # Backfill columns on read for next time
            try:
                row.user_id = int(row_uid)
                row.organization_id = int(row_org or personal_organization_id(int(row_uid)))
                db.commit()
                row_org = row.organization_id
            except Exception:
                db.rollback()
        if int(row_uid) != uid:
            return None
        if row_org is not None and int(row_org) != int(org_id):
            return None
        st = _row_to_state(row)
        with _LOCK:
            _JOBS[job_id] = st
        return st
    finally:
        db.close()


def update_job(
    job_id: str,
    *,
    state: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    now = time.time()
    with _LOCK:
        st = _JOBS.get(job_id)
        if not st:
            st = JobState(
                job_id=job_id,
                state=state or "RUNNING",
                progress=max(0, min(100, int(progress or 0))),
                message=str(message or "")[:500],
                created_at=now,
                updated_at=now,
                result=None,
                error=None,
            )
            _JOBS[job_id] = st
        if state is not None:
            st.state = state
        if progress is not None:
            st.progress = max(0, min(100, int(progress)))
        if message is not None:
            st.message = str(message)[:500]
        if result is not None:
            st.result = result
        st.updated_at = now
    _db_upsert(job_id, state=state, progress=progress, message=message, result=result)


def finish_job(job_id: str, *, result: dict[str, Any]) -> None:
    now = time.time()
    with _LOCK:
        st = _JOBS.get(job_id)
        if not st:
            st = JobState(
                job_id=job_id,
                state="SUCCESS",
                progress=100,
                message="Done",
                created_at=now,
                updated_at=now,
                result=None,
                error=None,
            )
            _JOBS[job_id] = st
        st.state = "SUCCESS"
        st.progress = 100
        st.message = "Done"
        st.result = result
        st.updated_at = now
    db = SessionLocal()
    try:
        row = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == job_id).first()
        if not row:
            row = KeywordClusterJob(job_id=job_id)
            db.add(row)
        row.state = "SUCCESS"
        row.progress = 100
        row.message = "Done"
        row.result_json = _encode_result_json(result or {})
        row.error = None
        try:
            row.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
    finally:
        db.close()


def fail_job(job_id: str, *, error: str) -> None:
    now = time.time()
    with _LOCK:
        st = _JOBS.get(job_id)
        if not st:
            st = JobState(
                job_id=job_id,
                state="ERROR",
                progress=0,
                message="Error",
                created_at=now,
                updated_at=now,
                result=None,
                error=None,
            )
            _JOBS[job_id] = st
        st.state = "ERROR"
        st.progress = min(99, max(0, int(st.progress)))
        st.message = "Error"
        st.error = str(error)[:2000]
        st.updated_at = now
    db = SessionLocal()
    try:
        row = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == job_id).first()
        if not row:
            row = KeywordClusterJob(job_id=job_id)
            db.add(row)
        row.state = "ERROR"
        row.progress = min(99, max(0, int(row.progress or 0)))
        row.message = "Error"
        row.error = str(error)[:2000]
        # Keep result_json so poll still shows written items / x/y progress.
        try:
            row.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        try:
            row.updated_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
    finally:
        db.close()


def cancel_job(job_id: str, *, message: str = "Cancelled") -> JobState | None:
    """Mark QUEUED/PENDING/RUNNING job CANCELLED. Returns current state if already finished."""
    jid = str(job_id or "").strip()
    if not jid:
        return None
    now = time.time()
    db = SessionLocal()
    try:
        row = db.query(KeywordClusterJob).filter(KeywordClusterJob.job_id == jid).first()
        if not row:
            with _LOCK:
                st = _JOBS.get(jid)
            return st
        state = str(row.state or "").strip().upper()
        if state in ("SUCCESS", "ERROR", "CANCELLED"):
            st = _row_to_state(row)
            with _LOCK:
                _JOBS[jid] = st
            return st
        row.state = "CANCELLED"
        row.message = str(message or "Cancelled")[:500]
        row.error = None
        try:
            row.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
        st = _row_to_state(row)
        st.updated_at = now
        with _LOCK:
            _JOBS[jid] = st
        return st
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def mark_stale_jobs_failed(*, stale_seconds: int = 300) -> int:
    """
    Watchdog: if a RUNNING job hasn't updated for > stale_seconds, mark it ERROR.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=int(stale_seconds))
    db = SessionLocal()
    try:
        rows = (
            db.query(KeywordClusterJob)
            .filter(KeywordClusterJob.state == "RUNNING")
            .filter(KeywordClusterJob.updated_at < cutoff)
            .all()
        )
        n = 0
        for r in rows or []:
            r.state = "ERROR"
            r.message = "Error"
            r.error = f"Watchdog: no progress update for >{stale_seconds}s"
            try:
                r.finished_at = now
            except Exception:
                pass
            n += 1
        if n:
            db.commit()
        return n
    finally:
        db.close()


def mark_stale_queued_failed(*, stale_seconds: int = 90) -> int:
    """
    If a job stays QUEUED too long, likely no worker is running. Mark ERROR to avoid "stuck at 0%".
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=int(stale_seconds))
    db = SessionLocal()
    try:
        rows = (
            db.query(KeywordClusterJob)
            .filter(KeywordClusterJob.state.in_(("QUEUED", "PENDING")))
            .filter(KeywordClusterJob.created_at < cutoff)
            .all()
        )
        n = 0
        for r in rows or []:
            r.state = "ERROR"
            r.message = "Error"
            r.error = (
                f"No worker claimed job for >{stale_seconds}s. "
                "Enable KEYWORD_CLUSTER_INLINE=1 or start cluster worker "
                "(scripts/keyword_cluster_worker.py)."
            )
            try:
                r.finished_at = now
            except Exception:
                pass
            n += 1
        if n:
            db.commit()
        return n
    finally:
        db.close()


def claim_next_pending_job(*, job_type: str | None = None) -> JobState | None:
    """
    Worker: atomically pick the oldest QUEUED job and mark RUNNING.
    SQLite uses BEGIN IMMEDIATE; PostgreSQL uses FOR UPDATE SKIP LOCKED.
    """
    db = SessionLocal()
    try:
        dialect = _dialect_name(db)
        if dialect == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        q = db.query(KeywordClusterJob).filter(KeywordClusterJob.state.in_(("QUEUED", "PENDING")))
        jt = (job_type or "").strip()
        if jt:
            try:
                q = q.filter(KeywordClusterJob.job_type == jt[:32])
            except Exception:
                # Column may not exist in some environments; ignore filter.
                pass
        q = q.order_by(KeywordClusterJob.created_at.asc())
        if dialect != "sqlite":
            q = q.with_for_update(skip_locked=True)
        row = q.first()
        if not row:
            db.rollback()
            return None
        row.state = "RUNNING"
        row.progress = max(1, int(row.progress or 1))
        row.message = str(row.message or "Starting")[:500]
        try:
            row.started_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
        st = _row_to_state(row)
        with _LOCK:
            _JOBS[st.job_id] = st
        return st
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def claim_job_by_id(job_id: str) -> JobState | None:
    """CAS: claim one QUEUED/PENDING job by id. None if already running/done."""
    jid = str(job_id or "").strip()
    if not jid:
        return None
    db = SessionLocal()
    try:
        dialect = _dialect_name(db)
        if dialect == "sqlite":
            try:
                db.execute(text("BEGIN IMMEDIATE"))
            except Exception:
                pass
        q = (
            db.query(KeywordClusterJob)
            .filter(KeywordClusterJob.job_id == jid)
            .filter(KeywordClusterJob.state.in_(("QUEUED", "PENDING")))
        )
        if dialect != "sqlite":
            q = q.with_for_update(skip_locked=True)
        row = q.first()
        if not row:
            db.rollback()
            return None
        now = datetime.now(timezone.utc)
        row.state = "RUNNING"
        row.progress = max(1, int(row.progress or 1))
        row.message = str(row.message or "Starting")[:500]
        row.started_at = now
        row.updated_at = now
        db.commit()
        st = _row_to_state(row)
        with _LOCK:
            _JOBS[st.job_id] = st
        return st
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def list_running_jobs(*, job_type: str | None = None, limit: int = 20) -> list[JobState]:
    """RUNNING jobs of a type, oldest first — used to resume orphans after restart."""
    db = SessionLocal()
    try:
        q = db.query(KeywordClusterJob).filter(KeywordClusterJob.state == "RUNNING")
        jt = (job_type or "").strip()
        if jt:
            try:
                q = q.filter(KeywordClusterJob.job_type == jt[:32])
            except Exception:
                pass
        q = q.order_by(KeywordClusterJob.updated_at.asc())
        try:
            cap = max(1, min(int(limit or 20), 50))
        except (TypeError, ValueError):
            cap = 20
        rows = q.limit(cap).all()
        out: list[JobState] = []
        for row in rows or []:
            st = _row_to_state(row)
            with _LOCK:
                _JOBS[st.job_id] = st
            out.append(st)
        return out
    finally:
        db.close()


def list_jobs_by_states(
    *,
    states: tuple[str, ...] | list[str],
    job_types: tuple[str, ...] | list[str] | None = None,
    limit: int = 20,
) -> list[JobState]:
    """Oldest-first jobs matching states (and optional job_types) — recover/requeue helpers."""
    db = SessionLocal()
    try:
        state_list = [str(s).strip().upper() for s in (states or []) if str(s).strip()]
        if not state_list:
            return []
        q = db.query(KeywordClusterJob).filter(KeywordClusterJob.state.in_(state_list))
        if job_types:
            types = [str(t).strip()[:32] for t in job_types if str(t).strip()]
            if types:
                q = q.filter(KeywordClusterJob.job_type.in_(types))
        q = q.order_by(KeywordClusterJob.created_at.asc())
        try:
            cap = max(1, min(int(limit or 20), 100))
        except (TypeError, ValueError):
            cap = 20
        rows = q.limit(cap).all()
        out: list[JobState] = []
        for row in rows or []:
            st = _row_to_state(row)
            with _LOCK:
                _JOBS[st.job_id] = st
            out.append(st)
        return out
    finally:
        db.close()


def cleanup_expired(*, ttl_seconds: int = 1800) -> None:
    """Drop jobs older than ttl_seconds (default 30 minutes)."""
    cutoff = time.time() - ttl_seconds
    with _LOCK:
        dead = [jid for jid, st in _JOBS.items() if st.updated_at < cutoff]
        for jid in dead:
            _JOBS.pop(jid, None)
    # Also cleanup persisted jobs.
    db = SessionLocal()
    try:
        dt_cut = datetime.now(timezone.utc) - timedelta(seconds=int(ttl_seconds))
        db.query(KeywordClusterJob).filter(KeywordClusterJob.updated_at < dt_cut).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

