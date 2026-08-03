"""Social Auto — Web 2.0 multi-platform (tách khỏi Content AI Publish)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.services.user_scope import belongs_to_user, is_admin_role
from app.services.web20_platform_status import account_card_status
from app.services.web20_providers.base import PLATFORMS

ACCOUNTS_FILE = Path("data/social_auto_web20_accounts.json")
POSTS_FILE = Path("data/social_auto_web20_posts.json")
LOGS_FILE = Path("data/social_auto_web20_logs.json")
MAX_ACCOUNTS = 30
MAX_POSTS = 500
MAX_LOGS = 300
WP_STATUSES = frozenset({"draft", "publish", "pending", "private", "queue"})
POST_STATUSES = frozenset({"draft", "ready", "published", "failed", "manual", "scheduled", "publishing", "retrying", "cancelled"})
SETTINGS_FILE = Path("data/social_auto_web20_settings.json")
MAX_POSTS_PER_ACCOUNT_PER_DAY = 3
MAX_PUBLISH_RETRIES = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [x for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


def _write_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_account(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("platform"):
        row["platform"] = "wordpress_2_0"
    return row


def _account_platform(row: dict[str, Any]) -> str:
    return str(row.get("platform") or "wordpress_2_0")


def _owned_rows(items: list[dict[str, Any]], user_id: int, role: str | None = None) -> list[dict[str, Any]]:
    if is_admin_role(role):
        return items
    return [x for x in items if belongs_to_user(x, user_id)]


def _find_account(account_id: str, user_id: int, role: str | None = None) -> dict[str, Any] | None:
    for row in _read_list(ACCOUNTS_FILE):
        if str(row.get("id")) != str(account_id):
            continue
        if is_admin_role(role) or belongs_to_user(row, user_id):
            return _normalize_account(row)
    return None


def _find_post(post_id: str, user_id: int, role: str | None = None) -> dict[str, Any] | None:
    for row in _read_list(POSTS_FILE):
        if str(row.get("id")) != str(post_id):
            continue
        if is_admin_role(role) or belongs_to_user(row, user_id):
            return row
    return None


def _connection_mode(row: dict[str, Any]) -> str:
    pf = _account_platform(row)
    if pf == "google_sites_manual":
        return "manual"
    if pf == "medium":
        tok = decrypt_secret(str(row.get("integration_token") or "")).strip()
        return "live" if tok and tok != "mock_medium_token" else ("mock" if tok == "mock_medium_token" else "error")
    if pf == "blogger":
        from app.services.web20_providers.blogger import is_mock_mode

        return "mock" if is_mock_mode() else "live"
    if pf == "tumblr":
        from app.services.web20_providers.tumblr import is_mock_mode

        return "mock" if is_mock_mode() else "live"
    return str(row.get("status") or "connected")


def _public_account(row: dict[str, Any]) -> dict[str, Any]:
    row = _normalize_account(row)
    mode = _connection_mode(row)
    pf = _account_platform(row)
    has_creds = True
    if pf == "medium":
        has_creds = bool(decrypt_secret(str(row.get("integration_token") or "")).strip())
    elif pf == "wordpress_2_0":
        has_creds = bool(decrypt_secret(str(row.get("app_password") or "")).strip())
    elif pf in {"blogger", "tumblr"}:
        has_creds = bool(decrypt_secret(str(row.get("access_token") or "")).strip())
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "platform": pf,
        "label": row.get("label") or row.get("site_url") or pf,
        "site_url": row.get("site_url"),
        "username": row.get("username"),
        "external_id": row.get("external_id") or "",
        "is_active": bool(row.get("is_active", True)),
        "blogs": row.get("blogs") or [],
        "default_status": row.get("default_status") or "draft",
        "status": row.get("status") or "connected",
        "connection_mode": mode,
        "has_credentials": has_creds,
        "card_status": account_card_status(
            {
                "platform": pf,
                "has_credentials": has_creds,
                "status": row.get("status") or "connected",
                "connection_mode": mode,
                "last_test_message": row.get("last_test_message") or "",
            }
        ),
        "connected_at": row.get("connected_at"),
        "last_test_at": row.get("last_test_at"),
        "last_test_message": row.get("last_test_message"),
        "main_site_url": row.get("main_site_url") or "",
    }


def _public_post(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id"),
        "account_id": row.get("account_id"),
        "platform": row.get("platform") or "",
        "campaign_id": row.get("campaign_id"),
        "title": row.get("title") or "",
        "slug": row.get("slug") or "",
        "excerpt": row.get("excerpt") or "",
        "html_content": row.get("html_content") or "",
        "tags": row.get("tags") or [],
        "category": row.get("category") or "",
        "status": row.get("status") or "draft",
        "wp_status": row.get("wp_status") or "draft",
        "main_site_url": row.get("main_site_url") or "",
        "source_title": row.get("source_title") or "",
        "source_content": row.get("source_content") or "",
        "safety_score": row.get("safety_score"),
        "safety_passed": row.get("safety_passed"),
        "published_url": row.get("published_url"),
        "wp_post_id": row.get("wp_post_id"),
        "external_id": row.get("external_id"),
        "manual_package": row.get("manual_package"),
        "error_message": row.get("error_message"),
        "scheduled_at": row.get("scheduled_at"),
        "retry_count": int(row.get("retry_count") or 0),
        "last_error_at": row.get("last_error_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "published_at": row.get("published_at"),
    }


def get_account_credentials(account_id: str, user_id: int) -> dict[str, str]:
    """Backward-compatible helper — WordPress 2.0 credentials."""
    secrets = get_account_secrets(account_id, user_id)
    if secrets.get("platform") != "wordpress_2_0":
        raise HTTPException(status_code=400, detail="Account không phải WordPress 2.0.")
    pwd = str(secrets.get("app_password") or "").strip()
    if not pwd:
        raise HTTPException(status_code=400, detail="Application Password không hợp lệ.")
    return {
        "site_url": str(secrets.get("site_url") or ""),
        "username": str(secrets.get("username") or ""),
        "app_password": pwd,
        "default_status": str(secrets.get("default_status") or "draft"),
    }


def get_account_secrets(account_id: str, user_id: int) -> dict[str, Any]:
    row = _find_account(account_id, user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản Web 2.0.")
    platform = _account_platform(row)
    secrets: dict[str, Any] = {
        "platform": platform,
        "default_status": str(row.get("default_status") or "draft"),
        "external_id": str(row.get("external_id") or ""),
        "main_site_url": str(row.get("main_site_url") or ""),
    }
    if platform == "wordpress_2_0":
        pwd = decrypt_secret(str(row.get("app_password") or "")).strip()
        secrets.update(
            {
                "site_url": str(row.get("site_url") or ""),
                "username": str(row.get("username") or ""),
                "app_password": pwd,
            }
        )
    elif platform in {"blogger", "tumblr"}:
        secrets["access_token"] = decrypt_secret(str(row.get("access_token") or "")).strip()
        secrets["refresh_token"] = decrypt_secret(str(row.get("refresh_token") or "")).strip()
        secrets["blog_id"] = str(row.get("external_id") or "")
    elif platform == "medium":
        secrets["integration_token"] = decrypt_secret(str(row.get("integration_token") or "")).strip()
        secrets["medium_user_id"] = str(row.get("external_id") or "")
    return secrets


def list_accounts(user_id: int, *, platform: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    rows = [_public_account(_normalize_account(x)) for x in _owned_rows(_read_list(ACCOUNTS_FILE), user_id, role)]
    if platform:
        pf = str(platform).strip().lower()
        rows = [r for r in rows if r.get("platform") == pf]
    return rows


def _ensure_account_quota(user_id: int) -> None:
    owned = [x for x in _read_list(ACCOUNTS_FILE) if belongs_to_user(x, user_id)]
    if len(owned) >= MAX_ACCOUNTS:
        raise HTTPException(status_code=400, detail=f"Tối đa {MAX_ACCOUNTS} tài khoản Web 2.0.")


def create_account(
    *,
    user_id: int,
    site_url: str,
    username: str,
    app_password: str,
    label: str = "",
    default_status: str = "draft",
) -> dict[str, Any]:
    if default_status not in WP_STATUSES:
        default_status = "draft"
    _ensure_account_quota(user_id)
    row = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "platform": "wordpress_2_0",
        "label": (label or site_url).strip()[:120],
        "site_url": site_url.strip().rstrip("/"),
        "username": username.strip(),
        "app_password": encrypt_secret(app_password.strip()),
        "external_id": "",
        "is_active": True,
        "blogs": [],
        "default_status": default_status,
        "status": "connected",
        "connected_at": _now(),
        "last_test_at": None,
        "last_test_message": "",
    }
    items = _read_list(ACCOUNTS_FILE)
    items.append(row)
    _write_list(ACCOUNTS_FILE, items)
    return _public_account(row)


def create_oauth_account(
    *,
    user_id: int,
    platform: str,
    access_token: str,
    refresh_token: str = "",
    blogs: list[dict[str, Any]] | None = None,
    external_id: str = "",
    label: str = "",
    default_status: str = "draft",
) -> dict[str, Any]:
    pf = str(platform or "").strip().lower()
    if pf not in PLATFORMS or pf in {"wordpress_2_0", "medium", "google_sites_manual"}:
        raise HTTPException(status_code=400, detail=f"Platform OAuth không hỗ trợ: {platform}")
    if default_status not in WP_STATUSES:
        default_status = "draft"
    _ensure_account_quota(user_id)
    blog_list = blogs or []
    active_id = external_id or (str(blog_list[0]["id"]) if blog_list else "")
    row = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "platform": pf,
        "label": (label or f"{pf} account").strip()[:120],
        "site_url": str(blog_list[0].get("url") if blog_list else ""),
        "username": "",
        "access_token": encrypt_secret(access_token.strip()),
        "refresh_token": encrypt_secret(refresh_token.strip()) if refresh_token else "",
        "external_id": active_id,
        "is_active": True,
        "blogs": blog_list,
        "default_status": default_status,
        "status": "connected",
        "connected_at": _now(),
        "last_test_at": None,
        "last_test_message": "",
    }
    items = _read_list(ACCOUNTS_FILE)
    items.append(row)
    _write_list(ACCOUNTS_FILE, items)
    return _public_account(row)


def create_medium_account(
    *,
    user_id: int,
    integration_token: str,
    medium_user_id: str,
    label: str = "",
    default_status: str = "draft",
) -> dict[str, Any]:
    if default_status not in WP_STATUSES:
        default_status = "draft"
    _ensure_account_quota(user_id)
    row = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "platform": "medium",
        "label": (label or "Medium").strip()[:120],
        "site_url": "",
        "username": "",
        "integration_token": encrypt_secret(integration_token.strip()),
        "external_id": str(medium_user_id or "").strip(),
        "is_active": True,
        "blogs": [],
        "default_status": default_status,
        "status": "connected",
        "connected_at": _now(),
        "last_test_at": None,
        "last_test_message": "",
    }
    items = _read_list(ACCOUNTS_FILE)
    items.append(row)
    _write_list(ACCOUNTS_FILE, items)
    return _public_account(row)


def create_manual_account(
    *,
    user_id: int,
    label: str = "Google Sites Manual",
    site_url: str = "",
    main_site_url: str = "",
) -> dict[str, Any]:
    _ensure_account_quota(user_id)
    row = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "platform": "google_sites_manual",
        "label": label.strip()[:120] or "Google Sites Manual",
        "site_url": site_url.strip()[:2000],
        "main_site_url": main_site_url.strip()[:2000],
        "username": "",
        "external_id": "",
        "is_active": True,
        "blogs": [],
        "default_status": "draft",
        "status": "connected",
        "connected_at": _now(),
        "last_test_at": None,
        "last_test_message": "",
    }
    items = _read_list(ACCOUNTS_FILE)
    items.append(row)
    _write_list(ACCOUNTS_FILE, items)
    return _public_account(row)


def update_account(account_id: str, user_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    items = _read_list(ACCOUNTS_FILE)
    found: dict[str, Any] | None = None
    for i, row in enumerate(items):
        if str(row.get("id")) != str(account_id) or not belongs_to_user(row, user_id):
            continue
        if patch.get("label") is not None:
            row["label"] = str(patch["label"]).strip()[:120]
        if patch.get("site_url") is not None:
            row["site_url"] = str(patch["site_url"]).strip().rstrip("/")
        if patch.get("username") is not None:
            row["username"] = str(patch["username"]).strip()
        if patch.get("app_password"):
            row["app_password"] = encrypt_secret(str(patch["app_password"]).strip())
        if patch.get("default_status") is not None:
            ds = str(patch["default_status"]).strip().lower()
            if ds in WP_STATUSES:
                row["default_status"] = ds
        if patch.get("last_test_at") is not None:
            row["last_test_at"] = patch["last_test_at"]
        if patch.get("last_test_message") is not None:
            row["last_test_message"] = patch["last_test_message"]
        if patch.get("status") is not None:
            row["status"] = patch["status"]
        if patch.get("external_id") is not None:
            row["external_id"] = str(patch["external_id"]).strip()
        if patch.get("is_active") is not None:
            row["is_active"] = bool(patch["is_active"])
        if patch.get("blogs") is not None:
            row["blogs"] = patch["blogs"]
        if patch.get("main_site_url") is not None:
            row["main_site_url"] = str(patch["main_site_url"]).strip()[:2000]
        if patch.get("access_token"):
            row["access_token"] = encrypt_secret(str(patch["access_token"]).strip())
        if patch.get("refresh_token"):
            row["refresh_token"] = encrypt_secret(str(patch["refresh_token"]).strip())
        items[i] = row
        found = _public_account(row)
        break
    if not found:
        return None
    _write_list(ACCOUNTS_FILE, items)
    return found


def delete_account(account_id: str, user_id: int) -> bool:
    items = _read_list(ACCOUNTS_FILE)
    new_items = []
    deleted = False
    for row in items:
        if str(row.get("id")) == str(account_id) and belongs_to_user(row, user_id):
            deleted = True
            continue
        new_items.append(row)
    if not deleted:
        return False
    _write_list(ACCOUNTS_FILE, new_items)
    return True


def list_posts(user_id: int, *, account_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    rows = [_public_post(x) for x in _owned_rows(_read_list(POSTS_FILE), user_id, role)]
    if account_id:
        rows = [r for r in rows if str(r.get("account_id")) == str(account_id)]
    rows.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return rows


def create_post(
    *,
    user_id: int,
    account_id: str,
    title: str,
    slug: str = "",
    excerpt: str = "",
    html_content: str = "",
    tags: list[str] | None = None,
    category: str = "",
    wp_status: str = "draft",
    main_site_url: str = "",
    source_title: str = "",
    source_content: str = "",
    campaign_id: str = "",
) -> dict[str, Any]:
    if not _find_account(account_id, user_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản Web 2.0.")
    acc = _find_account(account_id, user_id) or {}
    if wp_status not in WP_STATUSES:
        wp_status = "draft"
    owned = [x for x in _read_list(POSTS_FILE) if belongs_to_user(x, user_id)]
    if len(owned) >= MAX_POSTS:
        raise HTTPException(status_code=400, detail=f"Tối đa {MAX_POSTS} bài Web 2.0.")
    tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()][:20]
    row = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "account_id": str(account_id),
        "platform": _account_platform(acc),
        "campaign_id": str(campaign_id or ""),
        "title": str(title or "").strip()[:500],
        "slug": _slugify(slug or title)[:200],
        "excerpt": str(excerpt or "").strip()[:2000],
        "html_content": str(html_content or "").strip()[:100000],
        "tags": tag_list,
        "category": str(category or "").strip()[:120],
        "status": "draft",
        "wp_status": wp_status,
        "main_site_url": str(main_site_url or "").strip()[:2000],
        "source_title": str(source_title or "").strip()[:500],
        "source_content": str(source_content or "").strip()[:50000],
        "safety_score": None,
        "safety_passed": None,
        "published_url": None,
        "wp_post_id": None,
        "external_id": None,
        "manual_package": None,
        "error_message": None,
        "scheduled_at": None,
        "retry_count": 0,
        "last_error_at": None,
        "next_retry_at": None,
        "created_at": _now(),
        "updated_at": _now(),
        "published_at": None,
    }
    items = _read_list(POSTS_FILE)
    items.insert(0, row)
    _write_list(POSTS_FILE, items)
    return _public_post(row)


def update_post(post_id: str, user_id: int, patch: dict[str, Any], role: str | None = None) -> dict[str, Any] | None:
    items = _read_list(POSTS_FILE)
    found: dict[str, Any] | None = None
    for i, row in enumerate(items):
        if str(row.get("id")) != str(post_id):
            continue
        if not is_admin_role(role) and not belongs_to_user(row, user_id):
            continue
        for key in (
            "title",
            "slug",
            "excerpt",
            "html_content",
            "category",
            "wp_status",
            "main_site_url",
            "status",
            "published_url",
            "wp_post_id",
            "external_id",
            "manual_package",
            "error_message",
            "scheduled_at",
            "retry_count",
            "last_error_at",
            "next_retry_at",
            "safety_score",
            "safety_passed",
            "published_at",
        ):
            if key in patch and patch[key] is not None:
                row[key] = patch[key]
        if "tags" in patch and patch["tags"] is not None:
            row["tags"] = [str(t).strip() for t in patch["tags"] if str(t).strip()][:20]
        if patch.get("slug") is not None or patch.get("title") is not None:
            row["slug"] = _slugify(str(row.get("slug") or row.get("title") or ""))[:200]
        if patch.get("wp_status") is not None:
            ws = str(patch["wp_status"]).lower()
            if ws in WP_STATUSES:
                row["wp_status"] = ws
        row["updated_at"] = _now()
        items[i] = row
        found = _public_post(row)
        break
    if not found:
        return None
    _write_list(POSTS_FILE, items)
    return found


def _slugify(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "bai-viet"


def append_log(
    user_id: int,
    *,
    level: str = "info",
    code: str = "",
    message: str = "",
    account_id: str | None = None,
    post_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": int(user_id),
        "level": level,
        "code": code,
        "message": message[:2000],
        "account_id": account_id,
        "post_id": post_id,
        "meta": meta or {},
        "at": _now(),
    }
    items = _read_list(LOGS_FILE)
    items.insert(0, entry)
    user_logs = [x for x in items if belongs_to_user(x, user_id)]
    if len(user_logs) > MAX_LOGS:
        keep_ids = {x.get("id") for x in user_logs[:MAX_LOGS]}
        items = [x for x in items if not belongs_to_user(x, user_id) or x.get("id") in keep_ids]
    _write_list(LOGS_FILE, items)


def list_logs(user_id: int, *, limit: int = 50, role: str | None = None) -> list[dict[str, Any]]:
    rows = _owned_rows(_read_list(LOGS_FILE), user_id, role)
    return rows[: max(1, min(limit, 200))]


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def count_account_posts_today(account_id: str, user_id: int) -> int:
    """Đếm bài đã publish/ready hôm nay trên account (quota 3/ngày)."""
    today = datetime.now(timezone.utc).date()
    n = 0
    for row in _read_list(POSTS_FILE):
        if not belongs_to_user(row, user_id):
            continue
        if str(row.get("account_id")) != str(account_id):
            continue
        st = str(row.get("status") or "")
        if st not in {"published", "ready", "manual"}:
            continue
        pub = _parse_iso(str(row.get("published_at") or ""))
        if pub and pub.date() == today:
            n += 1
    return n


def list_due_scheduled_posts(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Bài scheduled đến hạn (toàn hệ thống — cho cron)."""
    now = now or datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for row in _read_list(POSTS_FILE):
        if str(row.get("status") or "") != "scheduled":
            continue
        at = _parse_iso(str(row.get("scheduled_at") or ""))
        if at and at <= now:
            due.append(row)
    due.sort(key=lambda x: str(x.get("scheduled_at") or ""))
    return due


