"""Publishing sites store — PostgreSQL primary; optional dual-read JSON fallback."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.tenant_sites_flags import (
    tenant_sites_dual_read,
    tenant_sites_json_write,
    tenant_sites_pg_enabled,
)

SITES_FILE = Path("data/publishing_sites.json")
MAX_SITES = 200
PLATFORMS = {"wordpress", "shopify", "haravan", "webcake"}
ALLOWED_STATUS = {"draft", "publish"}
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_all() -> list[dict[str, Any]]:
    if not SITES_FILE.exists():
        return []
    try:
        raw = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _entry_for_disk(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    plain = str(out.get("app_password") or "")
    if plain and not plain.startswith("enc:v1:"):
        out["app_password"] = encrypt_secret(plain)
    return out


def _write_json_all(items: list[dict[str, Any]]) -> None:
    if not tenant_sites_json_write():
        return
    SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    disk = [_entry_for_disk(x) for x in items]
    SITES_FILE.write_text(json.dumps(disk, ensure_ascii=False, indent=2), encoding="utf-8")


def _norm_url(url: str) -> str:
    s = str(url or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s.rstrip("/")


def _mask_password(value: str) -> str:
    s = str(value or "")
    if not s:
        return ""
    if s.startswith("enc:v1:"):
        plain = decrypt_secret(s)
        if not plain:
            return "••••••••"
        s = plain
    if len(s) <= 4:
        return "•" * len(s)
    return "•" * max(8, len(s) - 4) + s[-4:]


from app.services.user_scope import belongs_to_user as _belongs_to_user


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    platform = str(entry.get("platform") or "wordpress").strip().lower()
    if platform not in PLATFORMS:
        platform = "wordpress"
    status = str(entry.get("default_status") or "draft").strip().lower()
    if status not in ALLOWED_STATUS:
        status = "draft"
    uid = entry.get("user_id")
    try:
        user_id = int(uid) if uid is not None else 0
    except (TypeError, ValueError):
        user_id = 0
    url = _norm_url(entry.get("url") or "")
    if platform == "shopify" and url:
        try:
            from app.services.shopify_connect import normalize_shop_url

            url = normalize_shop_url(url) or url
        except Exception:
            pass
    if platform == "webcake" and url:
        try:
            from app.services.webcake_connect import normalize_site_url

            url = normalize_site_url(url) or url
        except Exception:
            pass
    org = entry.get("organization_id")
    try:
        organization_id = int(org) if org is not None else 0
    except (TypeError, ValueError):
        organization_id = 0
    return {
        "id": str(entry.get("id") or uuid.uuid4()),
        "organization_id": organization_id or user_id,
        "user_id": user_id,
        "platform": platform,
        "name": str(entry.get("name") or "").strip(),
        "url": url,
        "username": str(entry.get("username") or "").strip(),
        "app_password": decrypt_secret(str(entry.get("app_password") or "")),
        "default_status": status,
        "verified": bool(entry.get("verified", False)),
        "plugin_installed": bool(entry.get("plugin_installed", False)),
        "favicon_url": str(entry.get("favicon_url") or "").strip(),
        "last_checked_at": str(entry.get("last_checked_at") or ""),
        "last_message": str(entry.get("last_message") or ""),
        "created_at": str(entry.get("created_at") or _now()),
        "updated_at": str(entry.get("updated_at") or _now()),
    }


def _public(entry: dict[str, Any], *, reveal_password: bool = False) -> dict[str, Any]:
    out = {**entry}
    if entry.get("platform") == "shopify":
        try:
            from app.services.shopify_connect import unpack_shopify_secrets

            data = unpack_shopify_secrets(str(entry.get("app_password") or ""))
            out["shopify_api_version"] = str(data.get("api_version") or "2025-01")
        except Exception:
            out["shopify_api_version"] = "2025-01"
    if reveal_password:
        pwd = str(entry.get("app_password") or "")
        if pwd.startswith("enc:v1:"):
            pwd = decrypt_secret(pwd)
        out["app_password"] = pwd
    else:
        out["app_password"] = ""
        out["app_password_masked"] = _mask_password(entry.get("app_password", ""))
    if not out.get("favicon_url"):
        try:
            from urllib.parse import urlparse

            host = urlparse(entry.get("url") or "").netloc or ""
            if host:
                out["favicon_url"] = f"https://www.google.com/s2/favicons?domain={host}&sz=64"
        except Exception:
            out["favicon_url"] = ""
    return out


def list_sites(
    *,
    user_id: int,
    platform: str | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    if tenant_sites_pg_enabled():
        try:
            from app.services.publishing_sites_pg import list_sites_pg

            rows = list_sites_pg(user_id=user_id, organization_id=organization_id, platform=platform)
            if rows or not tenant_sites_dual_read():
                return rows
        except Exception:
            logger.exception("publishing_sites pg list failed dual_read=%s", tenant_sites_dual_read())
            if not tenant_sites_dual_read():
                raise
    items = [_normalize(x) for x in _read_json_all() if _belongs_to_user(x, user_id)]
    if platform:
        items = [x for x in items if x["platform"] == platform]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return [_public(x) for x in items]


def get_counts(*, user_id: int, organization_id: int | None = None) -> dict[str, int]:
    items = list_sites(user_id=user_id, organization_id=organization_id)
    counts = {p: 0 for p in PLATFORMS}
    for x in items:
        counts[x["platform"]] = counts.get(x["platform"], 0) + 1
    return counts


def get_site(
    site_id: str,
    *,
    user_id: int,
    reveal_password: bool = False,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    """Requires user_id + org scope — never by site id alone."""
    sid = str(site_id or "").strip()
    if not sid or int(user_id or 0) <= 0:
        return None
    if tenant_sites_pg_enabled():
        try:
            from app.services.publishing_sites_pg import get_site_pg

            row = get_site_pg(
                sid,
                user_id=user_id,
                organization_id=organization_id,
                reveal_password=reveal_password,
            )
            if row is not None or not tenant_sites_dual_read():
                return row
        except Exception:
            logger.exception("publishing_sites pg get failed")
            if not tenant_sites_dual_read():
                raise
    for k in _read_json_all():
        if str(k.get("id") or "") == sid and _belongs_to_user(k, user_id):
            return _public(_normalize(k), reveal_password=reveal_password)
    return None


def create_site(
    payload: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
) -> dict[str, Any]:
    if tenant_sites_pg_enabled():
        from app.services.publishing_sites_pg import create_site_pg

        item = create_site_pg(payload, user_id=user_id, organization_id=organization_id)
        if tenant_sites_json_write():
            items = _read_json_all()
            items.insert(0, {**payload, "id": item["id"], "user_id": user_id})
            del items[MAX_SITES:]
            _write_json_all(items)
        return item
    # legacy json-only path (flag off)
    entry = _normalize({**payload, "id": str(uuid.uuid4()), "user_id": int(user_id)})
    if not entry["name"]:
        raise ValueError("name is required")
    if not entry["url"]:
        raise ValueError("url is required")
    if entry["platform"] == "wordpress":
        if not entry["username"] or not entry["app_password"]:
            raise ValueError("username and app_password required")
    items = _read_json_all()
    items.insert(0, entry)
    del items[MAX_SITES:]
    _write_json_all(items)
    return _public(entry)


def update_site(
    site_id: str,
    patch: dict[str, Any],
    *,
    user_id: int,
    organization_id: int | None = None,
) -> dict[str, Any] | None:
    if tenant_sites_pg_enabled():
        from app.services.publishing_sites_pg import update_site_pg

        return update_site_pg(site_id, patch, user_id=user_id, organization_id=organization_id)
    sid = str(site_id or "").strip()
    if not sid:
        return None
    items = _read_json_all()
    out: list[dict[str, Any]] = []
    found: dict[str, Any] | None = None
    for k in items:
        if str(k.get("id") or "") == sid and _belongs_to_user(k, user_id):
            merged = {**k, **{kk: vv for kk, vv in patch.items() if vv is not None}}
            merged["updated_at"] = _now()
            found = _normalize(merged)
            out.append(found)
        else:
            out.append(k)
    if not found:
        return None
    _write_json_all(out)
    return _public(found)


def delete_site(
    site_id: str,
    *,
    user_id: int,
    organization_id: int | None = None,
) -> bool:
    if tenant_sites_pg_enabled():
        from app.services.publishing_sites_pg import delete_site_pg

        return delete_site_pg(site_id, user_id=user_id, organization_id=organization_id)
    sid = str(site_id or "").strip()
    if not sid:
        return False
    items = _read_json_all()
    new_items = [k for k in items if not (str(k.get("id") or "") == sid and _belongs_to_user(k, user_id))]
    if len(new_items) == len(items):
        return False
    _write_json_all(new_items)
    return True


def _entry_domain(url: str) -> str:
    try:
        from app.services.wordpress_plugin_security import normalize_domain

        return normalize_domain(url)
    except Exception:
        return str(url or "").strip().lower()


def mark_seo_helper_installed(
    *,
    user_id: int,
    site_urls: list[str] | None = None,
    domains: set[str] | None = None,
    message: str = "Đã phát hiện SEOAuto SEO Helper (kết nối plugin).",
    organization_id: int | None = None,
) -> int:
    want: set[str] = set()
    for d in domains or set():
        nd = _entry_domain(str(d))
        if nd:
            want.add(nd)
    for u in site_urls or []:
        nd = _entry_domain(str(u))
        if nd:
            want.add(nd)
    if not want:
        return 0

    if tenant_sites_pg_enabled():
        from app.db import SessionLocal
        from app.models.publishing_site import PublishingSite
        from app.services.tenant_org import resolve_organization_id

        db = SessionLocal()
        try:
            org_id = resolve_organization_id(user_id, organization_id, db=db)
            rows = (
                db.query(PublishingSite)
                .filter(
                    PublishingSite.organization_id == org_id,
                    PublishingSite.user_id == int(user_id),
                    PublishingSite.deleted_at.is_(None),
                    PublishingSite.platform == "wordpress",
                )
                .all()
            )
            changed = 0
            stamp = _now()
            for row in rows:
                domain = _entry_domain(str(row.site_url or ""))
                if not domain or domain not in want:
                    continue
                if row.plugin_installed and row.verified:
                    continue
                row.plugin_installed = True
                row.verified = True
                row.last_checked_at = stamp
                row.last_message = message
                changed += 1
            if changed:
                db.commit()
            return changed
        finally:
            db.close()

    # JSON fallback
    items = _read_json_all()
    changed = 0
    out: list[dict[str, Any]] = []
    stamp = _now()
    for raw in items:
        entry = dict(raw)
        if not _belongs_to_user(entry, user_id):
            out.append(entry)
            continue
        platform = str(entry.get("platform") or "wordpress").strip().lower()
        if platform != "wordpress":
            out.append(entry)
            continue
        domain = _entry_domain(str(entry.get("url") or ""))
        if not domain or domain not in want:
            out.append(entry)
            continue
        if bool(entry.get("plugin_installed")) and bool(entry.get("verified")):
            out.append(entry)
            continue
        entry["plugin_installed"] = True
        entry["verified"] = True
        entry["last_checked_at"] = stamp
        entry["last_message"] = message
        entry["updated_at"] = stamp
        changed += 1
        out.append(entry)
    if changed:
        _write_json_all(out)
    return changed
