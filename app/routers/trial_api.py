"""User-facing SaaS 3-day trial APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.saas_trial_service import (
    activate_saas_trial,
    client_ip,
    log_trial_audit,
    trial_status_payload,
)

router = APIRouter(prefix="/trial", tags=["trial"])


class TrialActivateBody(BaseModel):
    device_fingerprint: str | None = Field(default=None, max_length=128)


@router.get("/status")
def get_trial_status(
    request: Request,
    device_fingerprint: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return trial_status_payload(
        db,
        current_user,
        device_fingerprint=device_fingerprint,
        ip_address=client_ip(request),
    )


@router.post("/activate")
def activate_trial(
    body: TrialActivateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = activate_saas_trial(
        db,
        current_user,
        device_fingerprint=body.device_fingerprint,
        ip_address=client_ip(request),
    )
    log_trial_audit(
        db,
        action="activate_trial",
        user_id=current_user.id,
        detail={
            "trial_expires_at": result.get("trial_expires_at"),
            "device_fingerprint": bool(body.device_fingerprint),
        },
    )
    db.commit()
    return {"ok": True, **result}
