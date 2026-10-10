"""Shared publishing categories per website + platform (Settings + Content AI)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from app.services.wp_categories import (
    load_wordpress_categories,
    read_cached_wordpress_categories,
    write_cached_wordpress_categories,
)

PLATFORM_DISPLAY_NAMES = {
    "wordpress": "WordPress",
    "haravan": "Haravan",
    "webcake": "Webcake",
    "shopify": "Shopify",
}
CATEGORY_PLATFORMS = frozenset(PLATFORM_DISPLAY_NAMES)
_HARAVAN_BLOGS_URL = "https://apis.haravan.com/web/blogs.json"


def normalize_platform(value: str) -> str:
    return str(value or "").strip().lower()


def platform_display_name(platform: str) -> str:
    p = normalize_platform(platform)
    if not p:
        return "nền tảng"
    if p in PLATFORM_DISPLAY_NAMES:
        return PLATFORM_DISPLAY_NAMES[p]
    cleaned = re.sub(r"[_\-]+", " ", p).strip()
    return cleaned.title() if cleaned else "nền tảng"


def platform_category_label(platform: str) -> str:
    return f"Danh mục {platform_display_name(platform)}"


def platform_supports_categories(platform: str) -> bool:
    return normalize_platform(platform) in CATEGORY_PLATFORMS


def _cache_dir() -> Path:
    raw = (os.getenv("CONTENT_AI_CACHE_DIR") or "").strip()
    root = Path(raw) if raw else Path(__file__).resolve().parents[2] / "data" / "content_ai_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _platform_category_cache_path() -> Path:
    return _cache_dir() / "platform_categories.json"


def sanitize_category_items(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in items or []:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id")
        if raw_id is None or raw_id == "":
            continue
        cid: Any
        try:
            n = int(str(raw_id).strip())
            if n <= 0:
                continue
            cid = n
        except (TypeError, ValueError):
            cid = str(raw_id).strip()
            if not cid:
                continue
        sid = str(cid)
        if sid in seen:
            continue
        name = re.sub(r"\s+", " ", str(row.get("name") or "").strip())
        if not name:
            continue
        try:
            parent = int(row.get("parent") or 0)
        except (TypeError, ValueError):
            parent = 0
        seen.add(sid)
        out.append({"id": cid, "name": name, "parent": parent})
    return out


def _cache_keys(*, user_id: int, platform: str, site_id: str = "", url: str = "") -> list[str]:
    keys: list[str] = []
    uid = int(user_id or 0)
    pf = normalize_platform(platform) or "unknown"
    sid = str(site_id or "").strip()
    if sid:
        keys.append(f"u{uid}:{pf}:id:{sid}")
    norm = str(url or "").strip().lower().rstrip("/")
    if norm:
        keys.append(f"u{uid}:{pf}:url:{norm}")
    return keys


def _read_raw_cache() -> dict[str, Any]:
    try:
        raw = json.loads(_platform_category_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_raw_cache(raw: dict[str, Any]) -> None:
    path = _platform_category_cache_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_cached_site_categories(
    *,
    user_id: int,
    platform: str,
    site_id: str = "",
    url: str = "",
) -> dict[str, Any] | None:
    keys = _cache_keys(user_id=user_id, platform=platform, site_id=site_id, url=url)
    if not keys:
        return None
    raw = _read_raw_cache()
    for key in keys:
        row = raw.get(key)
        if not isinstance(row, dict):
            continue
        items = sanitize_category_items(row.get("items"))
        selected_id = str(row.get("selected_id") or "").strip()
        if not items and not selected_id:
            continue
        return {
            "ok": True,
            "items": items,
            "selected_id": selected_id,
            "message": str(row.get("message") or ""),
            "from_cache": True,
            "unsupported": False,
        }
    return None


def write_cached_site_categories(
    *,
    user_id: int,
    platform: str,
    site_id: str = "",
    url: str = "",
    items: list[dict[str, Any]] | None = None,
    selected_id: str = "",
    message: str = "",
) -> None:
    keys = _cache_keys(user_id=user_id, platform=platform, site_id=site_id, url=url)
    if not keys:
        return
    clean = sanitize_category_items(items)
    sel = str(selected_id or "").strip()
    if not clean and not sel:
        return
    raw = _read_raw_cache()
    prev_sel = ""
    for key in keys:
        prev = raw.get(key)
        if isinstance(prev, dict) and not sel:
            prev_sel = str(prev.get("selected_id") or "").strip() or prev_sel
    payload = {
        "items": clean,
        "selected_id": sel or prev_sel,
        "message": str(message or (f"Đã tải {len(clean)} danh mục." if clean else "")),
        "fetched_at": int(time.time()),
        "platform": normalize_platform(platform),
    }
    for key in keys:
        raw[key] = payload
    _write_raw_cache(raw)
    if normalize_platform(platform) == "wordpress" and clean:
        write_cached_wordpress_categories(
            user_id=user_id,
            site_id=site_id,
            url=url,
            items=clean,
            message=str(payload["message"] or ""),
        )


def _empty_ok(**extra: Any) -> dict[str, Any]:
    out = {
        "ok": True,
        "items": [],
        "selected_id": "",
        "message": "",
        "unsupported": False,
        "from_cache": False,
        "fetch_failed": False,
    }
    out.update(extra)
    return out


def _label_payload(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    data["label"] = platform_category_label(platform)
    data["platform"] = normalize_platform(platform)
    data["unsupported"] = bool(data.get("unsupported"))
    return data


def fetch_haravan_blog_categories(*, private_token: str) -> dict[str, Any]:
    token = str(private_token or "").strip()
    if not token:
        return {"ok": False, "items": [], "message": "Thiếu Private Token."}
    try:
        r = requests.get(
            _HARAVAN_BLOGS_URL,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "digiseo-Tool/1.0",
            },
            params={"limit": 250},
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"ok": False, "items": [], "message": f"Không gọi được Haravan API: {exc}"}
    if r.status_code >= 400:
        return {
            "ok": False,
            "items": [],
            "message": f"Haravan blogs API HTTP {r.status_code}.",
        }
    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "items": [], "message": "Phản hồi Haravan không phải JSON."}
    blogs = data.get("blogs") if isinstance(data, dict) else None
    if not isinstance(blogs, list):
        blogs = []
    items = []
    for row in blogs:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                "id": row.get("id"),
                "name": row.get("title") or row.get("handle") or row.get("name"),
                "parent": 0,
            }
        )
    clean = sanitize_category_items(items)
    return {
        "ok": True,
        "items": clean,
        "message": f"Đã tải {len(clean)} danh mục.",
    }


def fetch_shopify_blog_categories(
    *,
    shop_url: str,
    client_id: str,
    secrets_blob: str,
) -> dict[str, Any]:
    from app.services.shopify_connect import list_shopify_blogs_as_categories

    return list_shopify_blogs_as_categories(
        shop_url=shop_url,
        client_id=client_id,
        secrets_blob=secrets_blob,
    )


def fetch_webcake_blog_categories(*, secrets_blob: str) -> dict[str, Any]:
    from app.services.webcake_connect import list_webcake_blog_categories

    return list_webcake_blog_categories(secrets_blob=secrets_blob)


def _fetch_for_site(site: dict[str, Any]) -> dict[str, Any]:
    pf = normalize_platform(site.get("platform"))
    url = str(site.get("url") or "").strip()
    username = str(site.get("username") or "").strip()
    password = str(site.get("app_password") or "").strip()
    if pf == "wordpress":
        if not url or not username or not password:
            return {"ok": False, "items": [], "message": "", "pending": True}
        result = load_wordpress_categories(
            user_id=int(site.get("_user_id") or 0),
            site_id=str(site.get("id") or "").strip(),
            url=url,
            username=username,
            app_password=password,
            refresh=True,
        )
        items = sanitize_category_items(result.get("items"))
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "items": items if ok else [],
            "message": str(result.get("message") or "") if ok else "",
        }
    if pf == "haravan":
        return fetch_haravan_blog_categories(private_token=password)
    if pf == "shopify":
        if not url or not username or not password:
            return {"ok": False, "items": [], "message": "", "pending": True}
        return fetch_shopify_blog_categories(
            shop_url=url,
            client_id=username,
            secrets_blob=password,
        )
    if pf == "webcake":
        if not password:
            return {"ok": False, "items": [], "message": "", "pending": True}
        return fetch_webcake_blog_categories(secrets_blob=password)
    return {"ok": True, "items": [], "unsupported": True, "message": ""}


def load_site_categories(
    *,
    user_id: int,
    site: dict[str, Any] | None,
    refresh: bool = False,
    selected_id: str = "",
) -> dict[str, Any]:
    site = dict(site or {})
    pf = normalize_platform(site.get("platform"))
    if not pf or not platform_supports_categories(pf):
        return _label_payload(
            pf,
            _empty_ok(unsupported=True, hide=True),
        )
    site_id = str(site.get("id") or "").strip()
    url = str(site.get("url") or "").strip()
    cached = read_cached_site_categories(
        user_id=user_id,
        platform=pf,
        site_id=site_id,
        url=url,
    )
    if pf == "wordpress" and (not cached or not cached.get("items")):
        wp_cached = read_cached_wordpress_categories(user_id=user_id, site_id=site_id, url=url)
        if wp_cached and wp_cached.get("items"):
            write_cached_site_categories(
                user_id=user_id,
                platform=pf,
                site_id=site_id,
                url=url,
                items=list(wp_cached.get("items") or []),
                selected_id=str((cached or {}).get("selected_id") or selected_id or ""),
                message=str(wp_cached.get("message") or ""),
            )
            cached = read_cached_site_categories(
                user_id=user_id,
                platform=pf,
                site_id=site_id,
                url=url,
            )
    want_sel = str(selected_id or (cached or {}).get("selected_id") or "").strip()
    if not refresh and cached and cached.get("items"):
        if str(selected_id or "").strip():
            write_cached_site_categories(
                user_id=user_id,
                platform=pf,
                site_id=site_id,
                url=url,
                items=list(cached.get("items") or []),
                selected_id=want_sel,
                message=str(cached.get("message") or ""),
            )
        data = dict(cached)
        data["selected_id"] = want_sel
        return _label_payload(pf, data)

    live = dict(site)
    live["_user_id"] = int(user_id or 0)
    fetched = _fetch_for_site(live)
    if fetched.get("unsupported"):
        return _label_payload(pf, _empty_ok(unsupported=True, hide=True))
    if fetched.get("ok"):
        items = sanitize_category_items(fetched.get("items"))
        write_cached_site_categories(
            user_id=user_id,
            platform=pf,
            site_id=site_id,
            url=url,
            items=items,
            selected_id=want_sel,
            message=str(fetched.get("message") or ""),
        )
        return _label_payload(
            pf,
            {
                "ok": True,
                "items": items,
                "selected_id": want_sel,
                "message": str(fetched.get("message") or (f"Đã tải {len(items)} danh mục." if items else "")),
                "from_cache": False,
                "unsupported": False,
            },
        )
    if cached and cached.get("items"):
        data = dict(cached)
        data["selected_id"] = want_sel or str(cached.get("selected_id") or "")
        data["fetch_failed"] = True
        data["ok"] = True
        return _label_payload(pf, data)
    pending = bool(fetched.get("pending"))
    return _label_payload(
        pf,
        _empty_ok(
            fetch_failed=not pending,
            pending=pending,
            selected_id=want_sel,
        ),
    )


def save_selected_category(
    *,
    user_id: int,
    site: dict[str, Any],
    selected_id: str,
) -> dict[str, Any]:
    pf = normalize_platform(site.get("platform"))
    cached = read_cached_site_categories(
        user_id=user_id,
        platform=pf,
        site_id=str(site.get("id") or ""),
        url=str(site.get("url") or ""),
    ) or {}
    write_cached_site_categories(
        user_id=user_id,
        platform=pf,
        site_id=str(site.get("id") or ""),
        url=str(site.get("url") or ""),
        items=list(cached.get("items") or []),
        selected_id=str(selected_id or ""),
        message=str(cached.get("message") or ""),
    )
    return load_site_categories(user_id=user_id, site=site, refresh=False, selected_id=str(selected_id or ""))
