from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.json_atomic import mutate_json_list, read_json_list, write_json_list

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_FILE = _PROJECT_ROOT / "data" / "content_ai_projects.json"
MAX_PROJECTS_PER_USER = 120
_PROJECTS_FILE_CACHE: tuple[float, list[dict[str, Any]]] | None = None


def _read_projects() -> list[dict[str, Any]]:
    from app.services.user_data_pg.config import pg_fallback_json_enabled, pg_read_enabled

    if pg_read_enabled("content_ai_projects"):
        try:
            from app.services.user_data_pg import content_ai_projects as pg_store

            rows = pg_store.list_all_entries()
            if rows or not pg_fallback_json_enabled():
                return rows
        except Exception:
            if not pg_fallback_json_enabled():
                raise
    global _PROJECTS_FILE_CACHE
    try:
        mtime = PROJECT_FILE.stat().st_mtime if PROJECT_FILE.exists() else 0.0
    except OSError:
        mtime = 0.0
    if _PROJECTS_FILE_CACHE is not None and _PROJECTS_FILE_CACHE[0] == mtime:
        return _PROJECTS_FILE_CACHE[1]
    data = read_json_list(PROJECT_FILE)
    _PROJECTS_FILE_CACHE = (mtime, data)
    return data


def _invalidate_projects_cache() -> None:
    global _PROJECTS_FILE_CACHE
    _PROJECTS_FILE_CACHE = None


def _write_projects(projects: list[dict[str, Any]]) -> None:
    write_json_list(PROJECT_FILE, projects)
    _invalidate_projects_cache()
    try:
        from app.services.user_data_pg.config import pg_dual_write_enabled

        if pg_dual_write_enabled("content_ai_projects"):
            from app.services.user_data_pg import content_ai_projects as pg_store

            pg_store.replace_all_entries(projects)
    except Exception:
        pass


def _project_owner_id(entry: dict[str, Any]) -> int | None:
    if "user_id" not in entry:
        return None
    try:
        uid = int(entry.get("user_id") or 0)
    except (TypeError, ValueError):
        return None
    return uid if uid > 0 else None


def _trim_retention_for_user(projects: list[dict[str, Any]], user_id: int) -> None:
    uid = int(user_id)
    user_idxs = [i for i, p in enumerate(projects) if _project_owner_id(p) == uid]
    if len(user_idxs) <= MAX_PROJECTS_PER_USER:
        return
    drop = set(user_idxs[MAX_PROJECTS_PER_USER:])
    projects[:] = [p for i, p in enumerate(projects) if i not in drop]


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


def _needs_legacy_migration(projects: list[dict[str, Any]]) -> bool:
    return any(isinstance(p, dict) and _legacy_owner_missing(p) for p in projects)


def _ensure_legacy_migrated(projects: list[dict[str, Any]]) -> None:
    if _needs_legacy_migration(projects):
        _migrate_legacy_project_owners(projects)


def _read_projects_scoped(user_id: int) -> list[dict[str, Any]]:
    projects = _read_projects()
    if _needs_legacy_migration(projects):
        def _mutate(projs: list[dict[str, Any]]) -> None:
            _migrate_legacy_project_owners(projs)
            return None

        mutate_json_list(PROJECT_FILE, _mutate)
        _invalidate_projects_cache()
        projects = _read_projects()
    return projects


def _projects_for_user(projects: list[dict[str, Any]], user_id: int, *, role: str = "user") -> list[dict[str, Any]]:
    if is_admin_role(role):
        return [p for p in projects if isinstance(p, dict)]
    return [p for p in projects if _belongs_to_user(p, user_id) and not is_legacy_orphan(p)]


