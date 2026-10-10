"""WordPress site links (CAU) — org-scoped; credentials prefer publishing_sites."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.db import SessionLocal
from app.models.publishing_site import WordpressSiteLink
from app.services.publishing_sites_pg import _norm_url, site_url_normalized
from app.services.tenant_org import (
    ensure_personal_organization,
    personal_organization_id,
    resolve_organization_id,
)

import app.models.user  # noqa: F401
import app.models.organization  # noqa: F401
import app.models.plan  # noqa: F401
import app.models.subscription  # noqa: F401
import app.models.usage_limit  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.seo  # noqa: F401
import app.models.publishing_site  # noqa: F401


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(row: WordpressSiteLink) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": int(row.organization_id),
        "user_id": int(row.user_id),
        "label": row.label or row.site_url,
        "url": row.site_url,
        "username": row.username or "",
        "status": row.status or "connected",
        "connected_at": row.connected_at or "",
        "last_test_at": row.last_test_at or "",
        "last_test_message": row.last_test_message or "",
        "publishing_site_id": row.publishing_site_id or "",
    }


def _active(db: Session, *, organization_id: int, user_id: int | None = None):
    q = db.query(WordpressSiteLink).filter(
        WordpressSiteLink.organization_id == int(organization_id),
        WordpressSiteLink.deleted_at.is_(None),
    )
    if user_id is not None:
        q = q.filter(WordpressSiteLink.user_id == int(user_id))
    return q


def sync_links_from_publishing_sites(
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> int:
    """Mirror Settings publishing_sites into CAU links. No credential copy."""
    from app.services.publishing_sites_pg import list_sites_pg

    own = db or SessionLocal()
    close = db is None
    created = 0
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        pubs = list_sites_pg(
            user_id=user_id,
            organization_id=org_id,
            platform="wordpress",
            db=own,
        )
        for pub in pubs:
            pub_id = str(pub.get("id") or "").strip()
            url = _norm_url(str(pub.get("url") or ""))
            if not pub_id or not url:
                continue
            row = (
                _active(own, organization_id=org_id, user_id=user_id)
                .filter(WordpressSiteLink.publishing_site_id == pub_id)
                .first()
            )
            if row is None:
                row = (
                    _active(own, organization_id=org_id, user_id=user_id)
                    .filter(WordpressSiteLink.site_url == url)
                    .first()
                )
            if row is None:
                row = WordpressSiteLink(
                    id=str(uuid.uuid4()),
                    organization_id=int(org_id),
                    user_id=int(user_id),
                    created_by=int(user_id),
                    publishing_site_id=pub_id,
                    label=str(pub.get("name") or url)[:255] or None,
                    site_url=url,
                    username=str(pub.get("username") or "").strip() or None,
                    credential_encrypted="",
                    status="connected" if pub.get("verified") else "imported",
                    connected_at=_now(),
                )
                own.add(row)
                created += 1
            else:
                row.publishing_site_id = pub_id
                row.site_url = url
                if pub.get("username"):
                    row.username = str(pub.get("username")).strip()
                if pub.get("name"):
                    row.label = str(pub.get("name"))[:255]
                row.credential_encrypted = ""
                if row.deleted_at is not None:
                    row.deleted_at = None
        if close:
            own.commit()
        else:
            own.flush()
        return created
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def list_links_pg(
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        sync_links_from_publishing_sites(
            user_id=user_id,
            organization_id=org_id,
            db=own,
        )
        if close:
            own.commit()
        rows = _active(own, organization_id=org_id, user_id=user_id).all()
        return [_public(r) for r in rows]
    except Exception:
        if close:
            own.rollback()
        raise
    finally:
        if close:
            own.close()


def get_link_pg(
    link_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """Return link as dict (org+user scoped). Never loads by id alone."""
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        row = (
            _active(own, organization_id=org_id, user_id=user_id)
            .filter(WordpressSiteLink.id == str(link_id))
            .first()
        )
        if row is None:
            return None
        data = _public(row)
        data["app_password"] = row.credential_encrypted or ""
        data["publishing_site_id"] = row.publishing_site_id or ""
        return data
    finally:
        if close:
            own.close()


def get_credentials_pg(
    link_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
    db: Session | None = None,
) -> dict[str, str]:
    """Resolve WP credentials via org+user scoped link and optional publishing site."""
    own = db or SessionLocal()
    close = db is None
    try:
        org_id = resolve_organization_id(user_id, organization_id, db=own)
        row = (
            _active(own, organization_id=org_id, user_id=user_id)
            .filter(WordpressSiteLink.id == str(link_id))
            .first()
        )
        if row is None:
            row = (
                _active(own, organization_id=org_id, user_id=user_id)
                .filter(WordpressSiteLink.publishing_site_id == str(link_id))
                .first()
            )
        if not row:
            from app.services.publishing_sites_pg import get_site_pg

            pub = get_site_pg(
                str(link_id),
                user_id=user_id,
                organization_id=org_id,
                reveal_password=True,
                db=own,
            )
            if pub and str(pub.get("platform") or "").lower() == "wordpress":
                return {
                    "url": str(pub.get("url") or ""),
                    "username": str(pub.get("username") or "").strip(),
                    "app_password": re.sub(r"\s+", "", str(pub.get("app_password") or "").strip()),
                }
            raise LookupError("site_not_found")
        username = str(row.username or "").strip()
        pwd = decrypt_secret(str(row.credential_encrypted or "")).strip()
        url = str(row.site_url or "")
        if (not pwd or not username) and row.publishing_site_id:
            from app.models.publishing_site import PublishingSite

            pub = (
                own.query(PublishingSite)
                .filter(
                    PublishingSite.id == str(row.publishing_site_id),
                    PublishingSite.organization_id == org_id,
                    PublishingSite.user_id == int(user_id),
                    PublishingSite.deleted_at.is_(None),
                )
                .first()
            )
            if pub:
                username = username or (pub.username or "")
                p = decrypt_secret(str(pub.credential_encrypted or "")).strip()
                if p:
                    pwd = p
                url = url or (pub.site_url or "")
        return {
            "url": url,
            "username": username,
            "app_password": re.sub(r"\s+", "", pwd),
        }
    finally:
        if close:
            own.close()


def upsert_link_from_migrate(
    db: Session,
    *,
    record_id: str,
    organization_id: int,
    user_id: int,
    payload: dict[str, Any],
) -> str:
    plain = str(payload.get("app_password") or "").strip()
    if plain.startswith("enc:v1:"):
        enc = plain
    elif plain:
        enc = encrypt_secret(plain)
    else:
        enc = ""
    url = _norm_url(str(payload.get("url") or ""))
    row = db.get(WordpressSiteLink, str(record_id))
    if row is None:
        row = WordpressSiteLink(
            id=str(record_id),
            organization_id=int(organization_id),
            user_id=int(user_id),
            created_by=int(user_id),
            publishing_site_id=str(payload.get("publishing_site_id") or "") or None,
            label=str(payload.get("label") or "")[:255] or None,
            site_url=url,
            username=str(payload.get("username") or "").strip() or None,
            credential_encrypted="",  # prefer publishing_sites for secret
            status=str(payload.get("status") or "connected")[:32],
            last_test_at=str(payload.get("last_test_at") or "") or None,
            last_test_message=str(payload.get("last_test_message") or "") or None,
            connected_at=str(payload.get("connected_at") or "") or None,
            source_json_id=str(record_id),
        )
        # keep encrypted material only when no publishing_site_id
        if not row.publishing_site_id and enc:
            row.credential_encrypted = enc
        db.add(row)
        db.flush()
        return "inserted"
    if row.deleted_at is not None:
        row.deleted_at = None
    row.organization_id = int(organization_id)
    row.user_id = int(user_id)
    row.site_url = url or row.site_url
    if payload.get("publishing_site_id"):
        row.publishing_site_id = str(payload.get("publishing_site_id"))
    if payload.get("username"):
        row.username = str(payload.get("username")).strip()
    if payload.get("label"):
        row.label = str(payload.get("label"))[:255]
    if not row.publishing_site_id and enc:
        row.credential_encrypted = enc
    db.flush()
    return "updated"


def upsert_link_runtime(
    db: Session,
    *,
    user_id: int,
    organization_id: int | None = None,
    link_id: str | None = None,
    url: str,
    username: str,
    app_password: str,
    label: str = "",
    publishing_site_id: str | None = None,
    status: str = "connected",
    last_test_message: str = "",
) -> dict[str, Any]:
    if organization_id is None:
        org_id = ensure_personal_organization(db, user_id)
    else:
        org_id = resolve_organization_id(user_id, organization_id, db=db)
        if org_id == personal_organization_id(user_id):
            org_id = ensure_personal_organization(db, user_id)
    base = _norm_url(url)
    rid = str(link_id or uuid.uuid4())
    row = db.get(WordpressSiteLink, rid)
    if row is None:
        # match existing by org+url for user
        row = (
            _active(db, organization_id=org_id, user_id=user_id)
            .filter(WordpressSiteLink.site_url == base)
            .first()
        )
    if row is None:
        row = WordpressSiteLink(
            id=rid,
            organization_id=org_id,
            user_id=int(user_id),
            created_by=int(user_id),
            publishing_site_id=publishing_site_id,
            label=(label or base)[:120],
            site_url=base,
            username=username,
            credential_encrypted="",
            status=status,
            last_test_at=_now(),
            last_test_message=last_test_message or None,
            connected_at=_now(),
        )
        db.add(row)
    else:
        row.username = username
        row.label = (label or row.label or base)[:120]
        row.status = status
        row.last_test_at = _now()
        row.last_test_message = last_test_message or None
        if publishing_site_id:
            row.publishing_site_id = publishing_site_id
        if row.deleted_at is not None:
            row.deleted_at = None
    # If no publishing link, store encrypted credential
    if not row.publishing_site_id and app_password:
        plain = app_password
        if plain.startswith("enc:v1:"):
            row.credential_encrypted = plain
        else:
            row.credential_encrypted = encrypt_secret(plain)
    db.flush()
    return _public(row)
