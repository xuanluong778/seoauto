"""WordPress site connector — REST API only (no browser automation)."""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException

from pathlib import Path

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.publishing_sites_store import get_site as get_publishing_site
from app.services.publishing_sites_store import list_sites as list_publishing_sites
from app.services.user_scope import belongs_to_user
from app.services.wp_connect import normalize_wp_base_url, parse_wp_response_json, wp_get_json

SITES_FILE = Path("data/content_auto_update_sites.json")
MAX_SITES_PER_USER = 20

logger = logging.getLogger(__name__)

_SKIP_REST_TYPES = frozenset({
    "attachment",
    "revision",
    "nav_menu_item",
    "wp_navigation",
    "wp_font_family",
    "wp_font_face",
    "media",
})


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


def _site_url_key(url: str) -> str:
    return (normalize_wp_base_url(url) or str(url or "").strip().rstrip("/")).lower()


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


def _find_user_site_index(
    items: list[dict[str, Any]],
    *,
    user_id: int,
    url_key: str,
    publishing_site_id: str = "",
) -> int | None:
    pub_id = str(publishing_site_id or "").strip()
    for i, site in enumerate(items):
        if not belongs_to_user(site, user_id):
            continue
        if pub_id and str(site.get("publishing_site_id") or "") == pub_id:
            return i
        if url_key and _site_url_key(str(site.get("url") or "")) == url_key:
            return i
    return None


def _upsert_publishing_site(
    *,
    user_id: int,
    url: str,
    username: str,
    app_password: str,
    label: str = "",
    verified: bool = True,
) -> str:
    """Ghi site WordPress vào publishing store — đồng bộ với «Thêm site đăng bài»."""
    from app.services.publishing_sites_store import create_site as pub_create
    from app.services.publishing_sites_store import list_sites as pub_list
    from app.services.publishing_sites_store import update_site as pub_update

    base = normalize_wp_base_url(url)
    if not base:
        return ""
    url_key = _site_url_key(base)
    user = str(username or "").strip()
    pwd = str(app_password or "").strip()
    if not user or not pwd:
        return ""

    existing_id = ""
    for row in pub_list(user_id=user_id, platform="wordpress"):
        if _site_url_key(str(row.get("url") or "")) == url_key:
            existing_id = str(row.get("id") or "")
            break

    name = str(label or base).strip()[:120] or base
    patch = {
        "name": name,
        "url": base,
        "username": user,
        "app_password": pwd,
        "verified": bool(verified),
        "last_message": "Đồng bộ từ Content Auto Update.",
    }
    if existing_id:
        updated = pub_update(existing_id, patch, user_id=user_id)
        return str((updated or {}).get("id") or existing_id)
    created = pub_create(
        {
            "platform": "wordpress",
            "name": name,
            "url": base,
            "username": user,
            "app_password": pwd,
            "default_status": "draft",
            "verified": bool(verified),
            "last_message": patch["last_message"],
        },
        user_id=user_id,
    )
    return str(created.get("id") or "")


def _sync_from_publishing_sites(user_id: int) -> None:
    """Import / refresh WordPress sites from publishing store into Auto Update store."""
    pub_list = list_publishing_sites(user_id=user_id, platform="wordpress")
    if not pub_list:
        return

    all_s = _read_sites()
    changed = False
    for pub in pub_list:
        pub_id = str(pub.get("id") or "").strip()
        base = normalize_wp_base_url(str(pub.get("url") or ""))
        url_key = _site_url_key(base)
        if not pub_id or not url_key:
            continue

        full = get_publishing_site(pub_id, user_id=user_id, reveal_password=True)
        if not full:
            continue
        pwd = str(full.get("app_password") or "").strip()
        user = str(full.get("username") or "").strip()
        if not user or not pwd:
            continue

        label = str(full.get("name") or pub.get("name") or base).strip()[:120]
        status = "connected" if full.get("verified") else "imported"
        idx = _find_user_site_index(all_s, user_id=user_id, url_key=url_key, publishing_site_id=pub_id)
        if idx is not None:
            row = dict(all_s[idx])
            row.update(
                {
                    "label": label or row.get("label") or base,
                    "url": base,
                    "username": user,
                    "app_password": encrypt_secret(pwd),
                    "status": status,
                    "publishing_site_id": pub_id,
                    "last_test_message": str(full.get("last_message") or row.get("last_test_message") or "Đồng bộ từ site đăng bài."),
                }
            )
            if full.get("last_checked_at"):
                row["last_test_at"] = str(full.get("last_checked_at"))
            all_s[idx] = row
            changed = True
            continue

        all_s.append(
            {
                "id": str(uuid.uuid4()),
                "user_id": int(user_id),
                "label": label or base,
                "url": base,
                "username": user,
                "app_password": encrypt_secret(pwd),
                "status": status,
                "connected_at": _now(),
                "last_test_at": str(full.get("last_checked_at") or "") or None,
                "last_test_message": str(full.get("last_message") or "Đồng bộ từ site đăng bài."),
                "publishing_site_id": pub_id,
            }
        )
        changed = True

    if changed:
        _write_sites(all_s)


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
    url_key = _site_url_key(base)
    existing_idx = _find_user_site_index(all_s, user_id=user_id, url_key=url_key)
    if existing_idx is None and len(user_sites) >= MAX_SITES_PER_USER:
        raise HTTPException(status_code=400, detail="Đã đạt giới hạn site.")

    pub_id = _upsert_publishing_site(
        user_id=user_id,
        url=base,
        username=user,
        app_password=pwd,
        label=label or base,
        verified=True,
    )

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
    if pub_id:
        entry["publishing_site_id"] = pub_id
    if existing_idx is not None:
        prev = all_s[existing_idx]
        entry["id"] = str(prev.get("id") or entry["id"])
        entry["connected_at"] = str(prev.get("connected_at") or entry["connected_at"])
        if not pub_id and prev.get("publishing_site_id"):
            entry["publishing_site_id"] = prev.get("publishing_site_id")
        all_s[existing_idx] = entry
    else:
        all_s.append(entry)
    _write_sites(all_s)
    return _public_site(entry)


