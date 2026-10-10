"""PostgreSQL repository for Content AI projects — always org-scoped."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session, defer

from app.db import SessionLocal
from app.models.content_ai_project import ContentAiProject
from app.services.tenant_org import ensure_personal_organization, resolve_organization_id

import app.models.user  # noqa: F401
import app.models.organization  # noqa: F401
import app.models.plan  # noqa: F401
import app.models.subscription  # noqa: F401
import app.models.usage_limit  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.seo  # noqa: F401

_LOG = logging.getLogger(__name__)
_WRITE_LOCK = threading.RLock()

# Never persist secrets in project payloads
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|token|credential|authorization|bearer|private[_-]?key)",
    re.I,
)

_PAYLOAD_TOP_LEVEL = {
    "title",
    "slug",
    "target_website",
    "primary_keyword",
    "secondary_keywords",
    "outline_content",
    "meta_description",
    "tags",
    "content",
    "featured_image",
    "gallery_images",
    "scheduled_at",
    "custom_title",
    "custom_description",
    "custom_outline",
    "search_volume",
    "content_type",
    "competitor_url",
    "target_word_count",
    "wp_category_id",
    "wp_category_name",
    "wp_site_id",
    "wp_publish_status",
    "wp_post_url",
    "draft_output",
    "origin",
    "seo_score",
    "seo_issues",
    "seo_status",
    "seo_issue_count",
    "actual_word_count",
    "image_assets",
    "status",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


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


def strip_secrets(value: Any) -> Any:
    """Recursively drop secret-like keys from project JSON."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                continue
            out[str(k)] = strip_secrets(v)
        return out
    if isinstance(value, list):
        return [strip_secrets(x) for x in value]
    return value


def sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return strip_secrets(dict(entry)) if isinstance(entry, dict) else {}


