"""Tải và tối ưu ảnh Content AI — chỉ JPG/WEBP, <200KB, không upscale."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import requests
from PIL import Image, ImageOps

from app.services.content_ai_image_rules import LANDSCAPE_SIZE, PORTRAIT_SIZE

MAX_OUTPUT_BYTES = 200 * 1024
ALLOWED_OUTPUT = frozenset({"JPEG", "WEBP"})
Orientation = Literal["landscape", "portrait", "any"]


@dataclass
class OptimizedImage:
    local_url: str
    filename: str
    format: str
    width: int
    height: int
    bytes_size: int
    original_width: int
    original_height: int


def _seo_filename(stem: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", str(stem or "").lower()).strip("-")
    return (safe[:60] or "content-image") + f"-{uuid4().hex[:8]}"


def download_image_bytes(url: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    u = str(url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        raise ValueError("URL ảnh không hợp lệ.")
    try:
        r = requests.get(
            u,
            timeout=30,
            stream=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SEOAuto/1.0)",
                "Accept": "image/jpeg,image/webp,image/*,*/*;q=0.8",
            },
        )
    except Exception as exc:
        raise ValueError(f"Không tải được ảnh: {exc}") from exc
    if r.status_code != 200:
        raise ValueError(f"Không tải được ảnh (HTTP {r.status_code}).")
    data = b""
    for chunk in r.iter_content(65536):
        if not chunk:
            continue
        data += chunk
        if len(data) > max_bytes:
            raise ValueError("Ảnh nguồn quá lớn.")
    if len(data) < 400:
        raise ValueError("Ảnh tải về không hợp lệ.")
    return data


def _target_exact_dims(orientation: Orientation, orig_w: int, orig_h: int) -> tuple[int, int]:
    """Kích thước chuẩn sau crop/resize (không upscale)."""
    if orientation == "landscape":
        return LANDSCAPE_SIZE
    if orientation == "portrait":
        return PORTRAIT_SIZE
    if orig_w > 0 and orig_h > 0 and orig_h > orig_w * 1.15:
        return PORTRAIT_SIZE
    return LANDSCAPE_SIZE


def _inset_crop(img: Image.Image, inset: int = 2) -> Image.Image:
    w, h = img.size
    if w <= inset * 2 + 8 or h <= inset * 2 + 8:
        return img
    return img.crop((inset, inset, w - inset, h - inset))


def _center_crop_to_aspect(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    if target_w <= 0 or target_h <= 0:
        return img
    ow, oh = img.size
    if ow <= 0 or oh <= 0:
        return img
    target_ratio = target_w / target_h
    cur = ow / oh
    if abs(cur - target_ratio) < 0.04:
        return img
    if cur > target_ratio:
        new_w = max(1, int(oh * target_ratio))
        left = (ow - new_w) // 2
        return img.crop((left, 0, left + new_w, oh))
    new_h = max(1, int(ow / target_ratio))
    top = (oh - new_h) // 2
    return img.crop((0, top, ow, top + new_h))


def _fit_to_exact(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Crop inset → crop aspect → resize về đúng kích thước chuẩn (không upscale)."""
    img = _inset_crop(img, 2)
    ow, oh = img.size
    if ow <= 0 or oh <= 0:
        return img
    img = _center_crop_to_aspect(img, target_w, target_h)
    ow, oh = img.size
    ratio = min(target_w / ow, target_h / oh, 1.0)
    tw = max(1, int(ow * ratio))
    th = max(1, int(oh * ratio))
    if (tw, th) != (ow, oh):
        if tw >= ow:
            tw = max(1, ow - 2)
        if th >= oh:
            th = max(1, oh - 2)
        img = img.resize((tw, th), Image.Resampling.LANCZOS)
    return img


def _encode_under_limit(img: Image.Image, *, stem: str) -> tuple[bytes, str, str]:
    """Trả (bytes, format, filename_ext)."""
    for fmt, ext, qualities in (
        ("WEBP", ".webp", (85, 78, 70, 62, 55, 48)),
        ("JPEG", ".jpg", (85, 78, 70, 62, 55, 48, 40)),
    ):
        for q in qualities:
            buf = io.BytesIO()
            save_kw: dict[str, Any] = {"format": fmt, "quality": q, "optimize": True}
            if fmt == "JPEG":
                save_kw["progressive"] = True
            img.save(buf, **save_kw)
            data = buf.getvalue()
            if len(data) <= MAX_OUTPUT_BYTES:
                return data, fmt, ext
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=40, optimize=True, progressive=True)
    data = buf.getvalue()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("Không thể nén ảnh dưới 200KB mà không upscale.")
    return data, "JPEG", ".jpg"


def optimize_image_bytes(
    data: bytes,
    *,
    stem: str = "content-image",
    orientation: Orientation = "any",
    prefer_landscape_crop: bool = False,
) -> tuple[bytes, str, int, int, int, int]:
    """
    Trả (bytes, format, out_w, out_h, orig_w, orig_h).
    Chỉ JPG/WEBP; không upscale; resize phải nhỏ hơn gốc ít nhất 2px mỗi chiều nếu có resize.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise ValueError(f"Không đọc được ảnh: {exc}") from exc

    orig_w, orig_h = img.size
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    target_w, target_h = _target_exact_dims(orientation, orig_w, orig_h)
    if prefer_landscape_crop and orientation in ("landscape", "any"):
        target_w, target_h = LANDSCAPE_SIZE
    img = _fit_to_exact(img, target_w, target_h)

    out_bytes, fmt, _ext = _encode_under_limit(img, stem=stem)
    out_w, out_h = img.size
    return out_bytes, fmt, out_w, out_h, orig_w, orig_h


def save_optimized_image(
    data: bytes,
    *,
    stem: str,
    orientation: Orientation = "any",
    prefer_landscape_crop: bool = False,
    user_id: int | None = None,
    project_id: str | None = None,
) -> OptimizedImage:
    out_bytes, fmt, w, h, ow, oh = optimize_image_bytes(
        data,
        stem=stem,
        orientation=orientation,
        prefer_landscape_crop=prefer_landscape_crop,
    )
    ext = ".webp" if fmt == "WEBP" else ".jpg"
    fname = _seo_filename(stem) + ext
    if user_id is not None and int(user_id) > 0:
        from app.services.media_storage import save_private_image

        saved = save_private_image(
            user_id=int(user_id),
            data=out_bytes,
            suffix=ext,
            stem=stem,
            project_id=project_id,
        )
        local_url = saved["url"]
        fname = saved["name"]
    else:
        from app.services.media_storage import save_public_published_image

        saved = save_public_published_image(data=out_bytes, suffix=ext)
        local_url = saved["url"]
        fname = saved["name"]
    return OptimizedImage(
        local_url=local_url,
        filename=fname,
        format=fmt,
        width=w,
        height=h,
        bytes_size=len(out_bytes),
        original_width=ow,
        original_height=oh,
    )


def optimize_remote_image(
    url: str,
    *,
    stem: str,
    orientation: Orientation = "any",
    prefer_landscape_crop: bool = False,
    user_id: int | None = None,
    project_id: str | None = None,
) -> OptimizedImage:
    raw = download_image_bytes(url)
    return save_optimized_image(
        raw,
        stem=stem,
        orientation=orientation,
        prefer_landscape_crop=prefer_landscape_crop,
        user_id=user_id,
        project_id=project_id,
    )