def list_sites(user_id: int) -> list[dict[str, Any]]:
    _sync_from_publishing_sites(user_id)
    items = [_public_site(s) for s in _read_sites() if belongs_to_user(s, user_id)]
    items.sort(key=lambda x: str(x.get("label") or x.get("url") or "").lower())
    return items


def get_site(site_id: str, user_id: int) -> dict[str, Any] | None:
    _sync_from_publishing_sites(user_id)
    for s in _read_sites():
        if str(s.get("id")) == str(site_id) and belongs_to_user(s, user_id):
            return s
    return None


def get_site_credentials(site_id: str, user_id: int) -> dict[str, str]:
    site = get_site(site_id, user_id)
    if not site:
        raise HTTPException(status_code=404, detail="Không tìm thấy site.")
    pwd = decrypt_secret(str(site.get("app_password") or "")).strip()
    # Fallback: password encrypted with another key / corrupted in CAU store.
    if not pwd:
        pub_id = str(site.get("publishing_site_id") or "").strip()
        full = None
        if pub_id:
            full = get_publishing_site(pub_id, user_id=user_id, reveal_password=True)
        if not full:
            # Match by URL against publishing store
            want = _site_url_key(str(site.get("url") or ""))
            if want:
                for pub in list_publishing_sites(user_id=user_id, platform="wordpress"):
                    if _site_url_key(str(pub.get("url") or "")) != want:
                        continue
                    full = get_publishing_site(str(pub.get("id") or ""), user_id=user_id, reveal_password=True)
                    if full:
                        break
        if full:
            candidate = str(full.get("app_password") or "").strip()
            if candidate.startswith("enc:v1:"):
                candidate = decrypt_secret(candidate).strip()
            if candidate:
                pwd = candidate.replace(" ", "")
                try:
                    all_s = _read_sites()
                    for i, row in enumerate(all_s):
                        if str(row.get("id")) == str(site_id) and belongs_to_user(row, user_id):
                            row = dict(row)
                            row["app_password"] = encrypt_secret(pwd)
                            row["username"] = str(full.get("username") or row.get("username") or "")
                            if full.get("id"):
                                row["publishing_site_id"] = str(full.get("id"))
                            all_s[i] = row
                            _write_sites(all_s)
                            break
                except Exception:
                    logger.exception("heal CAU site password failed site_id=%s", site_id)
    if not pwd:
        raise HTTPException(
            status_code=400,
            detail="Site chưa có Application Password hợp lệ. Hãy bấm «Kết nối site» lại với Application Password mới.",
        )
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
        items = parse_wp_response_json(resp)
    except ValueError:
        return None
    if isinstance(items, list) and items:
        row = items[0]
        return row if isinstance(row, dict) else None
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def _search_slug_hint(q: str, site_base: str = "") -> str:
    raw = str(q or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return _slug_from_url(raw, site_base) or ""
    path = raw if raw.startswith("/") else raw
    if "/" in path:
        parts = [p for p in path.strip("/").split("/") if p]
        return parts[-1] if parts else ""
    return raw if re.fullmatch(r"[a-z0-9][a-z0-9\-_]*", raw, re.I) else ""


def _norm_url_key(url: str, base: str = "") -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        full = urljoin(base, raw) if base else raw
        p = urlparse(full)
        path = (p.path or "/").rstrip("/") or "/"
        return f"{p.scheme}://{p.netloc.lower()}{path}".lower()
    except Exception:
        return raw.lower().rstrip("/")


def _filter_item(
    *,
    item_type: str,
    item_id: str,
    name: str,
    slug: str = "",
    url: str = "",
    count: int = 0,
    is_main: bool = True,
) -> dict[str, Any]:
    return {
        "type": item_type,
        "id": str(item_id or ""),
        "name": _strip_html(str(name or "")),
        "slug": str(slug or "").strip().lower(),
        "url": str(url or "").strip(),
        "count": max(0, int(count or 0)),
        "is_main": bool(is_main),
    }


_NON_MAIN_SLUG_TOKENS = {
    "lien-he", "contact", "chinh-sach", "privacy", "gioi-thieu", "about",
    "tuyen-dung", "career", "ho-tro", "support", "dieu-khoan", "terms",
    "khach-hang", "faq", "bao-mat", "refund", "return",
}


def _looks_like_non_main_item(name: str, slug: str, url: str = "") -> bool:
    text = " ".join([
        str(name or "").strip().lower(),
        str(slug or "").strip().lower(),
        str(urlparse(str(url or "")).path or "").strip("/").lower(),
    ])
    return any(token in text for token in _NON_MAIN_SLUG_TOKENS)


def _is_prefix_url(prefix: str, candidate: str) -> bool:
    pfx = _norm_url_key(prefix)
    cur = _norm_url_key(candidate)
    if not pfx or not cur:
        return False
    if pfx.endswith("/"):
        return cur.startswith(pfx.rstrip("/"))
    return cur == pfx or cur.startswith(pfx + "/")


def _wp_paginate(
    path: str,
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    params: dict[str, Any] | None = None,
    timeout: float = 35,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    base_params = dict(params or {})
    while page <= total_pages:
        req_params = {**base_params, "page": page}
        resp, _ = wp_get_json(
            path,
            url=base,
            headers=headers,
            auth=auth,
            params=req_params,
            timeout=timeout,
        )
        if resp.status_code >= 400:
            break
        try:
            chunk = parse_wp_response_json(resp)
        except ValueError:
            # Some hosts break when _fields is used; retry once without it.
            if page == 1 and "_fields" in base_params:
                alt = dict(base_params)
                alt.pop("_fields", None)
                try:
                    resp2, _ = wp_get_json(
                        path,
                        url=base,
                        headers=headers,
                        auth=auth,
                        params={**alt, "page": page},
                        timeout=timeout,
                    )
                    if resp2.status_code < 400:
                        chunk = parse_wp_response_json(resp2)
                        resp = resp2
                        base_params = alt
                    else:
                        raise ValueError("retry http error")
                except (requests.RequestException, OSError, ValueError):
                    logger.warning(
                        "wp_paginate invalid json path=%s http=%s ctype=%s",
                        path,
                        resp.status_code,
                        (resp.headers.get("Content-Type") or "")[:80],
                    )
                    break
            else:
                logger.warning(
                    "wp_paginate invalid json path=%s http=%s ctype=%s",
                    path,
                    resp.status_code,
                    (resp.headers.get("Content-Type") or "")[:80],
                )
                break
        if not isinstance(chunk, list):
            break
        rows.extend(x for x in chunk if isinstance(x, dict))
        try:
            total_pages = max(1, int(resp.headers.get("X-WP-TotalPages") or 1))
        except (TypeError, ValueError):
            total_pages = page
        page += 1
    return rows


def _slug_from_path(url: str, base: str) -> str:
    key = _norm_url_key(url, base)
    base_key = _norm_url_key(base, base)
    if not key or key == base_key or key.endswith("/"):
        return "home"
    path = urlparse(key).path.strip("/")
    if not path:
        return "home"
    return path.split("/")[-1]


def _resolve_uncategorized_category_id(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> int:
    for row in _fetch_wp_category_rows(base=base, headers=headers, auth=auth):
        slug = str(row.get("slug") or "").lower()
        if slug in {"uncategorized", "chua-phan-loai"}:
            try:
                return int(row.get("id") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _category_row_by_slug(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    slug: str,
) -> dict[str, Any] | None:
    s = str(slug or "").strip().lower()
    if not s or s == "home":
        return None
    resp, _ = wp_get_json(
        "/wp-json/wp/v2/categories",
        url=base,
        headers=headers,
        auth=auth,
        params={"slug": s, "per_page": 1, "_fields": "id,name,slug,count"},
        timeout=25,
    )
    if resp.status_code >= 400:
        return None
    try:
        rows = parse_wp_response_json(resp)
    except ValueError:
        return None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _fetch_wp_level1_categories(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, Any]]:
    """Fetch WordPress parent categories (parent=0) for scan scope dropdown."""
    rows = _wp_paginate(
        "/wp-json/wp/v2/categories",
        base=base,
        headers=headers,
        auth=auth,
        params={
            "parent": 0,
            "per_page": 100,
            "orderby": "name",
            "order": "asc",
            "hide_empty": "false",
            "_fields": "id,name,slug,count,link,parent",
        },
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            cat_id = int(row.get("id") or 0)
            parent = int(row.get("parent") or 0)
        except (TypeError, ValueError):
            continue
        if cat_id <= 0 or parent != 0:
            continue
        name = _strip_html(str(row.get("name") or ""))
        slug = str(row.get("slug") or "").strip()
        count = int(row.get("count") or 0)
        link = str(row.get("link") or "").strip()
        if not link and slug:
            link = urljoin(base.rstrip("/") + "/", f"category/{slug}/")
        items.append({
            "id": cat_id,
            "name": name,
            "slug": slug,
            "count": count,
            "link": link,
            "type": "category",
        })
    items.sort(key=lambda x: str(x.get("name") or "").lower())
    return items


def _fetch_wp_categories(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, Any]]:
    return _fetch_wp_level1_categories(base=base, headers=headers, auth=auth)


def _fetch_wp_category_rows(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, Any]]:
    return _wp_paginate(
        "/wp-json/wp/v2/categories",
        base=base,
        headers=headers,
        auth=auth,
        params={"per_page": 100, "hide_empty": "false", "_fields": "id,parent,slug,name,count"},
    )


def _expand_category_ids(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    root_id: int,
) -> list[int]:
    root = int(root_id or 0)
    if root <= 0:
        return []
    rows = _fetch_wp_category_rows(base=base, headers=headers, auth=auth)
    children_by_parent: dict[int, list[int]] = {}
    for row in rows:
        try:
            cid = int(row.get("id") or 0)
            pid = int(row.get("parent") or 0)
        except (TypeError, ValueError):
            continue
        if cid <= 0:
            continue
        children_by_parent.setdefault(pid, []).append(cid)

    seen: set[int] = set()
    ordered: list[int] = []
    stack = [root]
    while stack:
        cid = stack.pop(0)
        if cid in seen:
            continue
        seen.add(cid)
        ordered.append(cid)
        stack.extend(children_by_parent.get(cid, []))
    return ordered


def _fetch_wp_top_pages(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    rows = _wp_paginate(
        "/wp-json/wp/v2/pages",
        base=base,
        headers=headers,
        auth=auth,
        params={
            "parent": 0,
            "per_page": 100,
            "status": "publish",
            "_fields": "id,link,slug,title",
        },
    )
    for row in rows:
        page_id = int(row.get("id") or 0)
        if not page_id:
            continue
        title_obj = row.get("title") if isinstance(row.get("title"), dict) else {}
        title = _strip_html(str(title_obj.get("rendered") or title_obj.get("raw") or ""))
        link = str(row.get("link") or "")
        slug = str(row.get("slug") or "") or _slug_from_path(link, base)
        cat = _category_row_by_slug(base=base, headers=headers, auth=auth, slug=slug)
        count = int((cat or {}).get("count") or 0)
        items.append(_filter_item(
            item_type="page",
            item_id=str(page_id),
            name=title or slug,
            slug=slug,
            url=link,
            count=count,
            is_main=not _looks_like_non_main_item(title or slug, slug, link),
        ))
    return items


def _fetch_wp_menu_items(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, Any]]:
    rows = _wp_paginate(
        "/wp-json/wp/v2/menu-items",
        base=base,
        headers=headers,
        auth=auth,
        params={"per_page": 100, "_fields": "id,title,url,menu_item_parent,slug"},
    )
    if not rows:
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        parent = int(row.get("menu_item_parent") or 0)
        if parent:
            continue
        title_obj = row.get("title") if isinstance(row.get("title"), dict) else {}
        name = _strip_html(str(title_obj.get("rendered") or title_obj.get("raw") or row.get("title") or ""))
        url = str(row.get("url") or "").strip()
        if not name or not url:
            continue
        slug = str(row.get("slug") or "") or _slug_from_path(url, base)
        item_id = "home" if slug == "home" else slug
        cat = _category_row_by_slug(base=base, headers=headers, auth=auth, slug=slug)
        count = int((cat or {}).get("count") or 0)
        items.append(_filter_item(
            item_type="menu_url",
            item_id=item_id,
            name=name,
            slug=slug,
            url=url,
            count=count,
            is_main=not _looks_like_non_main_item(name, slug, url),
        ))
    return items


_NAV_CLASS_RE = re.compile(r"(nav|menu|navbar|main-menu|primary-menu)", re.I)


def _parse_home_nav_links(*, base: str) -> list[dict[str, Any]]:
    """Fallback: parse homepage header/nav links when menu-items REST is unavailable."""
    items: list[dict[str, Any]] = []
    try:
        resp = requests.get(
            base.rstrip("/") + "/",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException:
        return items
    if resp.status_code >= 400 or not (resp.text or "").strip():
        return items

    soup = BeautifulSoup(resp.text[:800_000], "html.parser")
    nav_roots: list[Any] = []
    for tag in soup.find_all(["nav", "header"]):
        nav_roots.append(tag)
    for tag in soup.find_all(class_=_NAV_CLASS_RE):
        nav_roots.append(tag)
    if not nav_roots:
        nav_roots = [soup]

    seen: set[str] = set()
    base_host = urlparse(base).netloc.lower()

    def _iter_top_level_links(root: Any) -> list[Any]:
        links: list[Any] = []
        selectors = [
            ":scope > ul > li > a",
            ":scope > div > ul > li > a",
            ":scope > div > div > ul > li > a",
            ":scope > a",
        ]
        for selector in selectors:
            try:
                found = root.select(selector)
            except Exception:
                found = []
            for tag in found:
                if tag not in links:
                    links.append(tag)
        return links

    for root in nav_roots:
        for a in _iter_top_level_links(root):
            href = str(a.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base, href)
            host = urlparse(full).netloc.lower()
            if host and host != base_host:
                continue
            name = a.get_text(" ", strip=True)
            if not name or len(name) > 80:
                continue
            key = _norm_url_key(full, base)
            if not key or key in seen:
                continue
            seen.add(key)
            slug = _slug_from_path(full, base)
            item_id = "home" if slug == "home" else slug
            items.append(_filter_item(
                item_type="menu_url",
                item_id=item_id,
                name=name,
                slug=slug,
                url=full,
                count=0,
                is_main=not _looks_like_non_main_item(name, slug, full),
            ))
    return items


def _merge_filter_items(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    menu_items: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    main_menu_urls = {
        _norm_url_key(str(item.get("url") or ""), base)
        for item in menu_items
        if item.get("is_main")
    }

    def _add(item: dict[str, Any], *, allow_dup_name: bool = False) -> None:
        key = _norm_url_key(str(item.get("url") or ""), base) if item.get("url") else ""
        item_key = f"{item.get('type')}:{item.get('id')}"
        if item_key in seen_ids:
            return
        if key and key in seen_urls and item.get("type") != "category":
            return
        if key:
            seen_urls.add(key)
        seen_ids.add(item_key)
        merged.append(item)

    home_url = base.rstrip("/") + "/"
    _add(_filter_item(
        item_type="menu_url",
        item_id="home",
        name="Trang chủ",
        slug="home",
        url=home_url,
        count=0,
        is_main=True,
    ))

    for item in menu_items:
        if not item.get("is_main"):
            continue
        _add(item)

    for item in pages:
        if not item.get("is_main"):
            continue
        if main_menu_urls and _norm_url_key(str(item.get("url") or ""), base) not in main_menu_urls:
            continue
        key = _norm_url_key(str(item.get("url") or ""), base)
        if key and key in seen_urls:
            continue
        _add(item)

    cat_urls: set[str] = set()
    for item in categories:
        slug = str(item.get("slug") or "")
        if slug:
            cat_urls.add(_norm_url_key(urljoin(base + "/", slug), base))
            cat_urls.add(_norm_url_key(urljoin(base + "/", f"category/{slug}"), base))
    for item in categories:
        if not item.get("is_main"):
            continue
        slug = str(item.get("slug") or "")
        if slug and item.get("id") != "uncategorized":
            pseudo = _norm_url_key(urljoin(base + "/", slug), base)
            if pseudo in seen_urls:
                continue
        _add(item, allow_dup_name=True)

    for item in merged:
        if item.get("type") in {"menu_url", "page"} and not item.get("count"):
            slug = str(item.get("slug") or "")
            cat = _category_row_by_slug(base=base, headers=headers, auth=auth, slug=slug)
            if cat:
                item["count"] = int(cat.get("count") or 0)

    def _keep_main_item(item: dict[str, Any]) -> bool:
        if not item.get("is_main"):
            return False
        item_type = str(item.get("type") or "")
        if item_type == "category":
            return True
        url = str(item.get("url") or "")
        path = urlparse(url).path.strip("/")
        if not path:
            return True
        depth = len([p for p in path.split("/") if p])
        return depth <= 1

    merged = [item for item in merged if _keep_main_item(item)]
    merged.sort(key=lambda item: (
        0 if str(item.get("slug") or "") == "home" else 1,
        {"menu_url": 0, "page": 1, "category": 2}.get(str(item.get("type") or ""), 9),
        str(item.get("name") or "").lower(),
    ))
    return merged


def _apply_scan_filter(
    params: dict[str, Any],
    *,
    filter_key: str,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> str:
    raw = str(filter_key or "").strip()
    if not raw or raw.lower() in {"all", "0", ""}:
        return ""

    ftype = "category"
    fid = raw
    if ":" in raw:
        ftype, fid = raw.split(":", 1)
        ftype = ftype.strip().lower()
        fid = fid.strip()

    if ftype == "category":
        if fid.lower() in {"uncategorized", "uncategorised"}:
            uncat_id = _resolve_uncategorized_category_id(
                base=base, headers=headers, auth=auth,
            )
            if uncat_id > 0:
                params["categories"] = uncat_id
            return ""
        try:
            cat_id = int(fid)
        except ValueError:
            raise HTTPException(status_code=400, detail="category_id không hợp lệ.")
        params["categories"] = cat_id
        return ""

    if ftype in {"page", "menu_url"}:
        prefix_url = ""
        if fid.lower() == "home":
            return base.rstrip("/") + "/"
        slug = fid
        if ftype == "page":
            try:
                resp, _ = wp_get_json(
                    f"/wp-json/wp/v2/pages/{int(fid)}",
                    url=base,
                    headers=headers,
                    auth=auth,
                    params={"_fields": "slug,link"},
                    timeout=25,
                )
                if resp.status_code < 400:
                    row = parse_wp_response_json(resp)
                    if isinstance(row, dict):
                        slug = str(row.get("slug") or slug)
                        prefix_url = str(row.get("link") or "")
            except (ValueError, TypeError):
                pass
        else:
            menu_items = _fetch_wp_menu_items(base=base, headers=headers, auth=auth) or _parse_home_nav_links(base=base)
            for item in menu_items:
                if str(item.get("id") or "") == fid or str(item.get("slug") or "") == fid:
                    prefix_url = str(item.get("url") or "")
                    slug = str(item.get("slug") or slug)
                    break
        cat = _category_row_by_slug(base=base, headers=headers, auth=auth, slug=slug)
        if cat:
            cat_id = int(cat.get("id") or 0)
            expanded = _expand_category_ids(base=base, headers=headers, auth=auth, root_id=cat_id)
            params["categories"] = ",".join(str(x) for x in expanded) if expanded else cat_id
            # Prefer category filtering when the selected main menu/page maps to a WP category.
            # URL-prefix fallback is only for sections that do not have a matching category.
            return ""
        params["search"] = slug.replace("-", " ")[:200]
        return prefix_url

    raise HTTPException(status_code=400, detail="Bộ lọc không hợp lệ.")


def list_site_categories(
    *,
    site_id: str,
    user_id: int,
) -> dict[str, Any]:
    """Load level-1 WordPress categories for Auto Update scan scope."""
    cred = get_site_credentials(site_id, user_id)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])

    items = _fetch_wp_level1_categories(base=base, headers=headers, auth=auth)
    has_uncategorized = any(
        str(c.get("slug") or "").lower() in {"uncategorized", "chua-phan-loai"}
        and int(c.get("count") or 0) > 0
        for c in items
    )
    return {
        "items": items,
        "categories": items,
        "has_uncategorized": has_uncategorized,
    }


def _looks_like_url_query(q: str) -> bool:
    s = str(q or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("www.")


def _fetch_wp_public_rest_types(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
) -> list[dict[str, str]]:
    """Discover public post types exposed in WP REST API."""
    fallback = [
        {"slug": "post", "rest_base": "posts"},
        {"slug": "page", "rest_base": "pages"},
    ]
    resp, _ = wp_get_json(
        "/wp-json/wp/v2/types",
        url=base,
        headers=headers,
        auth=auth,
        timeout=25,
    )
    if resp.status_code >= 400:
        return fallback
    try:
        data = parse_wp_response_json(resp)
    except ValueError:
        return fallback
    if not isinstance(data, dict):
        return fallback

    out: list[dict[str, str]] = []
    seen_bases: set[str] = set()
    for slug, meta in data.items():
        if not isinstance(meta, dict):
            continue
        type_slug = str(slug or "").strip().lower()
        if not type_slug or type_slug in _SKIP_REST_TYPES:
            continue
        if meta.get("public") is False:
            continue
        if meta.get("show_in_rest") is False:
            continue
        rest_base = str(meta.get("rest_base") or slug or "").strip()
        rb_lower = rest_base.lower()
        if not rest_base or rb_lower in _SKIP_REST_TYPES:
            continue
        if rest_base in seen_bases:
            continue
        seen_bases.add(rest_base)
        out.append({"slug": type_slug, "rest_base": rest_base})

    return out or fallback


def list_site_posts(
    *,
    site_id: str,
    user_id: int,
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    status: str = "all",
    category_id: str = "",
    fetch_all: bool = False,
    max_total: int = 5000,
) -> dict[str, Any]:
    """List WordPress content via REST API (posts, pages, public CPTs)."""
    cred = get_site_credentials(site_id, user_id)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])

    per_page = max(1, min(int(per_page or 20), 100))
    page = max(1, int(page or 1))
    status_key = str(status or "all").strip().lower()
    status_map = {
        "all": "any",
        "publish": "publish",
        "published": "publish",
        "draft": "draft",
        "private": "private",
    }
    wp_status = status_map.get(status_key, "any")

    cat_raw = str(category_id or "").strip()
    category_filter = bool(cat_raw and cat_raw.lower() not in {"all", "0", ""})

    base_params: dict[str, Any] = {
        # Prefer public view context first — context=edit + excerpt often breaks JSON on some hosts/plugins.
        "context": "view",
        "status": "publish",
        "_fields": "id,link,slug,status,title,modified,date",
    }
    if status_key in {"draft", "private"}:
        base_params["status"] = wp_status
        base_params["context"] = "edit"
    elif status_key == "publish":
        base_params["status"] = "publish"
        base_params["context"] = "view"
    elif status_key == "all":
        # "all" starts with published posts; edit/any is attempted as soft fallback later.
        base_params["status"] = "publish"
        base_params["context"] = "view"

    q = str(search or "").strip()
    if q and not (fetch_all and not category_filter and _looks_like_url_query(q)):
        slug_hint = _search_slug_hint(q, base)
        if slug_hint and re.fullmatch(r"[a-z0-9][a-z0-9\-_]*", slug_hint, re.I):
            base_params["slug"] = slug_hint
        else:
            base_params["search"] = q[:200]

    if category_filter:
        _apply_scan_filter(
            base_params,
            filter_key=cat_raw,
            base=base,
            headers=headers,
            auth=auth,
        )

    def _row_to_post(
        row: dict[str, Any],
        *,
        type_slug: str = "post",
        rest_base: str = "posts",
    ) -> dict[str, Any]:
        title_obj = row.get("title") if isinstance(row.get("title"), dict) else {}
        return {
            "id": int(row.get("id") or 0),
            "type": str(type_slug or rest_base or "post"),
            "rest_base": str(rest_base or type_slug or "posts"),
            "link": str(row.get("link") or ""),
            "slug": str(row.get("slug") or ""),
            "status": str(row.get("status") or ""),
            "title": _strip_html(str(title_obj.get("rendered") or title_obj.get("raw") or "")),
            "modified": str(row.get("modified") or ""),
            "date": str(row.get("date") or ""),
        }

    def _fetch_rows(
        resource: str,
        req_params: dict[str, Any],
        *,
        soft_fail: bool = False,
    ) -> tuple[list[dict[str, Any]], int, int]:
        try:
            resp, _ = wp_get_json(
                f"/wp-json/wp/v2/{resource}",
                url=base,
                headers=headers,
                auth=auth,
                params=req_params,
                timeout=60,
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.warning(
                "cau_scan wp_get_json failed resource=%s site_id=%s soft_fail=%s err=%s",
                resource,
                site_id,
                soft_fail,
                str(exc)[:200],
            )
            if soft_fail:
                return [], 0, 0
            raise HTTPException(
                status_code=502,
                detail={
                    "message": f"Không kết nối được WordPress khi lấy «{resource}». Kiểm tra site/Application Password hoặc thử lại.",
                    "code": "wp_connect_failed",
                    "resource": resource,
                },
            ) from exc

        if resp.status_code >= 400:
            # Soft-skip unsupported / forbidden CPTs during whole-site scan.
            if soft_fail or resp.status_code in {400, 401, 403, 404}:
                try:
                    err = parse_wp_response_json(resp)
                except ValueError:
                    err = {}
                code = str((err or {}).get("code") or "") if isinstance(err, dict) else ""
                if soft_fail or resp.status_code == 404 or code in {
                    "rest_post_invalid_page_number",
                    "rest_invalid_param",
                    "rest_no_route",
                    "rest_forbidden",
                    "rest_cannot_read",
                    "rest_cookie_invalid_nonce",
                }:
                    logger.info(
                        "cau_scan skip resource=%s http=%s code=%s soft_fail=%s",
                        resource,
                        resp.status_code,
                        code,
                        soft_fail,
                    )
                    return [], 0, 0
            detail = (resp.text or "")[:300]
            raise HTTPException(
                status_code=502,
                detail={
                    "message": f"WordPress không trả danh sách «{resource}» (HTTP {resp.status_code}). Thử lọc theo danh mục hoặc kiểm tra quyền REST API.",
                    "code": "wp_list_failed",
                    "resource": resource,
                    "wp_status": resp.status_code,
                    "wp_detail": detail,
                },
            )

        parse_err: Exception | None = None
        try:
            rows = parse_wp_response_json(resp)
        except ValueError as exc:
            parse_err = exc
            rows = None
            # Retry safer variants: drop _fields, smaller page, publish/view.
            variants: list[dict[str, Any]] = []
            if "_fields" in req_params:
                v = dict(req_params)
                v.pop("_fields", None)
                variants.append(v)
            v2 = dict(req_params)
            v2.pop("_fields", None)
            v2["status"] = "publish"
            v2["context"] = "view"
            try:
                v2["per_page"] = min(int(v2.get("per_page") or 20), 20)
            except (TypeError, ValueError):
                v2["per_page"] = 20
            if v2 not in variants:
                variants.append(v2)
            for alt in variants:
                try:
                    resp2, _ = wp_get_json(
                        f"/wp-json/wp/v2/{resource}",
                        url=base,
                        headers=headers,
                        auth=auth,
                        params=alt,
                        timeout=60,
                    )
                    if resp2.status_code >= 400:
                        continue
                    rows = parse_wp_response_json(resp2)
                    resp = resp2
                    parse_err = None
                    break
                except (requests.RequestException, OSError, ValueError):
                    continue
            if parse_err is not None or rows is None:
                if soft_fail:
                    return [], 0, 0
                hint = str(parse_err or "")[:160]
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": (
                            f"WordPress trả dữ liệu không hợp lệ cho «{resource}». "
                            "Site có thể chặn REST API (WAF/Cloudflare) hoặc plugin chèn HTML vào JSON. "
                            "Thử kết nối lại site hoặc tắt plugin bảo mật tạm thời."
                        ),
                        "code": "wp_invalid_json",
                        "resource": resource,
                        "hint": hint,
                    },
                ) from parse_err
        if not isinstance(rows, list):
            rows = []
        try:
            total_pages = int(resp.headers.get("X-WP-TotalPages") or 0)
        except (TypeError, ValueError):
            total_pages = 0
        try:
            total_items = int(resp.headers.get("X-WP-Total") or 0)
        except (TypeError, ValueError):
            total_items = 0
        return rows, total_pages, total_items

    def _paginate_resource(
        rest_base: str,
        req_params: dict[str, Any],
        *,
        cap: int,
        soft_fail: bool = False,
    ) -> list[dict[str, Any]]:
        wp_per_page = 100
        wp_page = 1
        total_pages = 1
        collected: list[dict[str, Any]] = []
        while wp_page <= total_pages and len(collected) < cap:
            page_params = dict(req_params)
            page_params["per_page"] = wp_per_page
            page_params["page"] = wp_page
            chunk, total_pages, _ = _fetch_rows(rest_base, page_params, soft_fail=soft_fail)
            if not chunk:
                break
            collected.extend(chunk)
            wp_page += 1
        return collected[:cap]

    def _paginate_with_status_fallback(
        rest_base: str,
        req_params: dict[str, Any],
        *,
        cap: int,
        soft_fail: bool,
    ) -> list[dict[str, Any]]:
        """Try status=any + context=edit; fallback to publish/view if WP rejects."""
        rows = _paginate_resource(rest_base, req_params, cap=cap, soft_fail=True)
        if rows:
            return rows
        fallback = dict(req_params)
        fallback["status"] = "publish"
        fallback["context"] = "view"
        return _paginate_resource(rest_base, fallback, cap=cap, soft_fail=soft_fail)

    cap = max(1, min(int(max_total or 5000), 10000))

    if fetch_all and category_filter:
        posts_params = dict(base_params)
        rows = _paginate_with_status_fallback("posts", posts_params, cap=cap, soft_fail=False)
        items = [_row_to_post(row, type_slug="post", rest_base="posts") for row in rows if isinstance(row, dict)]
        type_counts = {"posts": len(items)}
        logger.info(
            "cau_scan site_id=%s mode=category category=%s type_counts=%s total=%d",
            site_id, cat_raw, type_counts, len(items),
        )
        return {
            "posts": items,
            "page": 1,
            "per_page": len(items),
            "has_more": len(rows) >= cap,
            "total": len(items),
            "type_counts": type_counts,
        }

    if fetch_all and not category_filter:
        rest_types = _fetch_wp_public_rest_types(base=base, headers=headers, auth=auth)
        # Prefer posts/pages first so a broken CPT cannot block the whole scan.
        def _type_rank(info: dict[str, str]) -> tuple[int, str]:
            rb = str(info.get("rest_base") or "")
            if rb == "posts":
                return (0, rb)
            if rb == "pages":
                return (1, rb)
            return (2, rb)

        rest_types = sorted(rest_types, key=_type_rank)
        all_items: list[dict[str, Any]] = []
        type_counts: dict[str, int] = {}
        skipped: list[str] = []
        seen_keys: set[str] = set()
        seen_links: set[str] = set()

        for type_info in rest_types:
            rest_base = str(type_info.get("rest_base") or "")
            type_slug = str(type_info.get("slug") or rest_base)
            if not rest_base:
                continue
            req_params = dict(base_params)
            req_params.pop("categories", None)
            # Core types: hard fail only if posts also fails after fallback.
            soft = rest_base not in {"posts", "pages"}
            try:
                rows = _paginate_with_status_fallback(
                    rest_base,
                    req_params,
                    cap=cap,
                    soft_fail=soft,
                )
            except HTTPException:
                if soft:
                    skipped.append(rest_base)
                    type_counts[rest_base] = 0
                    continue
                raise
            if not rows and soft:
                skipped.append(rest_base)
            type_counts[rest_base] = len(rows)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = _row_to_post(row, type_slug=type_slug, rest_base=rest_base)
                if not item["id"]:
                    continue
                dedupe_key = f"{item['type']}:{item['id']}"
                link_key = item.get("link") or ""
                if dedupe_key in seen_keys:
                    continue
                if link_key and link_key in seen_links:
                    continue
                seen_keys.add(dedupe_key)
                if link_key:
                    seen_links.add(link_key)
                all_items.append(item)

        if not all_items and not type_counts.get("posts") and not type_counts.get("pages"):
            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "Không lấy được bài/trang từ WordPress. "
                        "Kiểm tra Application Password, quyền REST API, hoặc thử quét theo danh mục."
                    ),
                    "code": "wp_scan_empty",
                    "skipped": skipped,
                },
            )

        all_items.sort(key=lambda x: str(x.get("modified") or x.get("date") or ""), reverse=True)
        logger.info(
            "cau_scan site_id=%s mode=whole_site type_counts=%s skipped=%s total=%d",
            site_id, type_counts, skipped, len(all_items),
        )
        return {
            "posts": all_items,
            "page": 1,
            "per_page": len(all_items),
            "has_more": False,
            "total": len(all_items),
            "type_counts": type_counts,
        }

    # Paginated slice (legacy / load-more path)
    posts: list[dict[str, Any]] = []
    wp_page = page
    total_pages = 0
    list_params = dict(base_params)
    list_params["per_page"] = per_page
    while len(posts) < per_page:
        list_params["page"] = wp_page
        post_rows, total_pages, _ = _fetch_rows("posts", list_params, soft_fail=False)
        if not post_rows:
            # Fallback publish/view for paginated path
            if wp_page == page and list_params.get("status") == "any":
                list_params["status"] = "publish"
                list_params["context"] = "view"
                post_rows, total_pages, _ = _fetch_rows("posts", list_params, soft_fail=False)
                if not post_rows:
                    break
            else:
                break
        for row in post_rows:
            if not isinstance(row, dict):
                continue
            posts.append(_row_to_post(row, type_slug="post", rest_base="posts"))
            if len(posts) >= per_page:
                break
        if total_pages and wp_page >= total_pages:
            break
        wp_page += 1

    has_more = bool(total_pages and wp_page < total_pages) or len(posts) >= per_page
    return {
        "posts": posts[:per_page],
        "page": page,
        "per_page": per_page,
        "has_more": has_more,
        "total": None,
        "type_counts": {"posts": len(posts[:per_page])},
    }


