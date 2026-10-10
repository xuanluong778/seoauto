"""PostgreSQL repository for publishing_sites — always org-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.db import SessionLocal
from app.models.publishing_site import PublishingSite
from app.services.tenant_org import (
    ensure_personal_organization,
    personal_organization_id,
    resolve_organization_id,
)

# Ensure relationship mappers resolve when repo used outside FastAPI boot
import app.models.user  # noqa: F401  # must load before knowledge/seo FKs
import app.models.organization  # noqa: F401
import app.models.plan  # noqa: F401
import app.models.subscription  # noqa: F401
import app.models.usage_limit  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.seo  # noqa: F401

PLATFORMS = {"wordpress", "shopify", "haravan", "webcake"}
ALLOWED_STATUS = {"draft", "publish"}
MAX_SITES = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_url(url: str) -> str:
    s = str(url or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s.rstrip("/")


def site_url_normalized(url: str) -> str:
    s = _norm_url(url).lower()
    try:
        p = urlparse(s)
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").rstrip("/")
        return f"{host}{path}"
    except Exception:
        return s


def _mask_password(value: str) -> str:
    s = str(value or "")
    if not s:
        return ""
    if s.startswith("enc:v1:"):
        plain = decrypt_secret(s)
        if not plain:
            # Ciphertext present but app key mismatch — still show stored, no secret leak
            return "••••••••"
        s = plain
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * max(8, len(s) - 4) + s[-4:]


def _row_to_entry(row: PublishingSite, *, plain_secret: bool = False) -> dict[str, Any]:
    secret = str(row.credential_encrypted or "")
    if plain_secret:
        secret = decrypt_secret(secret)
    return {
        "id": row.id,
        "organization_id": int(row.organization_id),
        "user_id": int(row.user_id),
        "created_by": int(row.created_by) if row.created_by else int(row.user_id),
        "platform": row.platform,
        "name": row.name or "",
        "url": row.site_url or "",
        "username": row.username or "",
        "app_password": secret if plain_secret else "",
        "default_status": row.default_status or "draft",
        "verified": bool(row.verified),
        "plugin_installed": bool(row.plugin_installed),
        "favicon_url": row.favicon_url or "",
        "last_checked_at": row.last_checked_at or "",
        "last_message": row.last_message or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _public(entry: dict[str, Any], *, reveal_password: bool = False) -> dict[str, Any]:
    out = {**entry}
    if reveal_password:
        pwd = str(entry.get("app_password") or "")
        if pwd.startswith("enc:v1:"):
            pwd = decrypt_secret(pwd)
        out["app_password"] = pwd
    else:
        masked_src = entry.get("_raw_credential") or entry.get("app_password") or ""
        out["app_password"] = ""
        out["app_password_masked"] = _mask_password(str(masked_src))
    if not out.get("favicon_url"):
        host = urlparse(entry.get("url") or "").netloc or ""
        if host:
            out["favicon_url"] = f"https://www.google.com/s2/favicons?domain={host}&sz=64"
    out.pop("_raw_credential", None)
    return out


def _active_q(db: Session, *, organization_id: int, user_id: int | None = None):
    q = db.query(PublishingSite).filter(
        PublishingSite.organization_id == int(organization_id),
        PublishingSite.deleted_at.is_(None),
    )
    if user_id is not None:
        q = q.filter(PublishingSite.user_id == int(user_id))
    return q


def list_sites_pg(
    *,
    user_id: int,
    organization_id: int | None = None,
    platform: str | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        q = _active_q(own, organization_id=org_id, user_id=user_id)
        if platform:
            q = q.filter(PublishingSite.platform == str(platform).lower())
        rows = q.order_by(PublishingSite.created_at.desc()).all()
        out = []
        for r in rows:
            entry = _row_to_entry(r, plain_secret=False)
            entry["_raw_credential"] = r.credential_encrypted
            out.append(_public(entry, reveal_password=False))
        return out
    finally:
        if close:
            own.close()


def get_site_pg(
    site_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    reveal_password: bool = False,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """Fetch by id **and** organization_id (+ owner). Id alone is insufficient."""
    sid = str(site_id or "").strip()
    if not sid:
        return None
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        row = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(PublishingSite.id == sid)
            .first()
        )
        if not row:
            return None
        entry = _row_to_entry(row, plain_secret=reveal_password)
        if not reveal_password:
            entry["_raw_credential"] = row.credential_encrypted
        return _public(entry, reveal_password=reveal_password)
    finally:
        if close:
            own.close()


def create_site_pg(
    payload: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    own = db or SessionLocal()
    close = db is None
    try:
        # Never trust client organization_id; membership checked inside resolve.
        if organization_id is None:
            org_id = ensure_personal_organization(own, user_id)
        else:
            org_id = resolve_organization_id(user_id, organization_id, db=own)
            if org_id == personal_organization_id(user_id):
                org_id = ensure_personal_organization(own, user_id)

        count = _active_q(own, organization_id=org_id, user_id=user_id).count()
        if count >= MAX_SITES:
            raise ValueError(f"Tối đa {MAX_SITES} sites.")

        platform = str(payload.get("platform") or "wordpress").strip().lower()
        if platform not in PLATFORMS:
            platform = "wordpress"
        status = str(payload.get("default_status") or "draft").strip().lower()
        if status not in ALLOWED_STATUS:
            status = "draft"
        url = _norm_url(str(payload.get("url") or ""))
        name = str(payload.get("name") or "").strip()
        username = str(payload.get("username") or "").strip()
        plain = str(payload.get("app_password") or "").strip()
        if plain.startswith("enc:v1:"):
            plain = decrypt_secret(plain)
        if not name:
            raise ValueError("name is required")
        if not url:
            raise ValueError("url is required")
        if platform == "wordpress" and (not username or not plain):
            raise ValueError("username and app_password required for wordpress")

        host = site_url_normalized(url)
        existing = (
            _active_q(own, organization_id=org_id)
            .filter(
                PublishingSite.platform == platform,
                PublishingSite.site_url_normalized == host,
            )
            .first()
        )
        if existing:
            raise ValueError("site already exists for this organization")

        row = PublishingSite(
            id=str(payload.get("id") or uuid.uuid4()),
            organization_id=org_id,
            user_id=int(user_id),
            created_by=int(user_id),
            platform=platform,
            name=name,
            site_url=url,
            site_url_normalized=host,
            username=username or None,
            credential_encrypted=encrypt_secret(plain) if plain else "",
            default_status=status,
            verified=bool(payload.get("verified", False)),
            plugin_installed=bool(payload.get("plugin_installed", False)),
            favicon_url=str(payload.get("favicon_url") or "") or None,
            last_checked_at=str(payload.get("last_checked_at") or "") or None,
            last_message=str(payload.get("last_message") or "") or None,
            source_json_id=str(payload.get("id") or "") or None,
        )
        own.add(row)
        if close:
            own.commit()
            own.refresh(row)
        else:
            own.flush()
        entry = _row_to_entry(row, plain_secret=False)
        entry["_raw_credential"] = row.credential_encrypted
        return _public(entry, reveal_password=False)
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def update_site_pg(
    site_id: str,
    patch: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        row = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(PublishingSite.id == str(site_id))
            .first()
        )
        if not row:
            return None
        if patch.get("name") is not None:
            row.name = str(patch["name"]).strip()
        if patch.get("url") is not None:
            url = _norm_url(str(patch["url"]))
            row.site_url = url
            row.site_url_normalized = site_url_normalized(url)
        if patch.get("username") is not None:
            row.username = str(patch["username"]).strip() or None
        if patch.get("app_password") is not None:
            plain = str(patch["app_password"] or "").strip()
            if plain:
                if plain.startswith("enc:v1:"):
                    plain = decrypt_secret(plain)
                row.credential_encrypted = encrypt_secret(plain)
        if patch.get("default_status") is not None:
            st = str(patch["default_status"]).strip().lower()
            if st in ALLOWED_STATUS:
                row.default_status = st
        if patch.get("verified") is not None:
            row.verified = bool(patch["verified"])
        if patch.get("plugin_installed") is not None:
            row.plugin_installed = bool(patch["plugin_installed"])
        if patch.get("favicon_url") is not None:
            row.favicon_url = str(patch["favicon_url"] or "") or None
        if patch.get("last_checked_at") is not None:
            row.last_checked_at = str(patch["last_checked_at"] or "") or None
        if patch.get("last_message") is not None:
            row.last_message = str(patch["last_message"] or "") or None
        row.updated_at = datetime.now(timezone.utc)
        if close:
            own.commit()
            own.refresh(row)
        else:
            own.flush()
        entry = _row_to_entry(row, plain_secret=False)
        entry["_raw_credential"] = row.credential_encrypted
        return _public(entry, reveal_password=False)
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def delete_site_pg(
    site_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> bool:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        row = (
            _active_q(own, organization_id=org_id, user_id=user_id)
            .filter(PublishingSite.id == str(site_id))
            .first()
        )
        if not row:
            return False
        row.deleted_at = datetime.now(timezone.utc)
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


def count_sites_pg(*, organization_id: int | None = None, db: Session | None = None) -> int:
    own = db or SessionLocal()
    close = db is None
    try:
        q = own.query(PublishingSite).filter(PublishingSite.deleted_at.is_(None))
        if organization_id is not None:
            q = q.filter(PublishingSite.organization_id == int(organization_id))
        return int(q.count())
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
    """Idempotent insert/update by primary id. Returns inserted|updated|skipped."""
    url = _norm_url(str(payload.get("url") or ""))
    platform = str(payload.get("platform") or "wordpress").strip().lower()
    if platform not in PLATFORMS:
        platform = "wordpress"
    plain = str(payload.get("app_password") or "").strip()
    if plain.startswith("enc:v1:"):
        enc = plain  # already application-encrypted
    elif plain:
        enc = encrypt_secret(plain)
    else:
        enc = ""

    row = db.get(PublishingSite, str(record_id))
    host = site_url_normalized(url)
    if row is None:
        row = PublishingSite(
            id=str(record_id),
            organization_id=int(organization_id),
            user_id=int(user_id),
            created_by=int(user_id),
            platform=platform,
            name=str(payload.get("name") or "").strip() or host,
            site_url=url,
            site_url_normalized=host,
            username=str(payload.get("username") or "").strip() or None,
            credential_encrypted=enc,
            default_status=str(payload.get("default_status") or "draft")[:16],
            verified=bool(payload.get("verified", False)),
            plugin_installed=bool(payload.get("plugin_installed", False)),
            favicon_url=str(payload.get("favicon_url") or "") or None,
            last_checked_at=str(payload.get("last_checked_at") or "") or None,
            last_message=str(payload.get("last_message") or "") or None,
            source_json_id=str(record_id),
        )
        db.add(row)
        db.flush()
        return "inserted"
    # update if not soft-deleted
    if row.deleted_at is not None:
        row.deleted_at = None
    row.organization_id = int(organization_id)
    row.user_id = int(user_id)
    row.platform = platform
    row.name = str(payload.get("name") or row.name or "").strip() or host
    row.site_url = url or row.site_url
    row.site_url_normalized = host or row.site_url_normalized
    if str(payload.get("username") or "").strip():
        row.username = str(payload.get("username")).strip()
    if enc:
        row.credential_encrypted = enc
    row.verified = bool(payload.get("verified", row.verified))
    row.plugin_installed = bool(payload.get("plugin_installed", row.plugin_installed))
    row.source_json_id = str(record_id)
    db.flush()
    return "updated"
