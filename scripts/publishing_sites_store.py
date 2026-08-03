from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.secrets_crypto import decrypt_secret, encrypt_secret

SITES_FILE = Path("data/publishing_sites.json")
MAX_SITES = 200

PLATFORMS = {"wordpress", "shopify", "haravan", "webcake"}
ALLOWED_STATUS = {"draft", "publish"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_all() -> list[dict[str, Any]]:
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
    if plain:
        out["app_password"] = encrypt_secret(plain)
    return out


def _write_all(items: list[dict[str, Any]]) -> None:
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
    return {
        "id": str(entry.get("id") or uuid.uuid4()),
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
        out["app_password"] = entry.get("app_password", "")
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


def list_sites(*, user_id: int, platform: str | None = None) -> list[dict[str, Any]]:
    items = [_normalize(x) for x in _read_all() if _belongs_to_user(x, user_id)]
    if platform:
        items = [x for x in items if x["platform"] == platform]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return [_public(x) for x in items]


def get_counts(*, user_id: int) -> dict[str, int]:
    items = [_normalize(x) for x in _read_all() if _belongs_to_user(x, user_id)]
    counts = {p: 0 for p in PLATFORMS}
    for x in items:
        counts[x["platform"]] = counts.get(x["platform"], 0) + 1
    return counts


def get_site(site_id: str, *, user_id: int, reveal_password: bool = False) -> dict[str, Any] | None:
    sid = str(site_id or "").strip()
    if not sid:
        return None
    for k in _read_all():
        if str(k.get("id") or "") == sid and _belongs_to_user(k, user_id):
            return _public(_normalize(k), reveal_password=reveal_password)
    return None


def create_site(payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
    entry = _normalize({**payload, "id": str(uuid.uuid4()), "user_id": int(user_id)})
    if not entry["name"]:
        raise ValueError("name is required")
    if not entry["url"]:
        raise ValueError("url is required")
    if entry["platform"] == "wordpress":
        if not entry["username"]:
            raise ValueError("username is required")
        if not entry["app_password"]:
            raise ValueError("app_password is required")
    elif entry["platform"] == "haravan":
        if not entry["app_password"]:
            raise ValueError("private token is required")
    elif entry["platform"] == "shopify":
        if not str(entry.get("username") or "").strip():
            raise ValueError("client_id is required")
        if not entry["app_password"]:
            raise ValueError("client_secret is required")
    elif entry["platform"] == "webcake":
        from app.services.webcake_connect import unpack_webcake_secrets

        data = unpack_webcake_secrets(str(entry.get("app_password") or ""))
        if not str(data.get("access_token") or "").strip():
            raise ValueError("access_token is required")
        if not str(data.get("refresh_token") or "").strip():
            raise ValueError("refresh_token is required")
    items = _read_all()
    items.insert(0, entry)
    del items[MAX_SITES:]
    _write_all(items)
    return _public(entry)


def update_site(site_id: str, patch: dict[str, Any], *, user_id: int) -> dict[str, Any] | None:
    sid = str(site_id or "").strip()
    if not sid:
        return None
    items = _read_all()
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
    _write_all(out)
    return _public(found)


def delete_site(site_id: str, *, user_id: int) -> bool:
    sid = str(site_id or "").strip()
    if not sid:
        return False
    items = _read_all()
    new_items = [k for k in items if not (str(k.get("id") or "") == sid and _belongs_to_user(k, user_id))]
    if len(new_items) == len(items):
        return False
    _write_all(new_items)
    return True
