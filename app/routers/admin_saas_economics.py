"""Admin SaaS economics — chi phí, doanh thu, lợi nhuận."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.admin_saas_economics import (
    EconomicsDashboardResponse,
    EconomicsSettingsPatch,
    EconomicsUnblockResponse,
)
from app.services.rbac import require_admin_user
from app.services.saas_economics_service import (
    build_economics_dashboard,
    clear_expensive_api_block,
    evaluate_thresholds_and_block,
    load_economics_settings,
    save_economics_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/saas/economics", tags=["admin-saas-economics"])


@router.get("/dashboard", response_model=EconomicsDashboardResponse)
def admin_saas_economics_dashboard(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> EconomicsDashboardResponse:
    evaluate_thresholds_and_block(db, trigger="dashboard")
    db.commit()
    data = build_economics_dashboard(db)
    return EconomicsDashboardResponse.model_validate(data)


@router.get("/settings")
def admin_saas_economics_settings(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict:
    return load_economics_settings(db)


@router.patch("/settings")
def admin_saas_economics_patch_settings(
    payload: EconomicsSettingsPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    saved = save_economics_settings(db, patch)
    evaluate_thresholds_and_block(db, trigger="settings_update")
    db.commit()
    logger.info("saas_economics_settings_updated keys=%s", list(patch.keys()))
    return saved


@router.get("/dataforseo")
def admin_dataforseo_usage(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict:
    from app.services.dataforseo_billing_service import admin_dataforseo_cost_summary

    return admin_dataforseo_cost_summary(db)


@router.post("/unblock", response_model=EconomicsUnblockResponse)
def admin_saas_economics_unblock(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> EconomicsUnblockResponse:
    clear_expensive_api_block(db, admin_note=f"Admin {admin.id} gỡ chặn thủ công")
    db.commit()
    return EconomicsUnblockResponse(
        expensive_api_blocked=False,
        message="Đã gỡ chặn API đắt. Hệ thống sẽ tự chặn lại nếu vẫn vượt ngưỡng.",
    )