def _rest_resource_for_type(post_type: str = "", rest_base: str = "") -> str:
    rb = str(rest_base or "").strip().strip("/")
    if rb:
        return rb
    pt = str(post_type or "post").strip().lower()
    if pt in {"page", "pages"}:
        return "pages"
    if pt in {"post", "posts", ""}:
        return "posts"
    return pt


def _normalize_wp_post_payload(post: dict[str, Any], *, post_type: str, post_url: str = "") -> dict[str, Any]:
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
        "slug": str(post.get("slug") or ""),
        "modified": str(post.get("modified") or post.get("modified_gmt") or ""),
        "modified_gmt": str(post.get("modified_gmt") or post.get("modified") or ""),
    }


def _fetch_by_id(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    wp_id: int,
    resource: str,
) -> dict[str, Any] | None:
    if int(wp_id or 0) <= 0:
        return None
    # Prefer edit (raw content); fall back to view for published posts.
    param_sets: list[dict[str, str]] = [
        {"context": "edit"},
        {"context": "view"},
        {},
    ]
    for params in param_sets:
        resp, _ = wp_get_json(
            f"/wp-json/wp/v2/{resource}/{int(wp_id)}",
            url=base,
            headers=headers,
            auth=auth,
            params=params,
            timeout=30,
        )
        if resp.status_code >= 400:
            continue
        try:
            row = parse_wp_response_json(resp)
        except ValueError:
            continue
        if isinstance(row, dict) and int(row.get("id") or 0) == int(wp_id):
            return row
    return None


