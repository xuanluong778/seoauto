"""Format, resize, SEO filename/alt, and save helpers for Content AI images."""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import uuid4

IMAGE_MIN_PX = 256
IMAGE_MAX_PX = 2048
WEB_IMAGE_MIN_PX = 100
WEB_IMAGE_MAX_PX = 2048

_FORMAT_ALIASES: dict[str, str] = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "webp": "webp",
}

_FORMAT_EXT: dict[str, str] = {
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
}

_FORMAT_MIME: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

_SIZE_PRESETS: list[dict[str, Any]] = [
    {"id": "1536x1024", "width": 1536, "height": 1024, "label_vi": "1536×1024 (ngang blog)"},
    {"id": "1024x1024", "width": 1024, "height": 1024, "label_vi": "1024×1024 (vuông)"},
    {"id": "1200x630", "width": 1200, "height": 630, "label_vi": "1200×630 (social)"},
    {"id": "800x400", "width": 800, "height": 400, "label_vi": "800×400 (banner)"},
    {"id": "1024x1536", "width": 1024, "height": 1536, "label_vi": "1024×1536 (dọc)"},
]

_WEB_IMAGE_SIZE_PRESETS: list[dict[str, Any]] = [
    {"id": "800x400", "width": 800, "height": 400, "label_vi": "800×400"},
    {"id": "1200x630", "width": 1200, "height": 630, "label_vi": "1200×630"},
    {"id": "1024x576", "width": 1024, "height": 576, "label_vi": "1024×576 (16:9)"},
    {"id": "600x600", "width": 600, "height": 600, "label_vi": "600×600 (vuông)"},
]

_FAQ_HEADING_RE = re.compile(
    r"\b(faq|câu hỏi thường gặp|cau hoi thuong gap|hoi dap|questions?\s*&\s*answers?)\b",
    re.I,
)


def list_output_formats() -> list[dict[str, str]]:
    return [
        {"id": "webp", "label_vi": "WEBP"},
        {"id": "png", "label_vi": "PNG"},
        {"id": "jpeg", "label_vi": "JPEG / JPG"},
    ]


def list_size_presets() -> list[dict[str, Any]]:
    return [dict(p) for p in _SIZE_PRESETS]


def list_web_image_size_presets() -> list[dict[str, Any]]:
    return [dict(p) for p in _WEB_IMAGE_SIZE_PRESETS]


def validate_web_image_dimensions(width: int, height: int) -> tuple[int, int]:
    w = int(width or 0)
    h = int(height or 0)
    if w < WEB_IMAGE_MIN_PX or h < WEB_IMAGE_MIN_PX:
        raise ValueError(f"Kích thước tối thiểu {WEB_IMAGE_MIN_PX}px mỗi chiều.")
    if w > WEB_IMAGE_MAX_PX or h > WEB_IMAGE_MAX_PX:
        raise ValueError(f"Kích thước tối đa {WEB_IMAGE_MAX_PX}px mỗi chiều.")
    return w, h


def parse_web_image_size_preset(preset_id: str) -> tuple[int, int] | None:
    pid = str(preset_id or "").strip().lower()
    if not pid or pid in ("custom", "tu_chinh"):
        return None
    m = re.match(r"^(\d{2,4})x(\d{2,4})$", pid.replace("×", "x"))
    if m:
        return validate_web_image_dimensions(int(m.group(1)), int(m.group(2)))
    for p in _WEB_IMAGE_SIZE_PRESETS:
        if str(p.get("id") or "").lower() == pid:
            return validate_web_image_dimensions(int(p["width"]), int(p["height"]))
    return None


def resolve_web_image_dimensions(
    *,
    size_preset: str = "",
    target_width: int | None = None,
    target_height: int | None = None,
) -> tuple[int | None, int | None]:
    if target_width and target_height:
        w, h = validate_web_image_dimensions(target_width, target_height)
        return w, h
    dims = parse_web_image_size_preset(size_preset)
    if dims:
        return dims
    return None, None


def normalize_output_format(fmt: str, *, default: str = "png") -> str:
    raw = str(fmt or "").strip().lower().lstrip(".")
    return _FORMAT_ALIASES.get(raw, _FORMAT_ALIASES.get(default, "png"))


