from __future__ import annotations

import base64
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from dotenv import dotenv_values

from app.services.content_ai_project_store import get_content_ai_project, update_content_ai_project_fields


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str | None]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    return dotenv_values(env_file) if env_file.exists() else {}


def _getenv(name: str, default: str = "") -> str:
    return str((os.getenv(name) or _env_map().get(name) or default)).strip()


def _clean_label(text: str, *, max_len: int = 200) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    s = re.sub(r"[|]+", " ", s)
    return s[:max_len].strip()


def build_section_image_prompt(
    *,
    title: str,
    primary_keyword: str,
    section_heading: str = "",
    section_content: str = "",
    brand_name: str = "",
    target_audience: str = "",
    industry: str = "",
    image_style: str = "",
) -> str:
    """Prompt ảnh minh họa trong bài — delegate tới build_seo_image_generation_prompt."""
    from app.services.content_image_context import (
        build_seo_image_generation_prompt,
        get_default_content_ai_image_style,
    )

    return build_seo_image_generation_prompt(
        main_keyword=primary_keyword,
        article_title=title,
        section_heading=section_heading or title,
        section_summary=section_content,
        brand_name=brand_name,
        industry=industry,
        target_audience=target_audience,
        image_style=image_style or get_default_content_ai_image_style(),
        language="vi",
        include_brand_logo=False,
    )


def build_thumbnail_prompt(*, title: str, primary_keyword: str) -> str:
    from app.services.content_image_context import (
        build_seo_image_generation_prompt,
        get_default_content_ai_image_style,
    )

    return build_seo_image_generation_prompt(
        main_keyword=primary_keyword,
        article_title=title,
        section_heading="",
        section_summary="",
        image_style=get_default_content_ai_image_style(),
        language="vi",
        include_brand_logo=False,
    )


def _save_image_bytes(data: bytes, *, stem: str = "ai-thumb") -> str:
    ext = ".png"
    if data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "ai-thumb"
    target_dir = Path("static") / "uploads" / "content-ai"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{safe_stem}-{uuid4().hex[:10]}{ext}"
    target_file = target_dir / target_name
    target_file.write_bytes(data)
    return f"/static/uploads/content-ai/{target_name}"