def _new_project_entry(
    *,
    project_id: str,
    user_id: int,
    source_payload: dict[str, Any],
    draft_payload: dict[str, Any],
    origin: str = "",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
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
    for seo_key in ("seo_score", "seo_issues", "seo_status", "seo_issue_count", "actual_word_count"):
        if seo_key in source_payload:
            entry[seo_key] = source_payload[seo_key]
    if origin:
        entry["origin"] = origin
    return entry


def save_content_ai_project(
    *,
    user_id: int,
    source_payload: dict[str, Any],
    draft_payload: dict[str, Any],
) -> str:
    project_id = str(uuid.uuid4())

    def _mutate(projects: list[dict[str, Any]]) -> str:
        _ensure_legacy_migrated(projects)
        projects.insert(
            0,
            _new_project_entry(
                project_id=project_id,
                user_id=user_id,
                source_payload=source_payload,
                draft_payload=draft_payload,
            ),
        )
        _trim_retention_for_user(projects, user_id)
        return project_id

    return mutate_json_list(PROJECT_FILE, _mutate)


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


# Host must include a domain extension (.com, .vn, .com.vn, .local, …).
_BOARD_WEBSITE_HOST_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,})(?:\.[a-z]{2,})?$",
    re.IGNORECASE,
)


def normalize_board_website_url(value: str | None) -> str:
    """
    Return a normalized http(s) website URL for the schedule-board site filter, or "".
    Rejects display names and values without a valid domain extension.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if not lower.startswith(("http://", "https://")):
        return ""
    try:
        parsed = urlparse(raw.strip())
    except Exception:
        return ""
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return ""
    host = str(parsed.hostname or "").strip().lower()
    if not host or not _BOARD_WEBSITE_HOST_RE.match(host):
        return ""
    netloc = host
    if parsed.port and not (
        (scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{host}:{int(parsed.port)}"
    return f"{scheme}://{netloc}"


def sanitize_board_website_options(sites: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Keep only valid website URLs; normalize and de-duplicate for the board filter."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in sites or []:
        if not isinstance(row, dict):
            continue
        for candidate in (row.get("label"), row.get("id"), row.get("url")):
            norm = normalize_board_website_url(candidate)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append({"id": norm, "label": norm})
            break
    out.sort(key=lambda x: x["label"].lower())
    return out


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
        _trim_retention_for_user(projects, user_id)
        _write_projects(projects)
    return results


def save_or_update_written_bulk_project(
    *,
    user_id: int,
    source_payload: dict[str, Any],
    draft_payload: dict[str, Any],
) -> str:
    """Ghi bài bulk đã có content — cập nhật nháp setup cùng keyword/domain nếu có."""
    site = _normalize_target_site(str(source_payload.get("target_website") or ""))
    pk = _normalize_keyword(str(source_payload.get("primary_keyword") or ""))

    def _mutate(projects: list[dict[str, Any]]) -> str:
        _ensure_legacy_migrated(projects)
        existing_idx: int | None = None
        for i, p in enumerate(projects):
            if not _belongs_to_user(p, user_id):
                continue
            if _normalize_target_site(str(p.get("target_website") or "")) != site:
                continue
            if _normalize_keyword(str(p.get("primary_keyword") or "")) != pk:
                continue
            existing_idx = i
            break
        if existing_idx is None:
            project_id = str(uuid.uuid4())
            projects.insert(
                0,
                _new_project_entry(
                    project_id=project_id,
                    user_id=user_id,
                    source_payload=source_payload,
                    draft_payload=draft_payload,
                    origin="bulk",
                ),
            )
            _trim_retention_for_user(projects, user_id)
            return project_id

        entry = dict(projects[existing_idx])
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
            "seo_score",
            "seo_issues",
            "seo_status",
            "seo_issue_count",
            "actual_word_count",
        ):
            if key in source_payload:
                entry[key] = source_payload[key]
        entry["content"] = str(draft_payload.get("content") or source_payload.get("content") or "")
        entry["draft_output"] = draft_payload
        entry["origin"] = "bulk"
        projects[existing_idx] = entry
        return str(entry.get("id") or "")

    return mutate_json_list(PROJECT_FILE, _mutate)


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
        "seo_score": p.get("seo_score"),
        "seo_issues": p.get("seo_issues") if isinstance(p.get("seo_issues"), list) else [],
        "seo_status": str(p.get("seo_status") or ""),
        "seo_issue_count": int(p.get("seo_issue_count") or 0)
        if p.get("seo_issue_count") is not None
        else (len(p.get("seo_issues") or []) if isinstance(p.get("seo_issues"), list) else 0),
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


def _project_matches_website_filter(
    project: dict[str, Any],
    *,
    website: str,
    site_hosts: set[str],
    site_urls: set[str],
    site_ids: set[str],
) -> bool:
    raw = str(website or "").strip()
    if not raw:
        return True
    target = str(project.get("target_website") or "").strip()
    if target and (target == raw or target in site_urls or _normalize_target_site(target) in site_hosts):
        return True
    pid_site = str(project.get("wp_site_id") or "").strip()
    if pid_site and (pid_site == raw or pid_site in site_ids):
        return True
    if _normalize_target_site(raw) and _normalize_target_site(target) == _normalize_target_site(raw):
        return True
    return False


def _has_written_content(p: dict[str, Any]) -> bool:
    if str(p.get("content") or "").strip():
        return True
    draft = p.get("draft_output")
    return isinstance(draft, dict) and bool(str(draft.get("content") or "").strip())


def _website_filter_sets(
    user_id: int, website: str
) -> tuple[set[str], set[str], set[str]]:
    raw = str(website or "").strip()
    site_hosts: set[str] = set()
    site_urls: set[str] = {raw} if raw else set()
    site_ids: set[str] = set()
    if not raw:
        return site_hosts, site_urls, site_ids
    norm = _normalize_target_site(raw)
    if norm:
        site_hosts.add(norm)
    from app.services.publishing_sites_store import get_site

    hit = get_site(raw, user_id=user_id, reveal_password=False)
    if hit:
        site_ids.add(raw)
        url = str(hit.get("url") or "").strip()
        if url:
            site_urls.add(url)
            hn = _normalize_target_site(url)
            if hn:
                site_hosts.add(hn)
    return site_hosts, site_urls, site_ids


def board_site_label_map(user_id: int) -> dict[str, str]:
    from app.services.publishing_sites_store import list_sites

    out: dict[str, str] = {}
    for site in list_sites(user_id=user_id):
        sid = str(site.get("id") or "").strip()
        if sid:
            out[sid] = str(site.get("name") or site.get("url") or sid).strip()
    return out


def board_site_url_map(user_id: int) -> dict[str, str]:
    """Map publishing-site id → normalized website URL (invalid URLs omitted)."""
    from app.services.publishing_sites_store import list_sites

    out: dict[str, str] = {}
    for site in list_sites(user_id=user_id):
        sid = str(site.get("id") or "").strip()
        if not sid:
            continue
        norm = normalize_board_website_url(site.get("url"))
        if norm:
            out[sid] = norm
    return out


def collect_written_board_summaries(
    *,
    user_id: int,
    website: str | None = None,
    limit: int = 500,
    collect_sites: bool = False,
    site_labels: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Single JSON pass: lightweight rows for schedule board (+ optional site options)."""
    cap = max(1, min(int(limit or 500), 500))
    website_raw = str(website or "").strip()
    site_hosts, site_urls, site_ids = (
        _website_filter_sets(user_id, website_raw) if website_raw else (set(), set(), set())
    )
    labels = site_labels or {}
    url_by_id = board_site_url_map(user_id) if collect_sites else {}
    scored: list[tuple[float, dict[str, Any]]] = []
    site_seen: dict[str, str] = {}

    for p in _projects_for_user(_read_projects_scoped(user_id), user_id):
        if not _has_written_content(p):
            continue
        if website_raw and not _project_matches_website_filter(
            p,
            website=website_raw,
            site_hosts=site_hosts,
            site_urls=site_urls,
            site_ids=site_ids,
        ):
            continue
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        draft = p.get("draft_output") if isinstance(p.get("draft_output"), dict) else {}
        row = {
            "id": pid,
            "primary_keyword": str(p.get("primary_keyword") or "").strip(),
            "custom_title": str(p.get("custom_title") or "").strip(),
            "title": str(p.get("title") or "").strip(),
            "target_website": str(p.get("target_website") or "").strip(),
            "wp_site_id": str(p.get("wp_site_id") or "").strip(),
            "wp_category_id": p.get("wp_category_id"),
            "wp_category_name": str(p.get("wp_category_name") or "").strip(),
            "featured_image": str(p.get("featured_image") or draft.get("featured_image") or "").strip(),
            "slug": str(p.get("slug") or "").strip(),
            "status": str(p.get("status") or "").strip(),
            "wp_post_url": str(p.get("wp_post_url") or "").strip(),
            "draft_output": {"featured_image": draft.get("featured_image")} if draft else {},
        }
        scored.append((_project_sort_ts(p), row))
        if collect_sites:
            for candidate in (
                row["target_website"],
                url_by_id.get(row["wp_site_id"]) or "",
                labels.get(row["wp_site_id"]) or "",
            ):
                norm = normalize_board_website_url(candidate)
                if norm and norm not in site_seen:
                    site_seen[norm] = norm

    scored.sort(key=lambda x: x[0], reverse=True)
    rows = [row for _, row in scored[:cap]]
    sites = sanitize_board_website_options([{"id": k, "label": v} for k, v in site_seen.items()])
    return rows, sites


