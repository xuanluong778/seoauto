from __future__ import annotations

import re
from typing import Any

from app.services.content_ai_openrouter_images import (
    aspect_ratio_for_openrouter,
    default_image_model,
    generate_image_bytes,
    generate_image_variants,
    generate_images_batch,
    normalize_image_model,
)
from app.services.content_ai_project_store import get_content_ai_project, update_content_ai_project_fields


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


def _save_image_bytes(
    data: bytes,
    *,
    stem: str = "ai-thumb",
    user_id: int | None = None,
    project_id: str | None = None,
) -> str:
    from app.services.content_ai_openrouter_images import _save_generated_image_bytes

    return _save_generated_image_bytes(
        data,
        stem=stem,
        user_id=user_id,
        project_id=project_id,
    )


def openai_size_for_aspect_ratio(aspect_ratio: str, *, model: str = "") -> str:
    """Legacy helper — OpenRouter uses aspect_ratio string."""
    return aspect_ratio_for_openrouter(aspect_ratio)


def openai_size_from_custom(width: int, height: int, *, model: str = "") -> tuple[str, str]:
    w = max(256, min(int(width or 1024), 2048))
    h = max(256, min(int(height or 1024), 2048))
    return f"{w}x{h}", f"{w}x{h}"


def _openai_generate_images_batch(
    *,
    prompt: str,
    size: str | None = None,
    n: int = 1,
    model: str | None = None,
    aspect_ratio: str = "16:9",
) -> list[bytes]:
    """Backward-compatible name — delegates to OpenRouter."""
    ar = aspect_ratio
    custom_w = custom_h = None
    if size and re.fullmatch(r"\d{2,4}x\d{2,4}", str(size).strip()):
        ar = str(size).strip()
    return generate_images_batch(
        prompt=prompt,
        model=model,
        aspect_ratio=ar,
        custom_width=custom_w,
        custom_height=custom_h,
        size=size,
        n=n,
    )


def _openai_generate_image_bytes(
    *,
    prompt: str,
    size: str | None = None,
    model: str | None = None,
    aspect_ratio: str = "16:9",
) -> bytes:
    return generate_image_bytes(
        prompt=prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        size=size,
    )


def generate_openai_image_variants(
    *,
    prompts: list[str],
    aspect_ratio: str = "16:9",
    stem: str = "studio",
    size: str | None = None,
    custom_width: int | None = None,
    custom_height: int | None = None,
    model: str | None = None,
    user_id: int | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generate 1..N images via OpenRouter (legacy export name)."""
    return generate_image_variants(
        prompts=prompts,
        aspect_ratio=aspect_ratio,
        stem=stem,
        model=model or default_image_model(),
        custom_width=custom_width,
        custom_height=custom_height,
        size=size,
        user_id=user_id,
        project_id=project_id,
    )


def generate_and_attach_project_thumbnail(project_id: str, *, user_id: int, model: str | None = None) -> dict[str, Any]:
    project = get_content_ai_project(project_id, user_id=user_id)
    if not project:
        raise ValueError("Không tìm thấy dự án.")
    title = str(project.get("title") or "").strip()
    pk = str(project.get("primary_keyword") or "").strip()
    prompt = build_thumbnail_prompt(title=title, primary_keyword=pk)
    image_bytes = generate_image_bytes(prompt=prompt, model=model)
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", pk or title or "thumb")[:40].strip("-") or "thumb"
    url = _save_image_bytes(image_bytes, stem=stem, user_id=user_id, project_id=project_id)
    updated = update_content_ai_project_fields(project_id, {"featured_image": url}, user_id=user_id)
    if not updated:
        raise ValueError("Không cập nhật được featured_image cho dự án.")
    return {
        "ok": True,
        "project_id": project_id,
        "featured_image": url,
        "prompt": prompt,
        "model": normalize_image_model(model),
        "project": updated,
    }
