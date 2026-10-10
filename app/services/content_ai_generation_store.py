"""PostgreSQL store for Content AI async generations."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.content_ai_generation import ContentAiGeneration
from app.migrations.ensure_content_ai_generations import ensure_content_ai_generations_schema

_LOG = logging.getLogger(__name__)

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


@dataclass
class GenerationState:
    generation_id: str
    user_id: int
    organization_id: int
    state: str
    progress: int
    message: str
    idempotency_key: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    credit_request_id: str | None
    credits_charged: int
    last_stream_seq: int
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _row_to_state(row: ContentAiGeneration) -> GenerationState:
    return GenerationState(
        generation_id=str(row.generation_id),
        user_id=int(row.user_id),
        organization_id=int(row.organization_id),
        state=str(row.state or "QUEUED"),
        progress=int(row.progress or 0),
        message=str(row.message or ""),
        idempotency_key=str(row.idempotency_key),
        request=_loads(row.request_payload_json),
        result=_loads(row.result_json) if row.result_json else None,
        error=str(row.error) if row.error else None,
        credit_request_id=str(row.credit_request_id) if row.credit_request_id else None,
        credits_charged=int(row.credits_charged or 0),
        last_stream_seq=int(row.last_stream_seq or 0),
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def ensure_schema() -> None:
    ensure_content_ai_generations_schema()


def create_generation(
    db: Session,
    *,
    user_id: int,
    organization_id: int,
    idempotency_key: str,
    request_payload: dict[str, Any],
    credit_request_id: str | None = None,
) -> GenerationState:
    ensure_schema()
    key = str(idempotency_key or "").strip()[:128]
    if not key:
        key = uuid.uuid4().hex
    existing = (
        db.query(ContentAiGeneration)
        .filter(
            ContentAiGeneration.user_id == int(user_id),
            ContentAiGeneration.idempotency_key == key,
        )
        .order_by(ContentAiGeneration.id.desc())
        .first()
    )
    if existing is not None:
        return _row_to_state(existing)

    gid = uuid.uuid4().hex
    now = _now()
    row = ContentAiGeneration(
        generation_id=gid,
        idempotency_key=key,
        user_id=int(user_id),
        organization_id=int(organization_id),
        state="QUEUED",
        progress=0,
        message="Queued",
        request_payload_json=json.dumps(request_payload or {}, ensure_ascii=False),
        credit_request_id=str(credit_request_id or "")[:64] or None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_state(row)


def get_generation(db: Session, generation_id: str) -> GenerationState | None:
    row = (
        db.query(ContentAiGeneration)
        .filter(ContentAiGeneration.generation_id == str(generation_id))
        .first()
    )
    return _row_to_state(row) if row else None


def get_generation_for_user(
    db: Session, generation_id: str, *, user_id: int, organization_id: int | None = None
) -> GenerationState | None:
    q = db.query(ContentAiGeneration).filter(
        ContentAiGeneration.generation_id == str(generation_id),
        ContentAiGeneration.user_id == int(user_id),
    )
    if organization_id is not None:
        q = q.filter(ContentAiGeneration.organization_id == int(organization_id))
    row = q.first()
    return _row_to_state(row) if row else None


def claim_generation(generation_id: str) -> GenerationState | None:
    """CAS QUEUED → RUNNING (row lock on PG; BEGIN IMMEDIATE on SQLite)."""
    db = SessionLocal()
    try:
        dialect = db.bind.dialect.name if db.bind else ""
        if dialect == "sqlite":
            from sqlalchemy import text

            try:
                db.execute(text("BEGIN IMMEDIATE"))
            except Exception:
                pass
        q = db.query(ContentAiGeneration).filter(
            ContentAiGeneration.generation_id == str(generation_id),
            ContentAiGeneration.state == "QUEUED",
        )
        if dialect == "postgresql":
            q = q.with_for_update(skip_locked=True)
        row = q.first()
        if not row:
            db.rollback()
            st = get_generation(db, generation_id)
            return st
        now = _now()
        row.state = "RUNNING"
        row.progress = max(1, int(row.progress or 1))
        row.message = "Running"
        row.started_at = now
        row.updated_at = now
        db.commit()
        return _row_to_state(row)
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()


def update_generation_progress(
    generation_id: str,
    *,
    progress: int | None = None,
    message: str | None = None,
    last_stream_seq: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        row = db.query(ContentAiGeneration).filter(ContentAiGeneration.generation_id == str(generation_id)).first()
        if not row:
            return
        if progress is not None:
            row.progress = int(progress)
        if message is not None:
            row.message = str(message)[:500]
        if last_stream_seq is not None:
            row.last_stream_seq = int(last_stream_seq)
        row.updated_at = _now()
        db.commit()
    finally:
        db.close()


def complete_generation(
    generation_id: str,
    *,
    result: dict[str, Any],
    credits_charged: int = 0,
    last_stream_seq: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        row = (
            db.query(ContentAiGeneration)
            .filter(
                ContentAiGeneration.generation_id == str(generation_id),
                ContentAiGeneration.state.in_(("QUEUED", "RUNNING")),
            )
            .first()
        )
        if not row:
            return
        now = _now()
        row.state = "COMPLETED"
        row.progress = 100
        row.message = "Completed"
        row.result_json = json.dumps(result or {}, ensure_ascii=False)
        row.credits_charged = int(credits_charged or 0)
        if last_stream_seq is not None:
            row.last_stream_seq = int(last_stream_seq)
        row.completed_at = now
        row.updated_at = now
        db.commit()
    finally:
        db.close()


def fail_generation(generation_id: str, *, error: str) -> None:
    db = SessionLocal()
    try:
        row = (
            db.query(ContentAiGeneration)
            .filter(
                ContentAiGeneration.generation_id == str(generation_id),
                ContentAiGeneration.state.in_(("QUEUED", "RUNNING")),
            )
            .first()
        )
        if not row:
            return
        now = _now()
        row.state = "FAILED"
        row.message = "Failed"
        row.error = str(error)[:2000]
        row.completed_at = now
        row.updated_at = now
        db.commit()
    finally:
        db.close()


def cancel_generation(db: Session, generation_id: str, *, user_id: int) -> GenerationState | None:
    row = (
        db.query(ContentAiGeneration)
        .filter(
            ContentAiGeneration.generation_id == str(generation_id),
            ContentAiGeneration.user_id == int(user_id),
            ContentAiGeneration.state.in_(("QUEUED", "RUNNING")),
        )
        .first()
    )
    if not row:
        return get_generation_for_user(db, generation_id, user_id=user_id)
    now = _now()
    row.state = "CANCELLED"
    row.message = "Cancelled"
    row.completed_at = now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _row_to_state(row)


def is_cancelled(generation_id: str) -> bool:
    db = SessionLocal()
    try:
        row = db.query(ContentAiGeneration).filter(ContentAiGeneration.generation_id == str(generation_id)).first()
        return bool(row and str(row.state) == "CANCELLED")
    finally:
        db.close()


def list_stale_generations(*, states: tuple[str, ...] = ("QUEUED", "RUNNING"), limit: int = 20) -> list[GenerationState]:
    db = SessionLocal()
    try:
        rows = (
            db.query(ContentAiGeneration)
            .filter(ContentAiGeneration.state.in_(tuple(states)))
            .order_by(ContentAiGeneration.updated_at.asc())
            .limit(max(1, min(int(limit), 50)))
            .all()
        )
        return [_row_to_state(r) for r in rows]
    finally:
        db.close()