def list_all_written_project_ids(*, user_id: int, limit: int = 500) -> list[str]:
    """All project ids with written content for a user (newest first)."""
    rows, _ = collect_written_board_summaries(user_id=user_id, limit=limit, collect_sites=False)
    return [str(r.get("id") or "").strip() for r in rows if str(r.get("id") or "").strip()]


def get_content_ai_projects_by_ids(
    project_ids: list[str],
    *,
    user_id: int,
) -> dict[str, dict[str, Any]]:
    """Batch-load projects by id (single JSON read)."""
    want = {str(x).strip() for x in (project_ids or []) if str(x).strip()}
    if not want:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for p in _projects_for_user(_read_projects_scoped(user_id), user_id):
        pid = str(p.get("id") or "").strip()
        if pid in want:
            out[pid] = p
            if len(out) >= len(want):
                break
    return out


def list_written_project_ids_for_website(
    *,
    user_id: int,
    website: str,
    limit: int = 500,
) -> list[str]:
    """Return project ids with written content for a target website (URL, host, or wp_site_id)."""
    raw = str(website or "").strip()
    if not raw:
        return []
    rows, _ = collect_written_board_summaries(
        user_id=user_id, website=raw, limit=limit, collect_sites=False
    )
    return [str(r.get("id") or "").strip() for r in rows if str(r.get("id") or "").strip()]


