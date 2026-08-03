from __future__ import annotations

from typing import Any

from app.services.content_ai_content_images import auto_insert_images_to_project
from app.services.image_relevance import build_llm_image_search_query


def build_google_thumbnail_query(*, title: str, primary_keyword: str) -> str:
    return build_llm_image_search_query(
        primary_keyword=primary_keyword,
        title=title,
        section_heading="",
    )


def fetch_and_attach_google_thumbnail(project_id: str, *, user_id: int) -> dict[str, Any]:
    """Tìm ảnh + chèn vào content (alias của auto_insert_images_to_project)."""
    return auto_insert_images_to_project(project_id, user_id=user_id, update_featured=True, force=False)