def openai_size_for_aspect_ratio(aspect_ratio: str, *, model: str = "") -> str:
    """Map UI aspect ratio to OpenAI Images size string."""
    m = (model or _getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")).strip()
    ar = str(aspect_ratio or "16:9").strip().lower()
    if ar in ("1:1", "square"):
        return "1024x1024"
    if ar in ("9:16", "portrait", "vertical"):
        return "1024x1536" if m.startswith("gpt-image") else "1024x1792"
    if ar in ("4:3", "4x3"):
        return "1536x1024" if m.startswith("gpt-image") else "1024x768"
    if ar in ("3:2",):
        return "1536x1024" if m.startswith("gpt-image") else "1024x683"
    # 16:9 landscape default
    return "1536x1024" if m.startswith("gpt-image") else "1792x1024"


def openai_size_from_custom(width: int, height: int, *, model: str = "") -> tuple[str, str]:
    """
    Map user px (e.g. 800x400) to nearest OpenAI Images API size.
    Returns (api_size, aspect_label for prompt e.g. '800x400').
    """
    m = (model or _getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")).strip()
    w = max(256, min(int(width or 1024), 2048))
    h = max(256, min(int(height or 1024), 2048))
    label = f"{w}x{h}"
    ratio = w / h if h else 1.0
    if 0.92 <= ratio <= 1.08:
        api = "1024x1024"
    elif ratio > 1.08:
        api = "1536x1024" if m.startswith("gpt-image") else "1792x1024"
    else:
        api = "1024x1536" if m.startswith("gpt-image") else "1024x1792"
    return api, label


def _openai_generate_images_batch(*, prompt: str, size: str | None = None, n: int = 1) -> list[bytes]:
    api_key = _getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Thiếu OPENAI_API_KEY trong env.local để tạo ảnh AI.")
    model = _getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    default_size = "1536x1024" if model.startswith("gpt-image") else "1024x1024"
    req_size = (size or "").strip() or _getenv("OPENAI_IMAGE_SIZE", default_size)
    count = max(1, min(int(n or 1), 4))
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt[:3900],
        "n": count,
        "size": req_size,
    }
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
    except Exception as exc:
        raise ValueError(f"Không gọi được OpenAI Images: {exc}") from exc
    if r.status_code != 200:
        detail = (r.text or "")[:400]
        raise ValueError(f"OpenAI Images lỗi HTTP {r.status_code}: {detail}")
    data = r.json() if r.content else {}
    items = data.get("data") or []
    if not items:
        raise ValueError("OpenAI Images không trả về ảnh.")
    out: list[bytes] = []
    for item in items[:count]:
        if not isinstance(item, dict):
            continue
        b64 = str(item.get("b64_json") or "").strip()
        if b64:
            out.append(base64.b64decode(b64))
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        try:
            img = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            raise ValueError(f"Không tải ảnh từ OpenAI: {exc}") from exc
        if img.status_code != 200:
            raise ValueError(f"Không tải ảnh từ OpenAI (HTTP {img.status_code}).")
        out.append(img.content)
    if not out:
        raise ValueError("OpenAI Images không có dữ liệu ảnh hợp lệ.")
    return out


def _openai_generate_image_bytes(*, prompt: str, size: str | None = None) -> bytes:
    return _openai_generate_images_batch(prompt=prompt, size=size, n=1)[0]


def generate_openai_image_variants(
    *,
    prompts: list[str],
    aspect_ratio: str = "16:9",
    stem: str = "studio",
    size: str | None = None,
    custom_width: int | None = None,
    custom_height: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generate 1..N images (one API call per prompt for reliable variation).
    Returns list of {url, prompt, index}.
    """
    api_key = _getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "Thiếu OPENAI_API_KEY trong env.local. Thêm khóa API để dùng AI Visual Content Studio."
        )
    model = _getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
    aspect_label = str(aspect_ratio or "16:9")
    if custom_width and custom_height:
        api_size, aspect_label = openai_size_from_custom(custom_width, custom_height, model=model)
        req_size = api_size
    elif size:
        req_size = str(size).strip()
    else:
        req_size = openai_size_for_aspect_ratio(aspect_ratio, model=model)
    results: list[dict[str, Any]] = []
    for i, prompt in enumerate(prompts):
        p = str(prompt or "").strip()
        if not p:
            continue
        try:
            blobs = _openai_generate_images_batch(prompt=p, size=req_size, n=1)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Model ảnh lỗi (biến thể {i + 1}): {exc}") from exc
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "studio"
        url = _save_image_bytes(blobs[0], stem=f"{safe_stem}-v{i + 1}")
        results.append(
            {"url": url, "prompt": p, "index": i, "size": req_size, "aspect_label": aspect_label, "model": model}
        )
    if not results:
        raise ValueError("Không tạo được ảnh preview — kiểm tra prompt và OPENAI_IMAGE_MODEL.")
    return results


def generate_and_attach_project_thumbnail(project_id: str, *, user_id: int) -> dict[str, Any]:
    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise ValueError("Không tìm thấy dự án.")
    title = str(project.get("title") or "").strip()
    pk = str(project.get("primary_keyword") or "").strip()
    prompt = build_thumbnail_prompt(title=title, primary_keyword=pk)
    image_bytes = _openai_generate_image_bytes(prompt=prompt)  # single bytes
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", pk or title or "thumb")[:40].strip("-") or "thumb"
    url = _save_image_bytes(image_bytes, stem=stem)
    updated = update_content_ai_project_fields(project_id, {"featured_image": url}, user_id=user_id)
    if not updated:
        raise ValueError("Không cập nhật được featured_image cho dự án.")
    return {
        "ok": True,
        "project_id": project_id,
        "featured_image": url,
        "prompt": prompt,
        "project": updated,
    }