def norm_url_host(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    try:
        parsed = urlparse(u)
        host = (parsed.netloc or parsed.path or "").strip().lower()
    except Exception:
        host = u.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip("/")


def norm_keyword(pk: str) -> str:
    return re.sub(r"\s+", " ", str(pk or "").strip()).lower()


def entry_checksum(entry: dict[str, Any]) -> str:
    safe = sanitize_entry(entry)
    # stable identity: exclude volatile runtime-only keys if any
    blob = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _payload_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    safe = sanitize_entry(entry)
    # keep full project document minus ids/ownership stored as columns
    out = {k: v for k, v in safe.items() if k not in {"id", "user_id", "organization_id", "created_by", "legacy_orphan"}}
    return out


def row_to_list_entry(row: ContentAiProject) -> dict[str, Any]:
    """Lightweight list projection — avoids loading full content/payload_json bodies."""
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    outline = str(payload.get("outline_content") or "")
    thumb = str(payload.get("featured_image") or "")
    actual_word_count = int(payload.get("actual_word_count") or 0)
    content = ""
    draft = payload.get("draft_output")
    if isinstance(draft, dict) and not actual_word_count:
        content = str(draft.get("content") or "")
    return {
        "id": row.id,
        "organization_id": int(row.organization_id),
        "user_id": int(row.user_id),
        "created_by": int(row.created_by) if row.created_by else int(row.user_id),
        "title": row.title or str(payload.get("title") or ""),
        "slug": row.slug if row.slug is not None else str(payload.get("slug") or ""),
        "target_website": row.target_website or str(payload.get("target_website") or ""),
        "primary_keyword": row.primary_keyword or str(payload.get("primary_keyword") or ""),
        "outline_content": outline,
        "featured_image": thumb,
        "content": content,
        "actual_word_count": actual_word_count,
        "origin": row.origin or str(payload.get("origin") or ""),
        "status": row.status or str(payload.get("status") or "draft"),
        "created_at": _iso(row.created_at) or str(payload.get("created_at") or ""),
        "updated_at": _iso(row.updated_at),
        "legacy_orphan": bool(row.legacy_orphan),
        "wp_publish_status": str(payload.get("wp_publish_status") or ""),
        "seo_score": payload.get("seo_score"),
        "seo_issues": payload.get("seo_issues") if isinstance(payload.get("seo_issues"), list) else [],
        "seo_status": str(payload.get("seo_status") or ""),
        "seo_issue_count": int(payload.get("seo_issue_count") or 0)
        if payload.get("seo_issue_count") is not None
        else (len(payload.get("seo_issues") or []) if isinstance(payload.get("seo_issues"), list) else 0),
    }


def row_to_entry(row: ContentAiProject) -> dict[str, Any]:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload = sanitize_entry(payload)
    # Column values win for core fields
    entry: dict[str, Any] = {
        **payload,
        "id": row.id,
        "organization_id": int(row.organization_id),
        "user_id": int(row.user_id),
        "created_by": int(row.created_by) if row.created_by else int(row.user_id),
        "title": row.title or payload.get("title") or "",
        "slug": row.slug if row.slug is not None else payload.get("slug") or "",
        "target_website": row.target_website or payload.get("target_website") or "",
        "primary_keyword": row.primary_keyword or payload.get("primary_keyword") or "",
        "content": row.content if row.content is not None else str(payload.get("content") or ""),
        "origin": row.origin or payload.get("origin") or "",
        "status": row.status or payload.get("status") or "draft",
        "created_at": _iso(row.created_at) or str(payload.get("created_at") or ""),
        "updated_at": _iso(row.updated_at),
        "legacy_orphan": bool(row.legacy_orphan),
    }
    return entry


def _apply_entry_to_row(row: ContentAiProject, entry: dict[str, Any], *, organization_id: int, user_id: int) -> None:
    safe = sanitize_entry(entry)
    title = str(safe.get("title") or "")[:500]
    site = str(safe.get("target_website") or "")
    pk = str(safe.get("primary_keyword") or "")
    content = str(safe.get("content") or "")
    draft = safe.get("draft_output")
    if not content and isinstance(draft, dict):
        content = str(draft.get("content") or "")

    row.organization_id = int(organization_id)
    row.user_id = int(user_id)
    if row.created_by is None:
        row.created_by = int(user_id)
    row.title = title
    row.slug = str(safe.get("slug") or "")[:500] or None
    row.target_website = site[:2000] if site else None
    row.target_website_norm = norm_url_host(site)[:255]
    row.primary_keyword = pk[:500] if pk else None
    row.primary_keyword_norm = norm_keyword(pk)[:500]
    row.origin = str(safe.get("origin") or "")[:64] or None
    row.status = str(safe.get("status") or row.status or "draft")[:32]
    row.content = content
    row.legacy_orphan = bool(safe.get("legacy_orphan"))
    row.payload_json = json.dumps(_payload_from_entry(safe), ensure_ascii=False, separators=(",", ":"), default=str)
    row.import_checksum = entry_checksum(safe)
    row.source_json_id = str(safe.get("id") or row.id)[:64]
    created = parse_dt(safe.get("created_at"))
    if created and row.created_at is None:
        row.created_at = created
    elif created and getattr(row, "_sa_instance_state", None):
        # only set on insert path typically
        pass
    row.updated_at = _now()


def _active_q(db: Session, *, organization_id: int, user_id: int | None = None):
    q = db.query(ContentAiProject).filter(
        ContentAiProject.organization_id == int(organization_id),
        ContentAiProject.deleted_at.is_(None),
        ContentAiProject.legacy_orphan.is_(False),
    )
    if user_id is not None:
        q = q.filter(ContentAiProject.user_id == int(user_id))
    return q


def list_entries_pg(
    *,
    user_id: int,
    organization_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    db: Session | None = None,
    list_only: bool = False,
) -> list[dict[str, Any]]:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        q = _active_q(own, organization_id=org_id, user_id=user_id)
        if list_only:
            q = q.options(defer(ContentAiProject.content))
        else:
            q = q.options(defer(ContentAiProject.payload_json))
        q = q.order_by(ContentAiProject.created_at.desc())
        if offset:
            q = q.offset(max(0, int(offset)))
        if limit is not None:
            q = q.limit(max(1, int(limit)))
        mapper = row_to_list_entry if list_only else row_to_entry
        return [mapper(r) for r in q.all()]
    finally:
        if close:
            own.close()


def count_entries_pg(
    *,
    user_id: int | None = None,
    organization_id: int | None = None,
    db: Session | None = None,
) -> int:
    own = db or SessionLocal()
    close = db is None
    try:
        q = own.query(ContentAiProject).filter(ContentAiProject.deleted_at.is_(None))
        if organization_id is not None:
            q = q.filter(ContentAiProject.organization_id == int(organization_id))
        if user_id is not None:
            q = q.filter(ContentAiProject.user_id == int(user_id))
        return int(q.count())
    finally:
        if close:
            own.close()


def get_entry_pg(
    project_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
    for_update: bool = False,
) -> dict[str, Any] | None:
    """Fetch by id AND org (+ owner). Id alone is never enough."""
    sid = str(project_id or "").strip()
    if not sid or int(user_id or 0) <= 0:
        return None
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        q = _active_q(own, organization_id=org_id, user_id=user_id).filter(ContentAiProject.id == sid)
        if for_update:
            q = q.with_for_update()
        row = q.first()
        return row_to_entry(row) if row else None
    finally:
        if close:
            own.close()


def get_entries_by_ids_pg(
    project_ids: list[str],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, dict[str, Any]]:
    want = {str(x).strip() for x in (project_ids or []) if str(x).strip()}
    if not want:
        return {}
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        rows = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(ContentAiProject.id.in_(list(want)))
            .all()
        )
        return {r.id: row_to_entry(r) for r in rows}
    finally:
        if close:
            own.close()


