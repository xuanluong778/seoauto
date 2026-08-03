from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_FILE = Path("data/content_ai_projects.json")
MAX_PROJECTS = 120


def _read_projects() -> list[dict[str, Any]]:
    if not PROJECT_FILE.exists():
        return []
    try:
        raw = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _write_projects(projects: list[dict[str, Any]]) -> None:
    PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_FILE.write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")


from app.services.user_scope import belongs_to_user as _belongs_to_user
from app.services.user_scope import is_admin_role, is_legacy_orphan


def _legacy_owner_missing(entry: dict[str, Any]) -> bool:
    if "user_id" not in entry:
        return True
    raw = entry.get("user_id")
    if raw is None:
        return True
    try:
        return int(raw) <= 0
    except (TypeError, ValueError):
        return not str(raw).strip()


def _migrate_legacy_project_owners(projects: list[dict[str, Any]]) -> bool:
    """Đánh dấu dự án cũ thiếu owner — không gán nhầm cho user đầu tiên mở app."""
    changed = False
    for p in projects:
        if not isinstance(p, dict):
            continue
        if _legacy_owner_missing(p):
            p["legacy_orphan"] = True
            p["user_id"] = 0
            changed = True
    return changed


def _read_projects_scoped(user_id: int) -> list[dict[str, Any]]:
    projects = _read_projects()
    if _migrate_legacy_project_owners(projects):
        _write_projects(projects)
    return projects


def _projects_for_user(projects: list[dict[str, Any]], user_id: int, *, role: str = "user") -> list[dict[str, Any]]:
    if is_admin_role(role):
        return [p for p in projects if isinstance(p, dict)]
    return [p for p in projects if _belongs_to_user(p, user_id) and not is_legacy_orphan(p)]


