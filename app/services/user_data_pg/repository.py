"""Shared helpers for user-data PostgreSQL repositories."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def payload_checksum(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def dumps_payload(entry: dict[str, Any]) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def loads_payload(raw: str) -> dict[str, Any]:
    data = json.loads(raw or "{}")
    return data if isinstance(data, dict) else {}


def entry_user_id(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def entry_record_id(entry: dict[str, Any], *, fallback_key: str = "id") -> str:
    return str(entry.get(fallback_key) or entry.get("record_id") or "").strip()


def is_legacy_orphan(entry: dict[str, Any]) -> bool:
    return bool(entry.get("legacy_orphan"))


def row_to_entry(row: Any) -> dict[str, Any]:
    return loads_payload(getattr(row, "payload_json", "{}"))


def upsert_document(
    db: Session,
    model: type[T],
    *,
    record_id: str,
    entry: dict[str, Any],
    extra_fields: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """
    Insert or skip if checksum unchanged. Returns (action, changed).
    action: inserted | updated | skipped
    """
    from app.services.user_data_pg.bootstrap import bootstrap_orm_models

    bootstrap_orm_models()
    rid = str(record_id or "").strip()
    if not rid:
        return "skipped", False
    checksum = payload_checksum(entry)
    existing = db.query(model).filter(getattr(model, "record_id") == rid).one_or_none()  # type: ignore[attr-defined]
    uid = entry_user_id(entry)
    created = parse_dt(entry.get("created_at")) or utc_now()
    updated = parse_dt(entry.get("updated_at")) or created
    org_id = entry.get("organization_id")
    try:
        org_val = int(org_id) if org_id is not None else None
    except (TypeError, ValueError):
        org_val = None

    if existing is not None:
        if getattr(existing, "import_checksum", None) == checksum:
            return "skipped", False
        existing.user_id = uid  # type: ignore[attr-defined]
        existing.organization_id = org_val  # type: ignore[attr-defined]
        existing.legacy_orphan = is_legacy_orphan(entry)  # type: ignore[attr-defined]
        existing.created_at = parse_dt(entry.get("created_at")) or existing.created_at  # type: ignore[attr-defined]
        existing.updated_at = updated  # type: ignore[attr-defined]
        existing.payload_json = dumps_payload(entry)  # type: ignore[attr-defined]
        existing.import_checksum = checksum  # type: ignore[attr-defined]
        if extra_fields:
            for k, v in extra_fields.items():
                setattr(existing, k, v)
        return "updated", True

    row_kwargs: dict[str, Any] = {
        "record_id": rid,
        "user_id": uid,
        "organization_id": org_val,
        "legacy_orphan": is_legacy_orphan(entry),
        "created_at": created,
        "updated_at": updated,
        "payload_json": dumps_payload(entry),
        "import_source": "json_file",
        "import_checksum": checksum,
    }
    if extra_fields:
        row_kwargs.update(extra_fields)
    db.add(model(**row_kwargs))  # type: ignore[call-arg, misc]
    return "inserted", True


def upsert_user_singleton(
    db: Session,
    model: type[T],
    *,
    user_id: int,
    payload: dict[str, Any],
) -> tuple[str, bool]:
    from app.services.user_data_pg.bootstrap import bootstrap_orm_models

    bootstrap_orm_models()
    checksum = payload_checksum(payload)
    existing = db.query(model).filter(getattr(model, "user_id") == int(user_id)).one_or_none()  # type: ignore[attr-defined]
    now = utc_now()
    org_id = payload.get("organization_id")
    try:
        org_val = int(org_id) if org_id is not None else None
    except (TypeError, ValueError):
        org_val = None
    if existing is not None:
        if getattr(existing, "import_checksum", None) == checksum:
            return "skipped", False
        existing.payload_json = dumps_payload(payload)  # type: ignore[attr-defined]
        existing.import_checksum = checksum  # type: ignore[attr-defined]
        existing.organization_id = org_val  # type: ignore[attr-defined]
        existing.updated_at = now  # type: ignore[attr-defined]
        return "updated", True
    db.add(
        model(  # type: ignore[call-arg, misc]
            user_id=int(user_id),
            organization_id=org_val,
            created_at=now,
            updated_at=now,
            payload_json=dumps_payload(payload),
            import_source="json_file",
            import_checksum=checksum,
        )
    )
    return "inserted", True
