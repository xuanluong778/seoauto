"""User-facing SaaS read APIs (Phase 1c/1d — no enforcement)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.saas import PlanListResponse, PlanResponse, SaasMeResponse, UsageLimitResponse
from app.services.auth import get_current_user
from app.services import plan_service
from app.services.saas_pricing_service import PUBLIC_PRICING_SLUGS
from app.services.saas_user_service import build_saas_me_response

router = APIRouter(prefix="/saas", tags=["saas"])


def _plan_to_public_response(plan) -> PlanResponse:
    limits = getattr(plan, "usage_limits", None) or []
    return PlanResponse(
        id=plan.id,
        slug=plan.slug,
        name=plan.name,
        description=plan.description,
        price_amount=plan.price_amount,
        currency=plan.currency,
        billing_cycle=plan.billing_cycle,
        is_active=plan.is_active,
        is_public=plan.is_public,
        sort_order=plan.sort_order,
        usage_limits=[UsageLimitResponse.model_validate(ul) for ul in limits],
    )


@router.get("/plans", response_model=PlanListResponse)
def list_public_plans(db: Session = Depends(get_db)) -> PlanListResponse:
    """Public pricing catalog (no auth)."""
    items = []
    for plan in plan_service.list_active_plans(db, public_only=True):
        if plan.slug not in PUBLIC_PRICING_SLUGS:
            continue
        full = plan_service.get_plan_with_limits(db, plan.id) or plan
        items.append(_plan_to_public_response(full))
    return PlanListResponse(items=items, total=len(items))


@router.get("/me", response_model=SaasMeResponse)
def saas_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SaasMeResponse:
    """Current user's plan, subscription period, and monthly quotas (read-only)."""
    return build_saas_me_response(db, current_user)
