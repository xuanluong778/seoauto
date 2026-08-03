"""Request/response for applying SEO Score AI fix to WordPress."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SeoScoreApplyFixRequest(BaseModel):
    project_id: int | None = Field(default=None, description="Project đã kết nối WP (tự resolve từ URL nếu thiếu)")
    url: str = Field(..., min_length=4)
    page_field: str
    before: Any = None
    after: Any = None
    issue_id: str = ""


class SeoScoreApplyFixResponse(BaseModel):
    ok: bool = True
    applied: bool = False
    manual_only: bool = False
    message: str = ""
    page_field: str = ""
    applied_value: Any = None
    wp_id: int | None = None
    post_url: str | None = None
    site_id: str | None = None
    project_id: int | None = None
