"""Request/response cho tab chấm điểm SEO 1 URL."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UrlSeoScoreboardRequest(BaseModel):
    url: str = Field(..., min_length=4, description="URL cần chấm điểm (http/https).")
    keyword: str | None = Field(default=None, description="Từ khóa chính (primary keyword).")
    secondary_keywords: list[str] | None = Field(
        default=None,
        description="Từ khóa phụ — danh sách hoặc chuỗi phân tách dấu phẩy.",
    )
    page_type: str | None = Field(
        default=None,
        description="homepage | article | category | product | landing | unknown",
    )
    search_volume: int | None = Field(
        default=None,
        ge=0,
        description="Volume/tháng (tùy chọn) để ước tính traffic khi tối ưu.",
    )
    current_serp_position: int | None = Field(
        default=None,
        ge=1,
        le=101,
        description="Thứ hạng hiện tại trên Google (1 = top), nếu biết — tinh chỉnh CTR & opportunity.",
    )


class SeoEvidenceFields(BaseModel):
    """Dữ liệu gốc gắn vào từng issue/check (backward-compatible — tất cả optional)."""

    issue_id: str | None = None
    group_key: str | None = None
    current_value: Any | None = None
    current_length: int | None = None
    recommended_value: str | None = None
    recommended_length: dict[str, int] | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    affected_element: str | None = None
    page_field: str | None = None
    can_ai_fix: bool = False
    can_apply: bool = False


class LinkProfileEvidence(BaseModel):
    """Dữ liệu phân tích link cho nhóm Internal / External Link."""

    internal_links_count: int = 0
    external_links_count: int = 0
    total_links_count: int = 0
    broken_links: list[dict[str, Any]] = Field(default_factory=list)
    anchor_texts: list[dict[str, Any]] = Field(default_factory=list)
    nofollow_count: int = 0
    dofollow_count: int = 0
    links: list[dict[str, Any]] = Field(default_factory=list)
    link_opportunities: list[str] = Field(default_factory=list)
    partial_data: bool = False
    warning: str | None = None


class UrlSeoScoreboardResponse(BaseModel):
    url: str
    normalized_url: str
    fetch: dict[str, Any]
    scores: dict[str, Any]
    breakdown: dict[str, Any]
    issues: list[dict[str, Any]]
    serp: dict[str, Any] | None
    opportunity: dict[str, Any] | None
    weights: dict[str, float]
    pillar_definitions: dict[str, str] = Field(default_factory=dict)
    page_snapshot: dict[str, Any] = Field(default_factory=dict)
    page_evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Dữ liệu gốc theo page_field (title, meta_description, headings, images, schema, links).",
    )
    link_profile: LinkProfileEvidence | dict[str, Any] | None = Field(
        default=None,
        description="Phân tích link (internal/external/anchor/nofollow) — mirror từ page_evidence.links.evidence.",
    )
    editorial_checklist: dict[str, Any] = Field(default_factory=dict)
    fifteen_pillar_assessment: dict[str, Any] = Field(default_factory=dict)
    serp_top10_crawl: dict[str, Any] = Field(default_factory=dict)
    optimization_report: dict[str, Any] = Field(default_factory=dict)
    ten_group_scoreboard: dict[str, Any] = Field(
        default_factory=dict,
        description="Chấm điểm 10 nhóm (total_score, group_scores, groups, strengths, …).",
    )
    generated_at: str
