"""Admin APIs — Lead Map Scanner cost control."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.google_map_lead_scanner_service import admin_usage_stats
from app.services.rbac import require_admin_user

router = APIRouter(prefix="/lead-scanner", tags=["admin-lead-scanner"])


@router.get("/status")
def admin_lead_scanner_status(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict:
    return admin_usage_stats(db)
