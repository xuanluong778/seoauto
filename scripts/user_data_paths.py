"""Per-user paths under data/users/{user_id}/."""

from __future__ import annotations

from pathlib import Path


def user_data_dir(user_id: int) -> Path:
    root = Path("data") / "users" / str(int(user_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_action_plan_notes_file(user_id: int) -> Path:
    return user_data_dir(user_id) / "action_plan_notes.json"


def user_action_plan_deploy_file(user_id: int) -> Path:
    return user_data_dir(user_id) / "action_plan_deploy_links.json"


def user_gsc_indexing_counts_file(user_id: int) -> Path:
    return user_data_dir(user_id) / "gsc_indexing_counts.json"


def _safe_segment(name: str) -> str:
    import re

    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name or "").strip()).strip("-").lower()
    return s or "general"


def user_upload_dir(user_id: int, *, project_id: str | None = None) -> Path:
    """Per-user upload root: data/users/{id}/uploads/content-ai/{project|general}/"""
    segment = _safe_segment(project_id or "general")
    root = user_data_dir(user_id) / "uploads" / "content-ai" / segment
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_upload_relative_path(*, project_id: str | None, filename: str) -> str:
    segment = _safe_segment(project_id or "general")
    return f"content-ai/{segment}/{filename}"


def resolve_user_upload_file(user_id: int, relative_path: str) -> Path | None:
    """Resolve path only under data/users/{id}/uploads/ — blocks path traversal."""
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    base = (user_data_dir(user_id) / "uploads").resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target if target.is_file() else None
