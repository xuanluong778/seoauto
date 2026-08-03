"""Request/response schemas for SEO Score AI fix."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SeoScoreAiFixRequest(BaseModel):
    url: str = Field(..., min_length=4, description="URL trang đang chấm điểm")
    keyword: str = Field(default="", description="Từ khóa chính")
    group_key: str = Field(default="", description="Nhóm SEO Score (vd. title_meta_slug)")
    issue_id: str = Field(default="", description="ID check/issue đang sửa")
    page_field: str = Field(..., description="Trường cần sửa: title | meta_description | heading | image_alt | …")
    current_value: Any = Field(default=None, description="Giá trị hiện tại trên trang")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Bằng chứng / ngữ cảnh từ scoreboard")


class SeoScoreAiFixResponse(BaseModel):
    before: Any = None
    after: Any = None
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    credit: dict[str, Any] | None = None
