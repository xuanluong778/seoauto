"""Private user uploads vs public published assets."""

from __future__ import annotations

import imghdr
import re
from pathlib import Path
from uuid import uuid4

from app.services.user_data_paths import user_upload_dir, user_upload_relative_path

# Public assets: random filename, no sensitive metadata in path
PUBLIC_PUBLISHED_DIR = Path("static") / "published"
ALLOWED_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
ALLOWED_IMAGE_MIMES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)


def _detect_image_suffix(data: bytes, fallback: str = ".jpg") -> str:
    kind = imghdr.what(None, h=data[:32])
    if kind == "jpeg":
        return ".jpg"
    if kind == "png":
        return ".png"
    if kind == "gif":
        return ".gif"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    fb = fallback if fallback in ALLOWED_IMAGE_SUFFIXES else ".jpg"
    return fb


def validate_image_bytes(data: bytes, *, suffix: str = "") -> None:
    if not data:
        raise ValueError("File rỗng.")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("File ảnh vượt quá 10MB.")
    sfx = suffix.lower() if suffix else _detect_image_suffix(data)
    if sfx == ".jpeg":
        sfx = ".jpg"
    if sfx not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Chỉ hỗ trợ jpg/jpeg/png/webp/gif.")
    detected = _detect_image_suffix(data, fallback=sfx)
    if detected not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Nội dung file không phải ảnh hợp lệ.")


def private_upload_url(user_id: int, relative_path: str) -> str:
    rel = str(relative_path or "").replace("\\", "/").lstrip("/")
    return f"/api/user-files/{int(user_id)}/{rel}"


def save_private_image(
    *,
    user_id: int,
    data: bytes,
    suffix: str = "",
    stem: str = "image",
    project_id: str | None = None,
) -> dict[str, str]:
    """Store under data/users/{id}/uploads/ — never under public static."""
    validate_image_bytes(data, suffix=suffix)
    sfx = suffix.lower() if suffix else _detect_image_suffix(data)
    if sfx == ".jpeg":
        sfx = ".jpg"
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "image"
    target_name = f"{safe_stem}-{uuid4().hex[:12]}{sfx}"
    dest_dir = user_upload_dir(user_id, project_id=project_id)
    (dest_dir / target_name).write_bytes(data)
    rel = user_upload_relative_path(project_id=project_id, filename=target_name)
    return {
        "url": private_upload_url(user_id, rel),
        "name": target_name,
        "relative_path": rel,
        "visibility": "private",
    }


def save_public_published_image(
    *,
    data: bytes,
    suffix: str = "",
) -> dict[str, str]:
    """
    For assets intentionally public (e.g. embedded in published articles).
    Random unguessable filename; mime validated; no user id in path.
    """
    validate_image_bytes(data, suffix=suffix)
    sfx = suffix.lower() if suffix else _detect_image_suffix(data)
    if sfx == ".jpeg":
        sfx = ".jpg"
    target_name = f"{uuid4().hex}{sfx}"
    PUBLIC_PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_PUBLISHED_DIR / target_name).write_bytes(data)
    return {
        "url": f"/static/published/{target_name}",
        "name": target_name,
        "visibility": "public",
    }
