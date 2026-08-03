"""Persisted scan results for Content Auto Update (per user + site + scope)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.user_scope import belongs_to_user

SCAN_CACHE_FILE = Path("data/content_auto_update_scan_cache.json")
MAX_CACHE_ENTRIES_PER_USER = 80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_store() -> dict[str, Any]:
    if not SCAN_CACHE_FILE.exists():
        return {"caches": [], "post_scores": []}
    try:
        raw = json.loads(SCAN_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"caches": [], "post_scores": []}
    if not isinstance(raw, dict):
        return {"caches": [], "post_scores": []}
    caches = raw.get("caches") if isinstance(raw.get("caches"), list) else []
    scores = raw.get("post_scores") if isinstance(raw.get("post_scores"), list) else []
    return {
        "caches": [x for x in caches if isinstance(x, dict)],
        "post_scores": [x for x in scores if isinstance(x, dict)],
    }


def _write_store(store: dict[str, Any]) -> None:
    SCAN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCAN_CACHE_FILE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def scan_scope_key(
    *,
    site_id: str,
    category_id: str = "",
    status: str = "all",
    search: str = "",
) -> str:
    cat = str(category_id or "").strip()
    scope = "category" if cat and cat.lower() not in {"all", "0", ""} else "whole_site"
    return "|".join([
        str(site_id or "").strip(),
        scope,
        cat,
        str(status or "all").strip().lower(),
        str(search or "").strip().lower(),
    ])


def score_level_from_score(score: int | None) -> str | None:
    if score is None:
        return None
    n = int(score)
    if n < 20:
        return "very_weak"
    if n < 50:
        return "urgent"
    if n < 80:
        return "optimize"
    return "good"


def score_level_label(level: str | None) -> str:
    labels = {
        "very_weak": "Rất yếu",
        "urgent": "Cần sửa gấp",
        "optimize": "Nên tối ưu",
        "good": "Đã ổn",
    }
    return labels.get(str(level or ""), "—")


def priority_from_score(score: int | None) -> str:
    if score is None:
        return "Trung bình"
    n = int(score)
    if n < 50:
        return "Rất cao"
    if n < 80:
        return "Cao"
    return "Thấp"


def priority_warning(score: int | None) -> str:
    if score is None:
        return ""
    if int(score) < 20:
        return "Bài quá yếu, nên viết lại hoặc tối ưu lớn."
    return ""


def _post_dedupe_key(*, site_id: str, post_type: str, post_id: int, url: str = "") -> str:
    return f"{site_id}|{post_type}|{post_id}"


def _normalize_wp_row(row: dict[str, Any]) -> dict[str, Any]:
    post_id = int(row.get("post_id") or row.get("id") or 0)
    post_type = str(row.get("post_type") or row.get("type") or "post")
    url = str(row.get("url") or row.get("link") or "")
    seo_score = row.get("seo_score")
    if seo_score is not None and seo_score != "":
        try:
            seo_score = int(seo_score)
        except (TypeError, ValueError):
            seo_score = None
    else:
        seo_score = None
    level = row.get("score_level") or score_level_from_score(seo_score)
    return {
        "post_id": post_id,
        "post_type": post_type,
        "type": post_type,
        "rest_base": str(row.get("rest_base") or post_type),
        "title": str(row.get("title") or ""),
        "url": url,
        "link": url,
        "slug": str(row.get("slug") or ""),
        "status": str(row.get("status") or ""),
        "modified": str(row.get("modified") or ""),
        "date": str(row.get("date") or ""),
        "seo_score": seo_score,
        "score_level": level,
        "priority": row.get("priority") or priority_from_score(seo_score),
        "scanned_at": str(row.get("scanned_at") or ""),
    }


def _lookup_post_score(
    store: dict[str, Any],
    *,
    user_id: int,
    site_id: str,
    post_type: str,
    post_id: int,
) -> dict[str, Any] | None:
    for row in store.get("post_scores") or []:
        if not belongs_to_user(row, user_id):
            continue
        if str(row.get("site_id")) != str(site_id):
            continue
        if str(row.get("post_type")) != str(post_type):
            continue
        if int(row.get("post_id") or 0) != int(post_id):
            continue
        return row
    return None


def upsert_post_score(
    *,
    user_id: int,
    site_id: str,
    post_id: int,
    post_type: str,
    url: str = "",
    slug: str = "",
    title: str = "",
    status: str = "",
    modified: str = "",
    seo_score: int | None,
) -> dict[str, Any]:
    store = _read_store()
    scores: list[dict[str, Any]] = list(store.get("post_scores") or [])
    level = score_level_from_score(seo_score)
    entry = {
        "user_id": int(user_id),
        "site_id": str(site_id),
        "post_id": int(post_id),
        "post_type": str(post_type or "post"),
        "url": str(url or ""),
        "slug": str(slug or ""),
        "title": str(title or ""),
        "status": str(status or ""),
        "modified": str(modified or ""),
        "seo_score": seo_score,
        "score_level": level,
        "priority": priority_from_score(seo_score),
        "scored_at": _now(),
    }
    replaced = False
    for i, row in enumerate(scores):
        if (
            belongs_to_user(row, user_id)
            and str(row.get("site_id")) == str(site_id)
            and str(row.get("post_type")) == str(post_type)
            and int(row.get("post_id") or 0) == int(post_id)
        ):
            scores[i] = {**row, **entry}
            replaced = True
            break
    if not replaced:
        scores.append(entry)
    store["post_scores"] = scores
    _write_store(store)
    _sync_score_into_caches(
        user_id=user_id,
        site_id=site_id,
        post_id=post_id,
        post_type=post_type,
        seo_score=seo_score,
        modified=modified,
    )
    return entry


def _sync_score_into_caches(
    *,
    user_id: int,
    site_id: str,
    post_id: int,
    post_type: str,
    seo_score: int | None,
    modified: str = "",
) -> None:
    store = _read_store()
    caches: list[dict[str, Any]] = list(store.get("caches") or [])
    level = score_level_from_score(seo_score)
    priority = priority_from_score(seo_score)
    changed = False
    for cache in caches:
        if not belongs_to_user(cache, user_id):
            continue
        if str(cache.get("site_id")) != str(site_id):
            continue
        posts = cache.get("posts") or []
        for post in posts:
            if not isinstance(post, dict):
                continue
            if int(post.get("post_id") or post.get("id") or 0) != int(post_id):
                continue
            if str(post.get("post_type") or post.get("type") or "") != str(post_type):
                continue
            post["seo_score"] = seo_score
            post["score_level"] = level
            post["priority"] = priority
            if modified:
                post["modified"] = modified
            changed = True
        if changed:
            cache["posts"] = posts
    if changed:
        store["caches"] = caches
        _write_store(store)


def merge_wp_posts_with_scores(
    *,
    user_id: int,
    site_id: str,
    wp_posts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    store = _read_store()
    scanned_at = _now()
    seen: set[str] = set()
    seen_links: set[str] = set()
    out: list[dict[str, Any]] = []

    for row in wp_posts:
        if not isinstance(row, dict):
            continue
        post_id = int(row.get("id") or 0)
        post_type = str(row.get("type") or "post")
        if not post_id:
            continue
        dedupe = _post_dedupe_key(site_id=site_id, post_type=post_type, post_id=post_id)
        link = str(row.get("link") or "")
        if dedupe in seen:
            continue
        if link and link in seen_links:
            continue
        seen.add(dedupe)
        if link:
            seen_links.add(link)

        cached = _lookup_post_score(
            store,
            user_id=user_id,
            site_id=site_id,
            post_type=post_type,
            post_id=post_id,
        )
        seo_score = None
        if cached and cached.get("seo_score") is not None:
            cached_mod = str(cached.get("modified") or "")
            wp_mod = str(row.get("modified") or "")
            if not wp_mod or not cached_mod or wp_mod == cached_mod:
                seo_score = int(cached.get("seo_score"))

        item = _normalize_wp_row({
            "post_id": post_id,
            "post_type": post_type,
            "type": post_type,
            "rest_base": row.get("rest_base"),
            "title": row.get("title"),
            "url": link,
            "link": link,
            "slug": row.get("slug"),
            "status": row.get("status"),
            "modified": row.get("modified"),
            "date": row.get("date"),
            "seo_score": seo_score,
            "scanned_at": scanned_at,
        })
        out.append(item)
    return out


def get_scan_cache(
    *,
    user_id: int,
    site_id: str,
    category_id: str = "",
    status: str = "all",
    search: str = "",
) -> dict[str, Any] | None:
    key = scan_scope_key(
        site_id=site_id,
        category_id=category_id,
        status=status,
        search=search,
    )
    store = _read_store()
    matches = [
        c for c in (store.get("caches") or [])
        if belongs_to_user(c, user_id) and str(c.get("scope_key") or "") == key
    ]
    if not matches:
        return None
    cache = sorted(matches, key=lambda x: str(x.get("scanned_at") or ""), reverse=True)[0]
    posts = [_normalize_wp_row(p) for p in (cache.get("posts") or []) if isinstance(p, dict)]
    return {
        "id": cache.get("id"),
        "scope_key": key,
        "scanned_at": cache.get("scanned_at"),
        "type_counts": cache.get("type_counts") or {},
        "posts": posts,
    }


def save_scan_cache(
    *,
    user_id: int,
    site_id: str,
    category_id: str = "",
    status: str = "all",
    search: str = "",
    posts: list[dict[str, Any]],
    type_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    store = _read_store()
    caches: list[dict[str, Any]] = list(store.get("caches") or [])
    key = scan_scope_key(
        site_id=site_id,
        category_id=category_id,
        status=status,
        search=search,
    )
    scope = "category" if str(category_id or "").strip() else "whole_site"
    scanned_at = _now()
    normalized = [_normalize_wp_row(p) for p in posts if isinstance(p, dict)]

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "site_id": str(site_id),
        "scope": scope,
        "scope_key": key,
        "category_id": str(category_id or ""),
        "status": str(status or "all"),
        "search": str(search or ""),
        "scanned_at": scanned_at,
        "type_counts": type_counts or {},
        "posts": normalized,
    }

    replaced = False
    for i, row in enumerate(caches):
        if belongs_to_user(row, user_id) and str(row.get("scope_key") or "") == key:
            entry["id"] = row.get("id") or entry["id"]
            caches[i] = entry
            replaced = True
            break
    if not replaced:
        caches.append(entry)

    user_caches = [c for c in caches if belongs_to_user(c, user_id)]
    if len(user_caches) > MAX_CACHE_ENTRIES_PER_USER:
        drop = sorted(user_caches, key=lambda x: str(x.get("scanned_at") or ""))[: len(user_caches) - MAX_CACHE_ENTRIES_PER_USER]
        drop_ids = {str(d.get("id")) for d in drop}
        caches = [c for c in caches if str(c.get("id")) not in drop_ids]

    store["caches"] = caches

    scores: list[dict[str, Any]] = list(store.get("post_scores") or [])
    for post in normalized:
        if post.get("seo_score") is None:
            continue
        pid = int(post.get("post_id") or 0)
        ptype = str(post.get("post_type") or "post")
        score_entry = {
            "user_id": int(user_id),
            "site_id": str(site_id),
            "post_id": pid,
            "post_type": ptype,
            "url": str(post.get("url") or ""),
            "slug": str(post.get("slug") or ""),
            "title": str(post.get("title") or ""),
            "status": str(post.get("status") or ""),
            "modified": str(post.get("modified") or ""),
            "seo_score": int(post.get("seo_score")),
            "score_level": post.get("score_level"),
            "priority": post.get("priority"),
            "scored_at": scanned_at,
        }
        replaced_score = False
        for i, row in enumerate(scores):
            if (
                belongs_to_user(row, user_id)
                and str(row.get("site_id")) == str(site_id)
                and str(row.get("post_type")) == ptype
                and int(row.get("post_id") or 0) == pid
            ):
                scores[i] = {**row, **score_entry}
                replaced_score = True
                break
        if not replaced_score:
            scores.append(score_entry)
    store["post_scores"] = scores
    _write_store(store)

    return entry
