"""SERP intelligence API — keyword competition, difficulty, opportunity (optional crawl context)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.cost_control.runtime import check_user_rate_limit
from app.services.credits import cost_serp_keyword_intelligence, credits_enforced
from app.services.saas_gate import build_job_id, saas_action_gate
from app.services.serp_intel_bundle import build_serp_keyword_report
from app.services.tenant_org import personal_organization_id
from app.services.trial_access import require_active_trial

router = APIRouter(tags=["serp-intel"])

_SERP_INTEL_RATE_PER_MIN = 10


class SerpIntelRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=500)
    search_volume: int | None = Field(default=None, ge=0)
    your_pages: list[dict[str, Any]] = Field(default_factory=list)
    crawl_data: dict[str, dict[str, Any]] = Field(default_factory=dict)
    topical_authority_score: float | None = Field(default=None, ge=0, le=100)
    location: str = "US"
    device: str = "desktop"


@router.post("/api/serp/keyword-intelligence")
def post_keyword_intelligence(
    body: SerpIntelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    """
    Full SERP report (mock SERP without ``SERPAPI_KEY``; live with SerpAPI).

    Auth + tenant + SaaS gate + rate limit required — never public.
    """
    check_user_rate_limit(
        scope="serp_keyword_intelligence",
        user_id=int(current_user.id),
        limit_per_min=_SERP_INTEL_RATE_PER_MIN,
    )
    org_id = personal_organization_id(int(current_user.id))
    credit_cost = cost_serp_keyword_intelligence(db=db) if credits_enforced() else 0
    job_id = build_job_id("serp_keyword_intelligence", current_user.id, org_id, uuid.uuid4().hex[:10])
    with saas_action_gate(
        db,
        current_user,
        feature_code="keyword_research",
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        organization_id=org_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            out = build_serp_keyword_report(
                body.keyword.strip(),
                search_volume=body.search_volume,
                your_pages=body.your_pages,
                crawl_data=body.crawl_data,
                topical_authority_score=body.topical_authority_score,
                location=body.location or "US",
                device=body.device or "desktop",
            )
            sgate.commit()
            sgate.record_usage(metadata={"organization_id": org_id})
            return out
        except Exception:
            sgate.release(reason="serp_intel_failed")
            raise
