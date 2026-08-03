"""PostgreSQL persistence for content_ai_projects.json documents."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user_data_stores import ContentAiProjectDocument
from app.services.user_data_pg.repository import entry_record_id, row_to_entry, upsert_document


def count_rows(db: Session | None = None) -> int:
    from app.services.user_data_pg.bootstrap import bootstrap_orm_models

    bootstrap_orm_models()
    own = db or SessionLocal()
    try:
        return own.query(ContentAiProjectDocument).count()
    finally:
        if db is None:
            own.close()


def list_all_entries(db: Session | None = None) -> list[dict[str, Any]]:
    from app.services.user_data_pg.bootstrap import bootstrap_orm_models

    bootstrap_orm_models()
    own = db or SessionLocal()
    try:
        rows = own.query(ContentAiProjectDocument).order_by(ContentAiProjectDocument.updated_at.desc()).all()
        return [row_to_entry(r) for r in rows]
    finally:
        if db is None:
            own.close()


def replace_all_entries(entries: list[dict[str, Any]], db: Session | None = None) -> None:
    """Full sync used by dual-write (does not delete JSON file)."""
    own = db or SessionLocal()
    close = db is None
    try:
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rid = entry_record_id(entry)
            if not rid:
                continue
            seen.add(rid)
            upsert_document(own, ContentAiProjectDocument, record_id=rid, entry=entry)
        own.commit()
    except Exception:
        own.rollback()
        raise
    finally:
        if close:
            own.close()


def import_entries(entries: list[dict[str, Any]], db: Session | None = None) -> dict[str, int]:
    own = db or SessionLocal()
    close = db is None
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "invalid": 0}
    try:
        for entry in entries:
            if not isinstance(entry, dict):
                stats["invalid"] += 1
                continue
            rid = entry_record_id(entry)
            if not rid:
                stats["invalid"] += 1
                continue
            action, _ = upsert_document(own, ContentAiProjectDocument, record_id=rid, entry=entry)
            stats[action] += 1
        own.commit()
        return stats
    except Exception:
        own.rollback()
        raise
    finally:
        if close:
            own.close()
