"""
Keyword Intelligence UI + JSON API.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.cost_control.runtime import check_user_rate_limit
from app.services.credits import cost_keyword_intelligence, credits_enforced
from app.services.keyword_intelligence_api import build_keyword_intelligence_response
from app.services.saas_gate import build_job_id, saas_action_gate
from app.services.tenant_org import personal_organization_id
from app.services.trial_access import require_active_trial

router = APIRouter(tags=["keyword-intelligence"])
templates = Jinja2Templates(directory="templates")

_KI_RATE_PER_MIN = 10


def _run_gated(
    db: Session,
    user: User,
    *,
    seed_keyword: str | None,
    seed_keywords: list[str] | None = None,
    domain: str | None,
    url: str | None,
    gsc_queries=None,
    pages=None,
    ranking_decision_v3=None,
) -> dict:
    check_user_rate_limit(
        scope="keyword_intelligence",
        user_id=int(user.id),
        limit_per_min=_KI_RATE_PER_MIN,
    )
    org_id = personal_organization_id(int(user.id))
    credit_cost = cost_keyword_intelligence(db=db) if credits_enforced() else 0
    job_id = build_job_id("keyword_intelligence", user.id, org_id, uuid.uuid4().hex[:10])
    with saas_action_gate(
        db,
        user,
        feature_code="keyword_research",
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        organization_id=org_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            payload = build_keyword_intelligence_response(
                seed_keyword=seed_keyword,
                seed_keywords=seed_keywords or [],
                domain=domain,
                url=url,
                gsc_queries=gsc_queries,
                pages=pages,
                ranking_decision_v3=ranking_decision_v3,
            )
            sgate.commit()
            sgate.record_usage(metadata={"organization_id": org_id})
            return payload
        except Exception:
            sgate.release(reason="keyword_intelligence_failed")
            raise


@router.get("/api/keyword-intelligence")
def api_keyword_intelligence(
    seed_keyword: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    url: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    payload = _run_gated(
        db,
        current_user,
        seed_keyword=seed_keyword,
        domain=domain,
        url=url,
    )
    return JSONResponse(content=payload)


@router.post("/api/keyword-intelligence")
async def api_keyword_intelligence_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "JSON object required"})
    seeds = body.get("seed_keywords") or body.get("seeds")
    if isinstance(seeds, str):
        seeds = [s.strip() for s in seeds.split(",") if s.strip()]
    if not isinstance(seeds, list):
        seeds = []
    gsc = body.get("gsc_queries")
    if gsc is not None and not isinstance(gsc, list):
        gsc = None
    payload = _run_gated(
        db,
        current_user,
        seed_keyword=str(body.get("seed_keyword") or "").strip() or None,
        seed_keywords=[str(s).strip() for s in seeds if str(s).strip()],
        domain=str(body.get("domain") or "").strip() or None,
        url=str(body.get("url") or "").strip() or None,
        gsc_queries=gsc,
        pages=body.get("pages") if isinstance(body.get("pages"), list) else None,
        ranking_decision_v3=body.get("ranking_decision_v3")
        if isinstance(body.get("ranking_decision_v3"), dict)
        else None,
    )
    return JSONResponse(content=payload)


@router.get("/keyword-intelligence", response_class=HTMLResponse)
def keyword_intelligence_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="keyword_intelligence.html",
        context={"initial_json": "{}"},
    )