def list_board_website_options(*, user_id: int, limit: int = 80) -> list[dict[str, str]]:
    """Distinct website URLs for schedule-board filter dropdown."""
    cap = max(1, min(int(limit or 80), 200))
    _, sites = collect_written_board_summaries(
        user_id=user_id,
        limit=500,
        collect_sites=True,
        site_labels=board_site_label_map(user_id),
    )
    return sanitize_board_website_options(sites)[:cap]


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
        "wp_category_id",
        "wp_publish_status",
        "image_assets",
    }
    holder: dict[str, Any] = {"found": None}

    def _mutate(projects: list[dict[str, Any]]) -> dict[str, Any] | None:
        _ensure_legacy_migrated(projects)
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
            holder["found"] = entry
            break
        return holder["found"]

    found = mutate_json_list(PROJECT_FILE, _mutate)
    if not found:
        return None
    return _project_list_row(found)


def delete_content_ai_project(project_id: str, *, user_id: int) -> bool:
    pid = str(project_id or "").strip()
    if not pid:
        return False

    def _mutate(projects: list[dict[str, Any]]) -> bool:
        _ensure_legacy_migrated(projects)
        before = len(projects)
        projects[:] = [
            p
            for p in projects
            if not (str(p.get("id") or "") == pid and _belongs_to_user(p, user_id))
        ]
        return len(projects) < before

    return mutate_json_list(PROJECT_FILE, _mutate)