def save_content_ai_project(
    *,
    user_id: int,
    source_payload: dict[str, Any],
    draft_payload: dict[str, Any],
) -> str:
    projects = _read_projects()
    project_id = str(uuid.uuid4())
    entry = {
        "id": project_id,
        "user_id": int(user_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": str(draft_payload.get("title") or source_payload.get("title") or ""),
        "slug": str(draft_payload.get("slug") or ""),
        "target_website": str(source_payload.get("target_website") or ""),
        "primary_keyword": str(source_payload.get("primary_keyword") or ""),
        "secondary_keywords": source_payload.get("secondary_keywords") or [],
        "outline_content": str(source_payload.get("outline_content") or ""),
        "meta_description": str(draft_payload.get("meta_description") or source_payload.get("meta_description") or ""),
        "tags": draft_payload.get("tags") or source_payload.get("tags") or [],
        "content": str(draft_payload.get("content") or source_payload.get("content") or ""),
        "featured_image": str(source_payload.get("featured_image") or draft_payload.get("featured_image") or ""),
        "gallery_images": source_payload.get("gallery_images") or draft_payload.get("gallery_images") or [],
        "scheduled_at": str(source_payload.get("scheduled_at") or draft_payload.get("scheduled_at") or ""),
        "custom_title": str(source_payload.get("custom_title") or ""),
        "custom_description": str(source_payload.get("custom_description") or ""),
        "custom_outline": str(source_payload.get("custom_outline") or ""),
        "search_volume": int(source_payload.get("search_volume") or 0),
        "content_type": str(source_payload.get("content_type") or ""),
        "competitor_url": str(source_payload.get("competitor_url") or ""),
        "target_word_count": int(source_payload.get("target_word_count") or 0) or 1000,
        "wp_category_id": int(source_payload.get("wp_category_id") or 0),
        "draft_output": draft_payload,
    }
    projects.insert(0, entry)
    del projects[MAX_PROJECTS:]
    _write_projects(projects)
    return project_id


def _strip_html_text(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html or "")
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _content_stats(content: str) -> dict[str, int | float]:
    raw = str(content or "")
    text = _strip_html_text(raw)
    words = len(text.split()) if text else 0
    chars = len(text)
    sentences = 0
    if text:
        sentences = len([p for p in re.split(r"[.!?]+", text) if len(p.strip()) >= 2])
    paragraphs = len(re.findall(r"<p\b", raw, flags=re.IGNORECASE))
    if not paragraphs and text:
        blocks = [x for x in re.split(r"\n{2,}", text) if x.strip()]
        paragraphs = len(blocks) if blocks else 1
    page_count = round(words / 260, 2) if words else 0.0
    return {
        "word_count": words,
        "char_count": chars,
        "sentence_count": sentences,
        "paragraph_count": paragraphs,
        "page_count": page_count,
    }


def _first_line(text: str) -> str:
    parts = [x.strip() for x in str(text or "").replace("\r", "").split("\n") if x.strip()]
    return parts[0] if parts else str(text or "").strip()


def _normalize_target_site(url: str) -> str:
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


def _normalize_keyword(pk: str) -> str:
    return re.sub(r"\s+", " ", str(pk or "").strip()).lower()


def find_project_by_site_keyword(
    user_id: int,
    target_website: str,
    primary_keyword: str,
) -> dict[str, Any] | None:
    site = _normalize_target_site(target_website)
    pk = _normalize_keyword(primary_keyword)
    if not site or not pk:
        return None
    for p in _projects_for_user(_read_projects_scoped(user_id), user_id):
        if _normalize_target_site(str(p.get("target_website") or "")) != site:
            continue
        if _normalize_keyword(str(p.get("primary_keyword") or "")) != pk:
            continue
        return p
    return None


def upsert_bulk_setup_projects(
    *,
    user_id: int,
    target_website: str,
    items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Lưu bài setup (keyword + title/meta/outline) chưa có content — tab Lưu nháp."""
    site = str(target_website or "").strip()
    if not site or not items:
        return []
    projects = _read_projects_scoped(user_id)
    results: list[dict[str, str]] = []
    changed = False

    for raw in items:
        kw = re.sub(r"\s+", " ", str(raw.get("keyword") or "").strip())
        if not kw:
            continue
        title = _first_line(str(raw.get("custom_title") or "")) or kw
        meta = _first_line(str(raw.get("custom_description") or ""))
        outline = str(raw.get("custom_outline") or "").strip()
        try:
            sv = int(raw.get("search_volume") or 0)
        except (TypeError, ValueError):
            sv = 0
        try:
            twc = int(raw.get("target_word_count") or 0)
        except (TypeError, ValueError):
            twc = 0
        twc = max(200, min(8000, twc)) if twc >= 200 else 1000

        sec_list: list[str] = []
        sk = raw.get("secondary_keywords")
        if isinstance(sk, list):
            sec_list = [str(x).strip() for x in sk if str(x).strip()]
        elif isinstance(sk, str):
            sec_list = [x.strip() for x in re.split(r"[,;\n\r]+", sk) if x.strip()]
        try:
            wpc_raw = int(raw.get("wp_category_id") or 0)
        except (TypeError, ValueError):
            wpc_raw = 0
        if wpc_raw < 0:
            wpc_raw = 0

        existing_idx: int | None = None
        site_norm = _normalize_target_site(site)
        pk_norm = _normalize_keyword(kw)
        for i, p in enumerate(projects):
            if not _belongs_to_user(p, user_id):
                continue
            if _normalize_target_site(str(p.get("target_website") or "")) != site_norm:
                continue
            if _normalize_keyword(str(p.get("primary_keyword") or "")) != pk_norm:
                continue
            existing_idx = i
            break

        if existing_idx is not None:
            entry = dict(projects[existing_idx])
            created = False
            has_content = bool(_resolve_project_content(entry))
            entry["title"] = title
            entry["primary_keyword"] = kw
            entry["target_website"] = site
            entry["meta_description"] = meta
            entry["outline_content"] = outline
            entry["custom_title"] = str(raw.get("custom_title") or "").strip()
            entry["custom_description"] = str(raw.get("custom_description") or "").strip()
            entry["custom_outline"] = outline
            entry["search_volume"] = sv
            entry["content_type"] = str(raw.get("content_type") or "").strip()
            entry["competitor_url"] = str(raw.get("competitor_url") or "").strip()
            entry["target_word_count"] = twc
            entry["secondary_keywords"] = sec_list
            entry["wp_category_id"] = wpc_raw
            if not has_content:
                entry["origin"] = "bulk_setup"
                entry["content"] = ""
                draft = entry.get("draft_output")
                if isinstance(draft, dict):
                    draft = dict(draft)
                    draft.update(
                        {
                            "title": title,
                            "content": "",
                            "meta_description": meta,
                            "primary_keyword": kw,
                            "outline_content": outline,
                            "target_website": site,
                            "secondary_keywords": sec_list,
                        }
                    )
                    if wpc_raw > 0:
                        draft["categories"] = [wpc_raw]
                    else:
                        draft.pop("categories", None)
                    entry["draft_output"] = draft
            projects[existing_idx] = entry
        else:
            draft = {
                "title": title,
                "content": "",
                "slug": "",
                "tags": [],
                "meta_description": meta,
                "target_website": site,
                "primary_keyword": kw,
                "secondary_keywords": sec_list,
                "outline_content": outline,
            }
            if wpc_raw > 0:
                draft["categories"] = [wpc_raw]
            entry = {
                "id": str(uuid.uuid4()),
                "user_id": int(user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "title": title,
                "slug": "",
                "target_website": site,
                "primary_keyword": kw,
                "secondary_keywords": sec_list,
                "outline_content": outline,
                "meta_description": meta,
                "tags": [],
                "content": "",
                "featured_image": "",
                "gallery_images": [],
                "scheduled_at": "",
                "wp_category_id": wpc_raw,
                "custom_title": str(raw.get("custom_title") or "").strip(),
                "custom_description": str(raw.get("custom_description") or "").strip(),
                "custom_outline": outline,
                "search_volume": sv,
                "content_type": str(raw.get("content_type") or "").strip(),
                "competitor_url": str(raw.get("competitor_url") or "").strip(),
                "target_word_count": twc,
                "origin": "bulk_setup",
                "draft_output": draft,
            }
            projects.insert(0, entry)
            created = True

        results.append(
            {
                "id": str(entry["id"]),
                "keyword": kw,
                "action": "created" if created else "updated",
            }
        )
        changed = True

    if changed:
        del projects[MAX_PROJECTS:]
        _write_projects(projects)
    return results


def save_or_update_written_bulk_project(
    *,
    user_id: int,
    source_payload: dict[str, Any],
    draft_payload: dict[str, Any],
) -> str:
    """Ghi bài bulk đã có content — cập nhật nháp setup cùng keyword/domain nếu có."""
    existing = find_project_by_site_keyword(
        user_id,
        str(source_payload.get("target_website") or ""),
        str(source_payload.get("primary_keyword") or ""),
    )
    if not existing:
        return save_content_ai_project(
            user_id=user_id,
            source_payload=source_payload,
            draft_payload=draft_payload,
        )

    pid = str(existing.get("id") or "")
    projects = _read_projects_scoped(user_id)
    for i, p in enumerate(projects):
        if str(p.get("id") or "") != pid:
            continue
        if not _belongs_to_user(p, user_id):
            continue
        entry = dict(p)
        for key in (
            "title",
            "slug",
            "target_website",
            "primary_keyword",
            "secondary_keywords",
            "outline_content",
            "meta_description",
            "tags",
            "content",
            "custom_title",
            "custom_description",
            "custom_outline",
            "search_volume",
            "content_type",
            "competitor_url",
            "target_word_count",
            "wp_category_id",
        ):
            if key in source_payload:
                entry[key] = source_payload[key]
        entry["content"] = str(draft_payload.get("content") or source_payload.get("content") or "")
        entry["draft_output"] = draft_payload
        entry["origin"] = "bulk"
        projects[i] = entry
        _write_projects(projects)
        return pid
    return save_content_ai_project(
        user_id=user_id,
        source_payload=source_payload,
        draft_payload=draft_payload,
    )


def _resolve_project_content(p: dict[str, Any]) -> str:
    content = str(p.get("content") or "").strip()
    if content:
        return content
    draft = p.get("draft_output")
    if isinstance(draft, dict):
        draft_content = str(draft.get("content") or "").strip()
        if draft_content:
            return draft_content
    return ""


def _project_list_row(p: dict[str, Any]) -> dict[str, Any]:
    outline = str(p.get("outline_content") or "").strip()
    content = _resolve_project_content(p)
    pk = str(p.get("primary_keyword") or "").strip()
    title = str(p.get("title") or "").strip()
    thumb = str(p.get("featured_image") or "").strip()
    stats = _content_stats(content)
    wc = int(stats["word_count"])
    has_section = bool(re.search(r"^#{2,3}\s", outline, flags=re.MULTILINE))
    has_research = bool(pk)
    has_outline = bool(outline)
    has_content = bool(content)
    has_thumb = bool(thumb)
    origin = str(p.get("origin") or "").strip().lower()
    is_setup_draft = origin == "bulk_setup" and not has_content
    wp_status = str(p.get("wp_publish_status") or "").strip().lower()
    if wp_status in {"publish", "published", "future"}:
        status = "published"
    elif is_setup_draft:
        status = "setup_draft"
    elif has_content and has_outline:
        status = "ready"
    else:
        status = "draft"
    return {
        "id": str(p.get("id") or ""),
        "created_at": p.get("created_at") or "",
        "title": title,
        "slug": str(p.get("slug") or ""),
        "target_website": str(p.get("target_website") or ""),
        "primary_keyword": pk,
        "featured_image": thumb,
        "word_count": wc,
        "char_count": int(stats["char_count"]),
        "sentence_count": int(stats["sentence_count"]),
        "paragraph_count": int(stats["paragraph_count"]),
        "page_count": float(stats["page_count"]),
        "has_research": has_research,
        "has_outline": has_outline,
        "has_content": has_content,
        "has_thumb": has_thumb,
        "has_section": has_section,
        "status": status,
        "origin": origin,
        "is_setup_draft": is_setup_draft,
    }


def _project_sort_ts(p: dict[str, Any]) -> float:
    raw = str(p.get("created_at") or "")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def list_content_ai_projects(*, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    owned = _projects_for_user(_read_projects_scoped(user_id), user_id)
    owned.sort(key=_project_sort_ts, reverse=True)
    cap = max(1, min(int(limit or 30), 500))
    return [_project_list_row(p) for p in owned[:cap]]


def get_content_ai_project(project_id: str, *, user_id: int) -> dict[str, Any] | None:
    pid = str(project_id or "").strip()
    if not pid:
        return None
    for p in _read_projects_scoped(user_id):
        if str(p.get("id") or "") == pid and _belongs_to_user(p, user_id) and not is_legacy_orphan(p):
            return p
    return None


def update_content_ai_project_fields(
    project_id: str,
    fields: dict[str, Any],
    *,
    user_id: int,
) -> dict[str, Any] | None:
    pid = str(project_id or "").strip()
    if not pid or not fields:
        return None
    allowed = {
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
    }
    projects = _read_projects_scoped(user_id)
    found: dict[str, Any] | None = None
    for i, p in enumerate(projects):
        if str(p.get("id") or "") != pid:
            continue
        if not _belongs_to_user(p, user_id):
            continue
        entry = dict(p)
        for key, val in fields.items():
            if key not in allowed:
                continue
            entry[key] = val
        draft = entry.get("draft_output")
        if isinstance(draft, dict):
            draft = dict(draft)
            for key, val in fields.items():
                if key in allowed:
                    draft[key] = val
            entry["draft_output"] = draft
        projects[i] = entry
        found = entry
        break
    if not found:
        return None
    _write_projects(projects)
    return _project_list_row(found)


def delete_content_ai_project(project_id: str, *, user_id: int) -> bool:
    pid = str(project_id or "").strip()
    if not pid:
        return False
    projects = _read_projects_scoped(user_id)
    filtered = [
        p
        for p in projects
        if not (str(p.get("id") or "") == pid and _belongs_to_user(p, user_id))
    ]
    if len(filtered) == len(projects):
        return False
    _write_projects(filtered)
    return True
