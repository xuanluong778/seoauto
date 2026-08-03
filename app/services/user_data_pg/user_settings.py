"""PostgreSQL persistence for user_system_settings.json."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user_data_stores import UserSystemSettingsDocument
from app.services.user_data_pg.repository import loads_payload, upsert_user_singleton


def import_users_map(users: dict[int, dict[str, Any]], db: Session | None = None) -> dict[str, int]:
    own = db or SessionLocal()
    close = db is None
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    try:
        for uid, payload in users.items():
            action, _ = upsert_user_singleton(own, UserSystemSettingsDocument, user_id=int(uid), payload=payload)
            stats[action] += 1
        own.commit()
        return stats
    except Exception:
        own.rollback()
        raise
    finally:
        if close:
            own.close()


def read_user_settings(user_id: int, db: Session | None = None) -> dict[str, Any] | None:
    own = db or SessionLocal()
    try:
        row = own.query(UserSystemSettingsDocument).filter(UserSystemSettingsDocument.user_id == int(user_id)).one_or_none()
        if not row:
            return None
        return loads_payload(row.payload_json)
    finally:
        if db is None:
            own.close()
