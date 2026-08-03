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
        for sql in alters:
            db.execute(text(sql))
        if alters:
            db.commit()
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
        db.commit()
    finally:
        db.close()


def create_job(*, job_type: str = "generic", message: str = "Queued", payload: dict[str, Any] | None = None) -> JobState:
    jid = uuid.uuid4().hex
    now = time.time()
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
        payload=payload,
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
        if payload is not None:
            row.payload_json = json.dumps(payload, ensure_ascii=False)[:400000]
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
        try:
            row.finished_at = datetime.now(timezone.utc)
        except Exception:
            pass
        db.commit()
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

