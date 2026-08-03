"""SERP intelligence API — keyword competition, difficulty, opportunity (optional crawl context)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.serp_intel_bundle import build_serp_keyword_report

router = APIRouter(tags=["serp-intel"])


class SerpIntelRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=500)
    search_volume: int | None = Field(default=None, ge=0)
    your_pages: list[dict[str, Any]] = Field(default_factory=list)
    crawl_data: dict[str, dict[str, Any]] = Field(default_factory=dict)
    topical_authority_score: float | None = Field(default=None, ge=0, le=100)
    location: str = "US"
    device: str = "desktop"


@router.post("/api/serp/keyword-intelligence")
def post_keyword_intelligence(body: SerpIntelRequest) -> dict[str, Any]:
    """
    Full SERP report (mock SERP without ``SERPAPI_KEY``; live with SerpAPI).

    Pass ``your_pages`` from crawl + ranking (``url``, ``ranking_score``, ``pagerank_score``, ``word_count``,
    ``primary_topic``, ``title``) and optional ``crawl_data`` URL → metrics for internal-overlap authority.
    """
    return build_serp_keyword_report(
        body.keyword.strip(),
        search_volume=body.search_volume,
        your_pages=body.your_pages,
        crawl_data=body.crawl_data,
        topical_authority_score=body.topical_authority_score,
        location=body.location or "US",
        device=body.device or "desktop",
    )