def fetch_post_by_id(
    *,
    site_id: str,
    user_id: int,
    wp_id: int,
    post_type: str = "post",
    rest_base: str = "",
    post_url: str = "",
) -> dict[str, Any]:
    """Fetch a WP post/page/CPT by numeric ID (preferred for Auto Update modal)."""
    cred = get_site_credentials(site_id, user_id)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])

    primary = _rest_resource_for_type(post_type, rest_base)
    candidates: list[str] = []
    for res in (primary, "posts", "pages"):
        if res and res not in candidates:
            candidates.append(res)

    post: dict[str, Any] | None = None
    used_resource = primary
    for resource in candidates:
        post = _fetch_by_id(
            base=base,
            headers=headers,
            auth=auth,
            wp_id=int(wp_id),
            resource=resource,
        )
        if post:
            used_resource = resource
            break

    if not post:
        if str(post_url or "").strip():
            try:
                return fetch_post_by_url(
                    site_id=site_id,
                    user_id=user_id,
                    post_url=post_url,
                    post_type=post_type,
                    rest_base=rest_base,
                )
            except HTTPException:
                pass
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy bài viết/trang qua REST API (theo ID).",
        )

    resolved_type = str(post_type or "").strip().lower()
    if not resolved_type or resolved_type in {"post", "posts"}:
        resolved_type = "page" if used_resource == "pages" else (
            used_resource if used_resource not in {"posts", "pages"} else "post"
        )
    elif used_resource == "pages":
        resolved_type = "page"

    return _normalize_wp_post_payload(post, post_type=resolved_type, post_url=post_url)


def fetch_post_by_url(
    *,
    site_id: str,
    user_id: int,
    post_url: str,
    post_type: str = "",
    rest_base: str = "",
) -> dict[str, Any]:
    cred = get_site_credentials(site_id, user_id)
    base = cred["url"]
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])
    slug = _slug_from_url(post_url, base)
    if not slug:
        raise HTTPException(status_code=400, detail="URL không thuộc site đã kết nối hoặc không đọc được slug.")

    preferred = _rest_resource_for_type(post_type, rest_base) if (post_type or rest_base) else ""
    resources: list[str] = []
    for res in (preferred, "posts", "pages"):
        if res and res not in resources:
            resources.append(res)

    post: dict[str, Any] | None = None
    used_resource = "posts"
    for resource in resources:
        post = _fetch_by_slug(base=base, headers=headers, auth=auth, slug=slug, resource=resource)
        if post:
            used_resource = resource
            break
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết/trang qua REST API.")

    resolved_type = str(post_type or "").strip().lower()
    if not resolved_type:
        resolved_type = "page" if used_resource == "pages" else "post"
    elif used_resource == "pages":
        resolved_type = "page"

    return _normalize_wp_post_payload(post, post_type=resolved_type, post_url=post_url)