def insert_entry_pg(
    entry: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    with _WRITE_LOCK:
        own = db or SessionLocal()
        close = db is None
        try:
            org_id = organization_id
            if org_id is None:
                org_id = ensure_personal_organization(own, int(user_id))
            else:
                org_id = resolve_organization_id(user_id, org_id)
                ensure_personal_organization(own, int(user_id))
            rid = str(entry.get("id") or uuid.uuid4())
            safe = sanitize_entry(entry)
            safe["id"] = rid
            safe["user_id"] = int(user_id)
            safe["organization_id"] = int(org_id)
            row = ContentAiProject(id=rid, organization_id=int(org_id), user_id=int(user_id), created_by=int(user_id))
            created = parse_dt(safe.get("created_at")) or _now()
            row.created_at = created
            _apply_entry_to_row(row, safe, organization_id=int(org_id), user_id=int(user_id))
            own.add(row)
            if close:
                own.commit()
            else:
                own.flush()
            return row_to_entry(row)
        except Exception:
            if close:
                own.rollback()
            raise
        finally:
            if close:
                own.close()

def update_entry_pg(
    project_id: str,
    fields: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    with _WRITE_LOCK:
        own = db or SessionLocal()
        close = db is None
        try:
            org_id = resolve_organization_id(user_id, organization_id)
            q = _active_q(own, organization_id=org_id, user_id=user_id).filter(
                ContentAiProject.id == str(project_id)
            )
            try:
                if own.get_bind().dialect.name != "sqlite":
                    q = q.with_for_update()
            except Exception:
                pass
            row = q.first()
            if not row:
                return None
            entry = row_to_entry(row)
            for k, v in (fields or {}).items():
                if k in {"id", "user_id", "organization_id", "created_by"}:
                    continue
                entry[k] = v
            # mirror into draft_output as store does
            draft = entry.get("draft_output")
            if isinstance(draft, dict):
                draft = dict(draft)
                for k, v in (fields or {}).items():
                    if k not in {"id", "user_id", "organization_id", "created_by"}:
                        draft[k] = v
                entry["draft_output"] = draft
            _apply_entry_to_row(row, entry, organization_id=org_id, user_id=user_id)
            if close:
                own.commit()
            else:
                own.flush()
            return row_to_entry(row)
        except Exception:
            if close:
                own.rollback()
            raise
        finally:
            if close:
                own.close()

def replace_entry_pg(
    entry: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """Insert or full-replace by id within org."""
    with _WRITE_LOCK:
        return _replace_entry_pg_locked(
            entry,
            user_id=user_id,
            organization_id=organization_id,
            db=db,
        )


def _replace_entry_pg_locked(
    entry: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = organization_id
        if org_id is None:
            org_id = ensure_personal_organization(own, int(user_id))
        else:
            ensure_personal_organization(own, int(user_id))
            org_id = int(org_id)
        rid = str(entry.get("id") or uuid.uuid4())
        safe = sanitize_entry(entry)
        safe["id"] = rid
        safe["user_id"] = int(user_id)
        safe["organization_id"] = int(org_id)
        row = (
            own.query(ContentAiProject)
            .filter(
                ContentAiProject.id == rid,
                ContentAiProject.organization_id == int(org_id),
            )
            .first()
        )
        dialect = ""
        try:
            dialect = own.get_bind().dialect.name
        except Exception:
            dialect = ""
        if dialect and dialect != "sqlite":
            row = (
                own.query(ContentAiProject)
                .filter(
                    ContentAiProject.id == rid,
                    ContentAiProject.organization_id == int(org_id),
                )
                .with_for_update()
                .first()
            )
        if row is None:
            row = ContentAiProject(id=rid, organization_id=int(org_id), user_id=int(user_id), created_by=int(user_id))
            row.created_at = parse_dt(safe.get("created_at")) or _now()
            own.add(row)
        row.deleted_at = None
        _apply_entry_to_row(row, safe, organization_id=int(org_id), user_id=int(user_id))
        if close:
            own.commit()
        else:
            own.flush()
        return row_to_entry(row)
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def delete_entry_pg(
    project_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> bool:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        row = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(ContentAiProject.id == str(project_id))
            .first()
        )
        if not row:
            return False
        row.deleted_at = _now()
        if close:
            own.commit()
        else:
            own.flush()
        return True
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def trim_retention_pg(
    *,
    user_id: int,
    max_projects: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> int:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        rows = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .order_by(ContentAiProject.created_at.desc())
            .all()
        )
        if len(rows) <= max_projects:
            return 0
        dropped = 0
        for row in rows[max_projects:]:
            row.deleted_at = _now()
            dropped += 1
        if close:
            own.commit()
        else:
            own.flush()
        return dropped
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def find_by_site_keyword_pg(
    *,
    user_id: int,
    target_website: str,
    primary_keyword: str,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    site = norm_url_host(target_website)
    pk = norm_keyword(primary_keyword)
    if not site or not pk:
        return None
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id)
        row = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(
                ContentAiProject.target_website_norm == site,
                ContentAiProject.primary_keyword_norm == pk,
            )
            .order_by(ContentAiProject.created_at.desc())
            .first()
        )
        return row_to_entry(row) if row else None
    finally:
        if close:
            own.close()


def upsert_from_migrate(
    db: Session,
    *,
    record_id: str,
    organization_id: int,
    user_id: int,
    payload: dict[str, Any],
) -> str:
    """Idempotent migrate upsert by primary id. Returns inserted|updated|skipped."""
    rid = str(record_id or "").strip()
    if not rid:
        return "skipped"
    safe = sanitize_entry(payload)
    safe["id"] = rid
    safe["user_id"] = int(user_id)
    safe["organization_id"] = int(organization_id)
    checksum = entry_checksum(safe)
    row = db.get(ContentAiProject, rid)
    if row is not None:
        if row.import_checksum == checksum and row.organization_id == int(organization_id):
            return "skipped"
        row.deleted_at = None
        _apply_entry_to_row(row, safe, organization_id=int(organization_id), user_id=int(user_id))
        if not row.created_at:
            row.created_at = parse_dt(safe.get("created_at")) or _now()
        return "updated"
    row = ContentAiProject(
        id=rid,
        organization_id=int(organization_id),
        user_id=int(user_id),
        created_by=int(user_id),
    )
    row.created_at = parse_dt(safe.get("created_at")) or _now()
    _apply_entry_to_row(row, safe, organization_id=int(organization_id), user_id=int(user_id))
    db.add(row)
    db.flush()
    return "inserted"


def list_all_active_ids(db: Session | None = None) -> list[str]:
    own = db or SessionLocal()
    close = db is None
    try:
        rows = (
            own.query(ContentAiProject.id)
            .filter(ContentAiProject.deleted_at.is_(None))
            .all()
        )
        return [r[0] for r in rows]
    finally:
        if close:
            own.close()
