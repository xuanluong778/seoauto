from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.rbac import normalize_role
from app.services.user_scope import belongs_to_user, entry_user_id

KB_FILE = Path("data/ai_knowledge_bases.json")
SCOPES = frozenset({"user", "global"})
INHERIT_MODES = frozenset({"all", "match"})
MAX_BASES = 50
INHERITANCE_LABEL = "Kế thừa từ hệ thống"

TONES = {
    "professional": "Chuyên nghiệp",
    "friendly": "Thân thiện",
    "expert": "Chuyên gia / uy tín",
    "casual": "Gần gũi, đời thường",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)sk-[a-z0-9]{20,}"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_url(url: str) -> str:
    s = str(url or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s.rstrip("/")


def _norm_site(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (p.netloc or p.path or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host.rstrip("/")
    except Exception:
        return raw.lower().rstrip("/")


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [t.strip().lower() for t in re.split(r"[,;|]", value) if t.strip()]
    return []


def _is_admin(role: str) -> bool:
    return normalize_role(role) == "admin"


def _is_legacy_orphan(entry: dict[str, Any]) -> bool:
    return bool(entry.get("legacy_orphan")) or ("user_id" not in entry and str(entry.get("scope") or "user") != "global")


def _migrate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Safe defaults for legacy rows — không gán user_id giả để tránh lộ dữ liệu."""
    row = dict(entry)
    scope = str(row.get("scope") or "").strip().lower()
    if scope not in SCOPES:
        if "user_id" not in row:
            row["legacy_orphan"] = True
            row["scope"] = "user"
            row["user_id"] = 0
        else:
            row["scope"] = "user"
    if scope == "global":
        row["user_id"] = 0
    elif "user_id" not in row:
        row["legacy_orphan"] = True
        row["user_id"] = 0
    if str(row.get("inherit_mode") or "").strip().lower() not in INHERIT_MODES:
        row["inherit_mode"] = "all" if row.get("scope") == "global" else "match"
    return row


def _read_all() -> list[dict[str, Any]]:
    if not KB_FILE.exists():
        return []
    try:
        raw = json.loads(KB_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [_migrate_entry(x) for x in raw if isinstance(x, dict)]


def _write_all(items: list[dict[str, Any]]) -> None:
    KB_FILE.parent.mkdir(parents=True, exist_ok=True)
    KB_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_raw(kb_id: str) -> dict[str, Any] | None:
    kid = str(kb_id or "").strip()
    if not kid:
        return None
    for raw in _read_all():
        if str(raw.get("id")) == kid:
            return raw
    return None


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    migrated = _migrate_entry(entry)
    tone = str(migrated.get("tone") or "professional").strip().lower()
    if tone not in TONES:
        tone = "professional"
    lang = str(migrated.get("language") or "vi").strip().lower()[:8] or "vi"
    scope = str(migrated.get("scope") or "user").strip().lower()
    if scope not in SCOPES:
        scope = "user"
    uid = entry_user_id(migrated) if scope == "user" else 0
    inherit_mode = str(migrated.get("inherit_mode") or ("all" if scope == "global" else "match")).strip().lower()
    if inherit_mode not in INHERIT_MODES:
        inherit_mode = "all" if scope == "global" else "match"
    inherit_websites = [_norm_url(w) for w in (migrated.get("inherit_websites") or []) if str(w).strip()]
    if isinstance(migrated.get("inherit_websites"), str) and str(migrated.get("inherit_websites")).strip():
        inherit_websites.extend(_norm_url(w) for w in re.split(r"[,;|]", str(migrated.get("inherit_websites"))) if w.strip())
    return {
        "id": str(migrated.get("id") or uuid.uuid4()),
        "user_id": uid,
        "scope": scope,
        "inherit_mode": inherit_mode,
        "inherit_websites": list(dict.fromkeys(inherit_websites)),
        "industry": str(migrated.get("industry") or "").strip(),
        "tags": _parse_tags(migrated.get("tags")),
        "project_id": str(migrated.get("project_id") or "").strip(),
        "cloned_from": str(migrated.get("cloned_from") or "").strip(),
        "legacy_orphan": bool(migrated.get("legacy_orphan")),
        "name": str(migrated.get("name") or "").strip(),
        "brand_name": str(migrated.get("brand_name") or "").strip(),
        "website_url": _norm_url(migrated.get("website_url") or ""),
        "tone": tone,
        "tone_label": TONES[tone],
        "language": lang,
        "products_services": str(migrated.get("products_services") or "").strip(),
        "target_audience": str(migrated.get("target_audience") or "").strip(),
        "key_facts": str(migrated.get("key_facts") or "").strip(),
        "avoid_topics": str(migrated.get("avoid_topics") or "").strip(),
        "custom_instructions": str(migrated.get("custom_instructions") or "").strip(),
        "enabled": bool(migrated.get("enabled", True)),
        "is_default": bool(migrated.get("is_default", False)),
        "created_at": str(migrated.get("created_at") or _now()),
        "updated_at": str(migrated.get("updated_at") or _now()),
    }


def _sanitize_text(text: str) -> str:
    out = str(text or "")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[redacted]", out)
    return out


def _user_match_context(user_id: int) -> dict[str, set[str]]:
    websites: set[str] = set()
    tags: set[str] = set()
    industries: set[str] = set()
    projects: set[str] = set()
    for raw in _read_all():
        row = _normalize(raw)
        if row.get("scope") != "user" or not belongs_to_user(raw, user_id):
            continue
        host = _norm_site(row.get("website_url") or "")
        if host:
            websites.add(host)
        for w in row.get("inherit_websites") or []:
            h = _norm_site(w)
            if h:
                websites.add(h)
        tags.update(_parse_tags(row.get("tags")))
        ind = str(row.get("industry") or "").strip().lower()
        if ind:
            industries.add(ind)
        proj = str(row.get("project_id") or "").strip().lower()
        if proj:
            projects.add(proj)
    return {"websites": websites, "tags": tags, "industries": industries, "projects": projects}


def _hosts_overlap(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    if a & b:
        return True
    for x in a:
        for y in b:
            if x in y or y in x:
                return True
    return False


def _global_inherited_for_user(entry: dict[str, Any], user_id: int) -> bool:
    row = _normalize(entry)
    if row.get("scope") != "global":
        return False
    mode = str(row.get("inherit_mode") or "all").lower()
    if mode == "all":
        return True
    ctx = _user_match_context(user_id)
    g_hosts: set[str] = set()
    if row.get("website_url"):
        g_hosts.add(_norm_site(row["website_url"]))
    for w in row.get("inherit_websites") or []:
        h = _norm_site(w)
        if h:
            g_hosts.add(h)
    g_tags = set(_parse_tags(row.get("tags")))
    g_ind = str(row.get("industry") or "").strip().lower()
    g_proj = str(row.get("project_id") or "").strip().lower()
    if not g_hosts and not g_tags and not g_ind and not g_proj:
        return True
    if _hosts_overlap(g_hosts, ctx["websites"]):
        return True
    if g_tags and ctx["tags"] and (g_tags & ctx["tags"]):
        return True
    if g_ind and g_ind in ctx["industries"]:
        return True
    if g_proj and g_proj in ctx["projects"]:
        return True
    return False


def _readable(entry: dict[str, Any], user_id: int, role: str = "user") -> bool:
    row = _normalize(entry)
    if _is_admin(role):
        return True
    if row.get("scope") == "global":
        return _global_inherited_for_user(entry, user_id)
    if _is_legacy_orphan(entry):
        return False
    return belongs_to_user(entry, user_id)


def _writable(entry: dict[str, Any], user_id: int, role: str) -> bool:
    row = _normalize(entry)
    if _is_admin(role):
        return True
    if row.get("scope") == "global":
        return False
    if _is_legacy_orphan(entry):
        return False
    return belongs_to_user(entry, user_id)


def _writable_or_raise(entry: dict[str, Any], user_id: int, role: str) -> None:
    if _writable(entry, user_id, role):
        return
    row = _normalize(entry)
    if row.get("scope") == "global":
        raise PermissionError("Knowledge Base toàn cục (Global) chỉ tài khoản admin mới được sửa hoặc xóa.")
    raise PermissionError("Bạn không có quyền sửa Knowledge Base này.")


def _is_inherited_view(entry: dict[str, Any], user_id: int, role: str) -> bool:
    row = _normalize(entry)
    if row.get("scope") != "global":
        return False
    if _is_admin(role):
        return False
    return _global_inherited_for_user(entry, user_id)


def _public(
    entry: dict[str, Any],
    *,
    user_id: int,
    role: str = "user",
    can_edit: bool | None = None,
) -> dict[str, Any]:
    row = _normalize(entry)
    inherited = _is_inherited_view(entry, user_id, role)
    out = dict(row)
    out["tone_label"] = TONES.get(row.get("tone") or "", row.get("tone") or "")
    out["is_inherited"] = inherited
    out["inheritance_label"] = INHERITANCE_LABEL if inherited else ""
    out["can_edit"] = bool(can_edit) if can_edit is not None else _writable(entry, user_id, role)
    out["can_clone"] = inherited or (row.get("scope") == "global" and not _is_admin(role))
    if _is_admin(role) and row.get("scope") == "user":
        out["owner_user_id"] = entry_user_id(entry)
    else:
        out.pop("owner_user_id", None)
    if not _is_admin(role) and row.get("scope") == "user" and not belongs_to_user(entry, user_id):
        raise ValueError("forbidden")
    if inherited or (row.get("scope") == "global" and not _is_admin(role)):
        out["custom_instructions"] = _sanitize_text(out.get("custom_instructions") or "")
        out["key_facts"] = _sanitize_text(out.get("key_facts") or "")
    return out


def list_bases(*, user_id: int, role: str = "user") -> list[dict[str, Any]]:
    r = normalize_role(role)
    own: list[dict[str, Any]] = []
    inherited: list[dict[str, Any]] = []
    for raw in _read_all():
        if not _readable(raw, user_id, r):
            continue
        row = _normalize(raw)
        item = _public(raw, user_id=user_id, role=r)
        if row.get("scope") == "user" and belongs_to_user(raw, user_id):
            own.append(item)
        elif row.get("scope") == "global":
            if _is_inherited_view(raw, user_id, r):
                inherited.append(item)
            elif _is_admin(r):
                inherited.append(item)
        elif _is_admin(r):
            own.append(item)
    own.sort(key=lambda x: (not x.get("is_default"), x.get("name", "").lower()))
    inherited.sort(key=lambda x: x.get("name", "").lower())
    return own + inherited


def get_base(kb_id: str, *, user_id: int, role: str = "user") -> dict[str, Any] | None:
    kid = str(kb_id or "").strip()
    if not kid:
        return None
    r = normalize_role(role)
    raw = _find_raw(kid)
    if not raw or not _readable(raw, user_id, r):
        return None
    return _public(raw, user_id=user_id, role=r)


def get_default_base(*, user_id: int, role: str = "user") -> dict[str, Any] | None:
    for item in list_bases(user_id=user_id, role=role):
        if item.get("scope") == "user" and item.get("enabled") and item.get("is_default"):
            return item
    for item in list_bases(user_id=user_id, role=role):
        if item.get("scope") == "user" and item.get("enabled"):
            return item
    return None


def create_base(payload: dict[str, Any], *, user_id: int, role: str = "user") -> dict[str, Any]:
    scope = str(payload.get("scope") or "user").strip().lower()
    if scope == "global" and not _is_admin(role):
        raise ValueError("Chỉ admin mới tạo knowledge base toàn cục.")
    if scope == "global" and str(payload.get("inherit_mode") or "all").lower() not in INHERIT_MODES:
        payload = {**payload, "inherit_mode": "all"}
    items = [
        _normalize(x)
        for x in _read_all()
        if belongs_to_user(x, user_id) and _normalize(x).get("scope") == "user" and not _is_legacy_orphan(x)
    ]
    if scope != "global" and len(items) >= MAX_BASES:
        raise ValueError(f"Tối đa {MAX_BASES} knowledge base.")
    row = _normalize(
        {
            **payload,
            "id": uuid.uuid4(),
            "user_id": 0 if scope == "global" else int(user_id),
            "scope": scope,
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    if not row["name"]:
        raise ValueError("Cần đặt tên knowledge base.")
    if row["is_default"] and scope != "global":
        for it in _read_all():
            if belongs_to_user(it, user_id) and _normalize(it).get("scope") == "user":
                it["is_default"] = False
    elif scope != "global" and not items:
        row["is_default"] = True
    all_items = _read_all()
    all_items.append(row)
    _write_all(all_items)
    return _public(row, user_id=user_id, role=role)


def update_base(kb_id: str, payload: dict[str, Any], *, user_id: int, role: str = "user") -> dict[str, Any] | None:
    kid = str(kb_id or "").strip()
    if not kid:
        return None
    if "scope" in payload and str(payload.get("scope") or "").lower() == "global" and not _is_admin(role):
        raise PermissionError("Chỉ admin mới đặt scope global.")
    if "user_id" in payload and not _is_admin(role):
        raise PermissionError("Không được đổi chủ sở hữu Knowledge Base.")
    items = _read_all()
    found: dict[str, Any] | None = None
    for i, it in enumerate(items):
        if str(it.get("id")) != kid:
            continue
        _writable_or_raise(it, user_id, role)
        merged = {**it, **{k: v for k, v in payload.items() if v is not None}}
        merged["id"] = kid
        merged["updated_at"] = _now()
        row = _normalize(merged)
        if not row["name"]:
            raise ValueError("Cần đặt tên knowledge base.")
        owner = entry_user_id(it) if _normalize(it).get("scope") == "user" else 0
        if payload.get("is_default") is True and row.get("scope") != "global":
            for j, other in enumerate(items):
                if j == i:
                    continue
                if _normalize(other).get("scope") != "user":
                    continue
                if entry_user_id(other) != owner:
                    continue
                other["is_default"] = False
        items[i] = _normalize(row)
        found = _public(items[i], user_id=user_id, role=role)
        break
    if not found:
        return None
    _write_all(items)
    return found


def delete_base(kb_id: str, *, user_id: int, role: str = "user") -> bool:
    kid = str(kb_id or "").strip()
    if not kid:
        return False
    items = _read_all()
    deleted = False
    deleted_owner = 0
    new_items: list[dict[str, Any]] = []
    for x in items:
        if str(x.get("id")) == kid:
            _writable_or_raise(x, user_id, role)
            deleted_owner = entry_user_id(x)
            deleted = True
            continue
        new_items.append(x)
    if not deleted:
        return False
    user_items = [
        x
        for x in new_items
        if belongs_to_user(x, deleted_owner) and _normalize(x).get("scope") == "user"
    ]
    if user_items and not any(x.get("is_default") for x in user_items):
        for x in new_items:
            if belongs_to_user(x, deleted_owner) and _normalize(x).get("scope") == "user":
                x["is_default"] = True
                x["updated_at"] = _now()
                break
    _write_all(new_items)
    try:
        from app.services.ai_knowledge_docs import delete_kb_docs

        delete_kb_docs(kid)
    except Exception:
        pass
    return True


def clone_base(
    source_kb_id: str,
    *,
    user_id: int,
    role: str = "user",
    name: str | None = None,
) -> dict[str, Any]:
    """Copy KB (thường từ global kế thừa) thành bản riêng của user."""
    src_raw = _find_raw(source_kb_id)
    if not src_raw:
        raise ValueError("Không tìm thấy Knowledge Base nguồn.")
    if not _readable(src_raw, user_id, role):
        raise PermissionError("Bạn không có quyền xem Knowledge Base này.")
    src = _normalize(src_raw)
    if src.get("scope") == "user" and not belongs_to_user(src_raw, user_id) and not _is_admin(role):
        raise PermissionError("Không thể sao chép Knowledge Base của user khác.")
    if src.get("scope") == "global" and _is_admin(role):
        raise ValueError("Admin dùng sửa trực tiếp KB Global; user mới cần sao chép thành bản riêng.")
    copy_name = str(name or "").strip() or f"{src.get('name') or 'KB'} (bản sao)"
    payload = {
        k: src.get(k)
        for k in (
            "brand_name",
            "website_url",
            "tone",
            "language",
            "products_services",
            "target_audience",
            "key_facts",
            "avoid_topics",
            "custom_instructions",
            "industry",
            "tags",
            "project_id",
        )
    }
    payload["name"] = copy_name
    payload["scope"] = "user"
    payload["cloned_from"] = str(src.get("id") or "")
    payload["is_default"] = False
    new_kb = create_base(payload, user_id=user_id, role="user")
    try:
        from app.services.ai_knowledge_docs import clone_kb_docs

        clone_kb_docs(str(src.get("id") or ""), str(new_kb.get("id") or ""))
    except Exception as exc:
        delete_base(str(new_kb.get("id") or ""), user_id=user_id, role=role)
        raise ValueError(f"Sao chép tài liệu thất bại: {exc}") from exc
    new_kb["stats"] = None
    return get_base(str(new_kb.get("id") or ""), user_id=user_id, role=role) or new_kb
