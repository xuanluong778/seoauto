"""Admin APIs — third-party integration configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.admin_integrations import (
    SinbyteActionResponse,
    SinbyteSaveRequest,
    SinbyteStatusResponse,
)
from app.services.platform_integration_store import (
    PROVIDER_SINBYTE,
    delete_api_key,
    get_integration_status,
    save_api_key,
)
from app.services.rbac import require_admin_user
from app.services.security_audit_log import log_audit_event
from app.services.sinbyte_service import test_connection

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


def _status(db: Session) -> SinbyteStatusResponse:
    return SinbyteStatusResponse.model_validate(get_integration_status(db, PROVIDER_SINBYTE))


@router.get("/sinbyte/status", response_model=SinbyteStatusResponse)
def admin_sinbyte_status(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> SinbyteStatusResponse:
    return _status(db)


@router.post("/sinbyte/save", response_model=SinbyteActionResponse)
def admin_sinbyte_save(
    body: SinbyteSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> SinbyteActionResponse:
    try:
        save_api_key(db, provider=PROVIDER_SINBYTE, api_key=body.api_key, user_id=admin.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="API key không hợp lệ.")

    log_audit_event(
        action="admin.integration.sinbyte.save",
        user_id=admin.id,
        resource_type="platform_integration",
        resource_id=PROVIDER_SINBYTE,
        detail={"masked": True},
        request=request,
    )
    db.commit()

    status = _status(db)
    return SinbyteActionResponse(
        ok=True,
        message="Đã lưu API key Sinbyte.",
        api_key_masked=status.api_key_masked,
        status=status,
    )


@router.post("/sinbyte/test", response_model=SinbyteActionResponse)
def admin_sinbyte_test(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> SinbyteActionResponse:
    result = test_connection(db)
    log_audit_event(
        action="admin.integration.sinbyte.test",
        user_id=admin.id,
        resource_type="platform_integration",
        resource_id=PROVIDER_SINBYTE,
        detail={"ok": result.get("ok"), "connected": result.get("connected")},
        request=request,
    )
    db.commit()

    status = _status(db)
    return SinbyteActionResponse(
        ok=bool(result.get("ok")),
        message=str(result.get("message") or ""),
        connected=bool(result.get("connected")),
        api_key_masked=status.api_key_masked,
        status=status,
    )


@router.delete("/sinbyte", response_model=SinbyteActionResponse)
def admin_sinbyte_delete(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> SinbyteActionResponse:
    delete_api_key(db, provider=PROVIDER_SINBYTE)
    log_audit_event(
        action="admin.integration.sinbyte.delete",
        user_id=admin.id,
        resource_type="platform_integration",
        resource_id=PROVIDER_SINBYTE,
        detail={},
        request=request,
    )
    db.commit()

    status = _status(db)
    return SinbyteActionResponse(
        ok=True,
        message="Đã xóa API key Sinbyte khỏi cơ sở dữ liệu.",
        connected=status.connected,
        api_key_masked=status.api_key_masked,
        status=status,
    )
