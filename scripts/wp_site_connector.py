"""WordPress site connector — REST API only (no browser automation)."""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

from pathlib import Path

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.user_scope import belongs_to_user
from app.services.wp_connect import normalize_wp_base_url, wp_get_json

SITES_FILE = Path("data/content_auto_update_sites.json")
MAX_SITES_PER_USER = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_sites() -> list[dict[str, Any]]:
    if not SITES_FILE.exists():
        return []
    try:
        raw = json.loads(SITES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _write_sites(items: list[dict[str, Any]]) -> None:
    SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SITES_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _wp_headers(username: str, app_password: str) -> dict[str, str]:
    pwd = str(app_password or "").strip().replace(" ", "")
    cred = f"{username.strip()}:{pwd}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(cred).decode("ascii"),
        "Accept": "application/json",
    }


def _public_site(site: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": site.get("id"),
        "user_id": site.get("user_id"),
        "label": site.get("label") or site.get("url"),
        "url": site.get("url"),
        "username": site.get("username"),
        "status": site.get("status") or "connected",
        "connected_at": site.get("connected_at"),
        "last_test_at": site.get("last_test_at"),
        "last_test_message": site.get("last_test_message"),
    }


def connect_site(
    *,
    user_id: int,
    url: str,
    username: str,
    app_password: str,
    label: str = "",
) -> dict[str, Any]:
    base = normalize_wp_base_url(url)
    if not base:
        raise HTTPException(status_code=400, detail="URL WordPress không hợp lệ.")
    user = str(username or "").strip()
    pwd = str(app_password or "").strip()
    if not user or not pwd:
        raise HTTPException(status_code=400, detail="Thiếu username hoặc Application Password.")

    test = test_connection(url=base, username=user, app_password=pwd)
    if not test.get("ok"):
        raise HTTPException(status_code=400, detail=test.get("message") or "Không kết nối được WordPress.")

    all_s = _read_sites()
    user_sites = [s for s in all_s if belongs_to_user(s, user_id)]
    if len(user_sites) >= MAX_SITES_PER_USER:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn site.")

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "label": (label or base).strip()[:120],
        "url": base,
        "username": user,
        "app_password": encrypt_secret(pwd),
        "status": "connected",
        "connected_at": _now(),
        "last_test_at": _now(),
        "last_test_message": test.get("message"),
    }
    all_s.append(entry)
    _write_sites(all_s)
    return _public_site(entry)


def list_sites(user_id: int) -> list[dict[str, Any]]:
    return [_public_site(s) for s in _read_sites() if belongs_to_user(s, user_id)]


def get_site(site_id: str, user_id: int) -> dict[str, Any] | None:
    for s in _read_sites():
        if str(s.get("id")) == str(site_id) and belongs_to_user(s, user_id):
            return s
    return None


def get_site_credentials(site_id: str, user_id: int) -> dict[str, str]:
    site = get_site(site_id, user_id)
    if not site:
        raise HTTPException(status_code=404, detail="Không tìm thấy site.")
    pwd = decrypt_secret(str(site.get("app_password") or "")).strip()
    if not pwd:
        raise HTTPException(status_code=400, detail="Site chưa có credential.")
    return {
        "url": str(site.get("url") or ""),
        "username": str(site.get("username") or ""),
        "app_password": pwd,
    }


def test_connection(*, url: str, username: str, app_password: str) -> dict[str, Any]:
    base = normalize_wp_base_url(url)
    if not base:
        return {"ok": False, "message": "URL không hợp lệ."}
    try:
        resp, working = wp_get_json(
            "/wp-json/wp/v2/users/me",
            url=base,
            headers=_wp_headers(username, app_password),
            auth=(username.strip(), str(app_password or "").strip().replace(" ", "")),
            timeout=25,
        )
    except requests.RequestException as exc:
        return {"ok": False, "message": f"Không kết nối được: {exc}"}
    if resp.status_code >= 400:
        return {"ok": False, "message": f"WordPress HTTP {resp.status_code}: {(resp.text or '')[:200]}"}
    return {"ok": True, "message": "Kết nối WordPress REST API thành công.", "working_url": working}


def test_site_by_id(site_id: str, user_id: int) -> dict[str, Any]:
    cred = get_site_credentials(site_id, user_id)
    result = test_connection(**cred)
    all_s = _read_sites()
    for i, s in enumerate(all_s):
        if str(s.get("id")) == str(site_id) and belongs_to_user(s, user_id):
            s = dict(s)
            s["last_test_at"] = _now()
            s["last_test_message"] = result.get("message")
            s["status"] = "connected" if result.get("ok") else "error"
            all_s[i] = s
            break
    _write_sites(all_s)
    return result


def _slug_from_url(post_url: str, site_base: str) -> str:
    path = urlparse(post_url).path.strip("/")
    base_host = urlparse(site_base).netloc.lower()
    if urlparse(post_url).netloc.lower() != base_host:
        return ""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    return parts[-1]


def _fetch_by_slug(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    slug: str,
    resource: str,
) -> dict[str, Any] | None:
    resp, _ = wp_get_json(
        f"/wp-json/wp/v2/{resource}",
        url=base,
        headers=headers,
        auth=auth,
        params={"slug": slug, "status": "any", "context": "edit"},
        timeout=30,
    )
    if resp.status_code >= 400:
        return None
    try:
        items = resp.json()
    except ValueError:
        return None
    if isinstance(items, list) and items:
        row = items[0]
        return row if isinstance(row, dict) else None
    return None


def fetch_post_by_url(*, site_id: str, user_id: int, post_url: str) -> dict[str, Any]:
    cred = get_site_credentials(site_id, user_id)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])
    slug = _slug_from_url(post_url, base)
    if not slug:
        raise HTTPException(status_code=400, detail="URL không thuộc site đã kết nối hoặc không đọc được slug.")

    post = _fetch_by_slug(base=base, headers=headers, auth=auth, slug=slug, resource="posts")
    post_type = "post"
    if not post:
        post = _fetch_by_slug(base=base, headers=headers, auth=auth, slug=slug, resource="pages")
        post_type = "page"
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết/trang qua REST API.")

    content = str(post.get("content", {}).get("raw") or post.get("content", {}).get("rendered") or "")
    excerpt = str(post.get("excerpt", {}).get("raw") or post.get("excerpt", {}).get("rendered") or "")

    return {
        "wp_id": int(post.get("id") or 0),
        "post_type": post_type,
        "title": str(post.get("title", {}).get("raw") or post.get("title", {}).get("rendered") or ""),
        "content": content,
        "excerpt": excerpt,
        "status": str(post.get("status") or "draft"),
        "link": str(post.get("link") or post_url),
        "slug": str(post.get("slug") or slug),
        "modified": str(post.get("modified") or ""),
    }
