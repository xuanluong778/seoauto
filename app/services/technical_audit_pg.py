"""PostgreSQL helpers for technical audits (used by audit_store dual-write/read)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.technical_audit import TechnicalAudit

_LOG = logging.getLogger(__name__)
_sqlite_write_lock = __import__("threading").Lock()


def _use_sqlite_lock() -> bool:
    try:
        from app.db import engine as _engine

        return getattr(_engine.dialect, "name", "") == "sqlite"
    except Exception:
        return False


def technical_audits_pg_enabled() -> bool:
    return os.getenv("TECHNICAL_AUDITS_PG", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def technical_audits_json_write_enabled() -> bool:
    """Dual-write JSON while migrating; set 0 only after PG verified."""
    return os.getenv("TECHNICAL_AUDITS_JSON_WRITE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def technical_audits_pg_read_enabled() -> bool:
    return os.getenv("TECHNICAL_AUDITS_PG_READ", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _parse_at(raw: object) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def row_to_dict(row: TechnicalAudit) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    out = dict(payload)
    out["id"] = row.id
    out["audit_id"] = row.id
    out["user_id"] = int(row.user_id)
    out["at"] = row.created_at.isoformat() if row.created_at else out.get("at")
    out["source_url"] = row.source_url or out.get("source_url") or ""
    out["domain"] = row.domain or out.get("domain") or ""
    out["pages_scanned"] = int(row.pages_scanned or 0)
    out["truncated_issues"] = bool(row.truncated_issues)
    if row.idempotency_key:
        out["idempotency_key"] = row.idempotency_key
    if row.organization_id is not None:
        out["organization_id"] = int(row.organization_id)
    if "issues" not in out:
        out["issues"] = []
    return out


def entry_from_payload(entry: dict[str, Any], *, organization_id: int | None = None) -> TechnicalAudit:
    aid = str(entry.get("id") or entry.get("audit_id") or "").strip()
    uid = int(entry.get("user_id"))
    idem = str(entry.get("idempotency_key") or "").strip()[:128] or None
    issues = entry.get("issues") if isinstance(entry.get("issues"), list) else []
    return TechnicalAudit(
        id=aid,
        user_id=uid,
        organization_id=organization_id if organization_id is not None else entry.get("organization_id"),
        created_at=_parse_at(entry.get("at")),
        source_url=str(entry.get("source_url") or "")[:2000],
        domain=str(entry.get("domain") or "")[:255],
        pages_scanned=int(entry.get("pages_scanned") or 0),
        issue_count=len(issues),
        truncated_issues=bool(entry.get("truncated_issues")),
        idempotency_key=idem,
        payload_json=json.dumps(entry, ensure_ascii=False, default=str),
    )


def upsert_audit_entry(entry: dict[str, Any], *, organization_id: int | None = None) -> str:
    """Insert or replace by primary key. Idempotent for same id."""
    row = entry_from_payload(entry, organization_id=organization_id)
    use_lock = _use_sqlite_lock()
    if use_lock:
        _sqlite_write_lock.acquire()
    db = SessionLocal()
    try:
        existing = db.get(TechnicalAudit, row.id)
        if existing is not None:
            if int(existing.user_id) != int(row.user_id):
                raise PermissionError("audit id owned by another user")
            existing.organization_id = row.organization_id
            existing.created_at = row.created_at
            existing.source_url = row.source_url
            existing.domain = row.domain
            existing.pages_scanned = row.pages_scanned
            existing.issue_count = row.issue_count
            existing.truncated_issues = row.truncated_issues
            existing.idempotency_key = row.idempotency_key
            existing.payload_json = row.payload_json
        else:
            if row.idempotency_key:
                hit = db.execute(
                    select(TechnicalAudit).where(
                        TechnicalAudit.user_id == row.user_id,
                        TechnicalAudit.idempotency_key == row.idempotency_key,
                    )
                ).scalar_one_or_none()
                if hit is not None:
                    return str(hit.id)
            db.add(row)
        db.flush()
        audit_id = str(row.id)
        db.commit()
        return audit_id
    except IntegrityError:
        db.rollback()
        if row.idempotency_key:
            hit = db.execute(
                select(TechnicalAudit).where(
                    TechnicalAudit.user_id == row.user_id,
                    TechnicalAudit.idempotency_key == row.idempotency_key,
                )
            ).scalar_one_or_none()
            if hit is not None:
                return str(hit.id)
        raise
    finally:
        db.close()
        if use_lock:
            _sqlite_write_lock.release()


def get_audit_pg(audit_id: str, user_id: int) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        row = db.execute(
            select(TechnicalAudit).where(
                TechnicalAudit.id == str(audit_id).strip(),
                TechnicalAudit.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        return row_to_dict(row) if row else None
    finally:
        db.close()


def get_latest_pg(user_id: int) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        row = db.execute(
            select(TechnicalAudit)
            .where(TechnicalAudit.user_id == int(user_id))
            .order_by(TechnicalAudit.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row_to_dict(row) if row else None
    finally:
        db.close()


def get_by_idempotency_pg(user_id: int, idempotency_key: str) -> dict[str, Any] | None:
    key = str(idempotency_key or "").strip()[:128]
    if not key:
        return None
    use_lock = _use_sqlite_lock()
    if use_lock:
        _sqlite_write_lock.acquire()
    db = SessionLocal()
    try:
        row = db.execute(
            select(TechnicalAudit)
            .where(
                TechnicalAudit.user_id == int(user_id),
                TechnicalAudit.idempotency_key == key,
            )
            .order_by(TechnicalAudit.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row_to_dict(row) if row else None
    finally:
        db.close()
        if use_lock:
            _sqlite_write_lock.release()


def list_audits_pg(user_id: int, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(TechnicalAudit)
                .where(TechnicalAudit.user_id == int(user_id))
                .order_by(TechnicalAudit.created_at.desc())
                .offset(off)
                .limit(lim)
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            full = row_to_dict(row)
            summary = {
                "id": row.id,
                "at": full.get("at"),
                "user_id": row.user_id,
                "domain": row.domain,
                "source_url": row.source_url,
                "pages_scanned": row.pages_scanned,
                "technical_summary": full.get("technical_summary") or {},
                "health_score": None,
                "issue_count": row.issue_count,
                "truncated_issues": row.truncated_issues,
            }
            tdv2 = full.get("technical_dashboard_v2")
            if isinstance(tdv2, dict) and tdv2.get("technical_health_score") is not None:
                summary["health_score"] = tdv2.get("technical_health_score")
            elif isinstance(full.get("technical_summary"), dict):
                summary["health_score"] = (full.get("technical_summary") or {}).get("health_score")
            out.append(summary)
        return out
    finally:
        db.close()


def list_mine_recent_by_domain_pg(user_id: int, limit: int = 8, db: Session | None = None) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 50))
    own = db or SessionLocal()
    close = db is None
    try:
        rows = (
            own.execute(
                select(
                    TechnicalAudit.id,
                    TechnicalAudit.created_at,
                    TechnicalAudit.domain,
                    TechnicalAudit.source_url,
                    TechnicalAudit.pages_scanned,
                    TechnicalAudit.issue_count,
                    TechnicalAudit.truncated_issues,
                    TechnicalAudit.payload_json,
                )
                .where(TechnicalAudit.user_id == int(user_id))
                .order_by(TechnicalAudit.created_at.desc())
                .limit(max(lim * 8, 40))
            )
            .all()
        )
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in rows:
            dom = (row.domain or "").strip().lower()
            if not dom:
                dom = (row.source_url or "").strip().lower() or f"id:{row.id}"
            if dom in seen:
                continue
            seen.add(dom)
            summary: dict[str, Any] = {}
            try:
                full = json.loads(row.payload_json or "{}")
                if isinstance(full, dict):
                    summary = full.get("technical_summary") or {}
            except Exception:
                summary = {}
            out.append(
                {
                    "id": row.id,
                    "at": row.created_at.isoformat() if row.created_at else None,
                    "domain": row.domain or "",
                    "source_url": row.source_url or "",
                    "pages_scanned": row.pages_scanned,
                    "technical_summary": summary,
                    "issue_count": row.issue_count,
                    "truncated_issues": row.truncated_issues,
                }
            )
            if len(out) >= lim:
                break
        return out
    finally:
        if close:
            own.close()


def delete_audit_pg(audit_id: str, user_id: int) -> bool:
    db = SessionLocal()
    try:
        res = db.execute(
            delete(TechnicalAudit).where(
                TechnicalAudit.id == str(audit_id).strip(),
                TechnicalAudit.user_id == int(user_id),
            )
        )
        db.commit()
        return bool(res.rowcount and res.rowcount > 0)
    finally:
        db.close()


def trim_retention_pg(user_id: int, keep: int = 40) -> int:
    """Delete oldest audits beyond keep for one user. Returns deleted count."""
    use_lock = _use_sqlite_lock()
    if use_lock:
        _sqlite_write_lock.acquire()
    db = SessionLocal()
    try:
        ids = (
            db.execute(
                select(TechnicalAudit.id)
                .where(TechnicalAudit.user_id == int(user_id))
                .order_by(TechnicalAudit.created_at.desc())
            )
            .scalars()
            .all()
        )
        if len(ids) <= keep:
            return 0
        drop = ids[keep:]
        res = db.execute(
            delete(TechnicalAudit).where(
                TechnicalAudit.user_id == int(user_id),
                TechnicalAudit.id.in_(drop),
            )
        )
        db.commit()
        return int(res.rowcount or 0)
    finally:
        db.close()
        if use_lock:
            _sqlite_write_lock.release()


def count_audits_pg() -> int:
    db = SessionLocal()
    try:
        from sqlalchemy import func

        return int(db.execute(select(func.count()).select_from(TechnicalAudit)).scalar() or 0)
    finally:
        db.close()


def count_audits_pg_for_user(user_id: int) -> int:
    db = SessionLocal()
    try:
        from sqlalchemy import func

        return int(
            db.execute(
                select(func.count()).select_from(TechnicalAudit).where(TechnicalAudit.user_id == int(user_id))
            ).scalar()
            or 0
        )
    finally:
        db.close()