def list_retrying_posts(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Bài retrying — retry sau last_error_at + backoff."""
    now = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for row in _read_list(POSTS_FILE):
        if str(row.get("status") or "") != "retrying":
            continue
        retries = int(row.get("retry_count") or 0)
        if retries >= MAX_PUBLISH_RETRIES:
            continue
        nxt = _parse_iso(str(row.get("next_retry_at") or ""))
        if nxt and nxt > now:
            continue
        if not nxt:
            last = _parse_iso(str(row.get("last_error_at") or row.get("updated_at") or ""))
            if last:
                backoff_min = min(30, 5 * max(1, retries))
                if (now - last).total_seconds() < backoff_min * 60:
                    continue
        out.append(row)
    return out


def get_settings(user_id: int) -> dict[str, Any]:
    items = _read_list(SETTINGS_FILE)
    for row in items:
        if belongs_to_user(row, user_id):
            return row
    return {
        "user_id": user_id,
        "max_posts_per_account_per_day": MAX_POSTS_PER_ACCOUNT_PER_DAY,
        "default_wp_status": "draft",
    }


def save_settings(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    items = _read_list(SETTINGS_FILE)
    found = False
    row: dict[str, Any] = get_settings(user_id)
    if patch.get("max_posts_per_account_per_day") is not None:
        row["max_posts_per_account_per_day"] = max(1, min(10, int(patch["max_posts_per_account_per_day"])))
    if patch.get("default_wp_status") is not None:
        ds = str(patch["default_wp_status"]).lower()
        if ds in WP_STATUSES:
            row["default_wp_status"] = ds
    row["user_id"] = int(user_id)
    row["updated_at"] = _now()
    for i, existing in enumerate(items):
        if belongs_to_user(existing, user_id):
            items[i] = row
            found = True
            break
    if not found:
        row["id"] = str(uuid.uuid4())
        items.append(row)
    _write_list(SETTINGS_FILE, items)
    return row