def validate_dimensions(
    width: int,
    height: int,
    *,
    min_px: int | None = None,
    max_px: int | None = None,
) -> tuple[int, int]:
    w = int(width or 0)
    h = int(height or 0)
    lo = int(min_px if min_px is not None else IMAGE_MIN_PX)
    hi = int(max_px if max_px is not None else IMAGE_MAX_PX)
    if w < lo or h < lo:
        raise ValueError(f"Kích thước tối thiểu {lo}px mỗi chiều.")
    if w > hi or h > hi:
        raise ValueError(f"Kích thước tối đa {hi}px mỗi chiều.")
    return w, h


def parse_size_preset(preset_id: str) -> tuple[int, int] | None:
    pid = str(preset_id or "").strip().lower()
    if not pid or pid in ("custom", "tu_chinh", "aspect"):
        return None
    m = re.match(r"^(\d{3,4})x(\d{3,4})$", pid.replace("×", "x"))
    if m:
        return validate_dimensions(int(m.group(1)), int(m.group(2)))
    for p in _SIZE_PRESETS:
        if str(p.get("id") or "").lower() == pid:
            return validate_dimensions(int(p["width"]), int(p["height"]))
    return None


def slugify_seo(text: str, *, max_len: int = 48) -> str:
    t = str(text or "").replace("Đ", "D").replace("đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    t = re.sub(r"-{2,}", "-", t)
    return t[:max_len].strip("-") or "anh-minh-hoa"


def build_seo_image_filename(
    primary_keyword: str,
    *,
    section_heading: str = "",
    variation_index: int = 0,
    output_format: str = "webp",
) -> str:
    """e.g. sua-laptop-tai-nha-quan-7.webp"""
    fmt = normalize_output_format(output_format)
    ext = _FORMAT_EXT[fmt]
    pk = slugify_seo(primary_keyword, max_len=42)
    h = slugify_seo(section_heading, max_len=36) if section_heading else ""
    parts: list[str] = []
    if h and h != pk and not pk.startswith(h) and h not in pk:
        parts.append(h)
    parts.append(pk)
    stem = "-".join(p for p in parts if p) or "anh-minh-hoa"
    if variation_index > 0:
        stem = f"{stem}-v{variation_index + 1}"
    return f"{stem}{ext}"


def build_seo_image_alt(
    *,
    primary_keyword: str,
    section_heading: str = "",
    section_summary: str = "",
    title: str = "",
) -> str:
    """ALT tự nhiên, có ngữ cảnh — ví dụ: Kỹ thuật viên sửa laptop tại nhà Quận 7."""
    kw = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    heading = re.sub(r"\s+", " ", str(section_heading or "").strip())
    summary = re.sub(r"\s+", " ", str(section_summary or "").strip())[:160]
    ttl = re.sub(r"\s+", " ", str(title or "").strip())

    if heading and kw:
        kw_l, head_l = kw.lower(), heading.lower()
        if kw_l in head_l:
            alt = heading
        elif head_l in kw_l:
            alt = kw
        else:
            alt = f"{heading} — {kw}"
    elif heading:
        alt = heading
    elif kw:
        alt = kw
    elif ttl:
        alt = ttl
    else:
        alt = "Minh họa bài viết"

    if summary and len(alt) < 72:
        first = summary.split(".")[0].strip()
        if first and len(first) > 12 and first.lower() not in alt.lower():
            if not heading:
                alt = first[0].upper() + first[1:] if first else alt
            elif len(first) <= 90:
                alt = first[0].upper() + first[1:] if first else alt

    alt = re.sub(r"\s+", " ", alt).strip()
    if len(alt) > 125:
        alt = alt[:122].rstrip(" ,—-") + "…"
    return alt


def _fold_vn_ascii(s: str) -> str:
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").casefold()


def is_faq_heading(heading: str) -> bool:
    if not heading:
        return False
    folded = _fold_vn_ascii(heading)
    return bool(_FAQ_HEADING_RE.search(folded) or _FAQ_HEADING_RE.search(heading))


def process_image_bytes(
    data: bytes,
    *,
    output_format: str = "png",
    width: int | None = None,
    height: int | None = None,
    quality: int = 88,
    min_px: int | None = None,
) -> tuple[bytes, str, str]:
    """
    Resize and encode image. Returns (bytes, extension_with_dot, mime_type).
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Thiếu thư viện Pillow — cài pillow để xử lý định dạng/kích thước ảnh.") from exc

    fmt = normalize_output_format(output_format)
    img = Image.open(io.BytesIO(data))
    if width and height:
        w, h = validate_dimensions(width, height, min_px=min_px)
        resample = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((w, h), resample)

    buf = io.BytesIO()
    if fmt == "jpeg":
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=max(60, min(int(quality), 95)), optimize=True)
    elif fmt == "webp":
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(buf, format="WEBP", quality=max(60, min(int(quality), 95)), method=4)
    else:
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        img.save(buf, format="PNG", optimize=True)

    ext = _FORMAT_EXT[fmt]
    return buf.getvalue(), ext, _FORMAT_MIME[fmt]


def save_content_ai_image(
    data: bytes,
    *,
    filename: str,
    output_format: str | None = None,
    width: int | None = None,
    height: int | None = None,
    min_px: int | None = None,
) -> str:
    """Save under static/uploads/content-ai/ with optional resize/format."""
    raw_name = str(filename or "").strip()
    if output_format or (width and height):
        fmt = normalize_output_format(output_format or Path(raw_name).suffix.lstrip(".") or "png")
        data, ext, _mime = process_image_bytes(
            data,
            output_format=fmt,
            width=width,
            height=height,
            min_px=min_px,
        )
        base = Path(raw_name).stem
        if not base.endswith(ext.replace(".", "")):
            raw_name = f"{base}{ext}"
    else:
        ext = Path(raw_name).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = _detect_ext_from_bytes(data)
            raw_name = f"{Path(raw_name).stem}{ext}"

    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip("-").lower()
    if not safe or safe in (".png", ".jpg", ".jpeg", ".webp"):
        fallback_ext = _detect_ext_from_bytes(data)
        safe = f"anh-{uuid4().hex[:10]}{fallback_ext}"

    target_dir = Path("static") / "uploads" / "content-ai"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe
    if target.exists():
        stem, suffix = target.stem, target.suffix
        target = target_dir / f"{stem}-{uuid4().hex[:6]}{suffix}"
    target.write_bytes(data)
    return f"/static/uploads/content-ai/{target.name}"


def _detect_ext_from_bytes(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def read_local_content_ai_image(url: str) -> bytes:
    raw = str(url or "").strip()
    if raw.startswith("/static/uploads/content-ai/"):
        path = Path("static") / "uploads" / "content-ai" / Path(raw).name
        if path.is_file():
            return path.read_bytes()
    raise ValueError("Không đọc được file ảnh local.")


def reencode_content_ai_image_at_url(
    url: str,
    *,
    output_format: str,
    width: int | None = None,
    height: int | None = None,
    filename: str | None = None,
) -> str:
    """Re-save an existing studio upload with new format/size (SEO filename optional)."""
    data = read_local_content_ai_image(url)
    fmt = normalize_output_format(output_format)
    if width and height:
        w, h = validate_dimensions(width, height)
    else:
        w, h = None, None
    name = filename or Path(str(url).split("/")[-1]).name
    if filename:
        if not name.lower().endswith(_FORMAT_EXT[fmt]):
            name = f"{Path(name).stem}{_FORMAT_EXT[fmt]}"
    return save_content_ai_image(
        data, filename=name, output_format=fmt, width=w, height=h
    )


def figure_snippet_seo(
    url: str,
    alt: str,
    *,
    width: int | None = None,
    height: int | None = None,
    caption: str = "",
) -> str:
    from html import escape

    alt_esc = escape(str(alt or "").strip()[:200])
    cap = str(caption or "").strip()[:200]
    cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
    attrs = ['loading="lazy"', 'decoding="async"']
    if width and int(width) > 0:
        attrs.append(f'width="{int(width)}"')
    if height and int(height) > 0:
        attrs.append(f'height="{int(height)}"')
    attr_s = " ".join(attrs)
    return (
        f'<figure class="editor-image content-ai-inline-image content-ai-web-image">'
        f'<img src="{url}" alt="{alt_esc}" {attr_s} />{cap_html}</figure>'
    )
