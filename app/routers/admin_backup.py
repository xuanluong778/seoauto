"""Admin backup APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.admin_backup import (
    AdminBackupActionResponse,
    AdminBackupRunDetail,
    AdminBackupRunListResponse,
    AdminBackupRunRow,
    AdminBackupStatusResponse,
)
from app.services.admin_backup_service import (
    get_backup_run_admin,
    get_backup_status_admin,
    list_backup_runs_admin,
    log_admin_backup_action,
    parse_manifest,
    trigger_backup_admin,
    verify_backup_admin,
)
from app.services.rbac import require_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backup", tags=["admin-backup"])


@router.get("/runs", response_model=AdminBackupRunListResponse)
def admin_list_backup_runs(
    request: Request,
    backup_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBackupRunListResponse:
    data = list_backup_runs_admin(db, backup_type=backup_type, status=status, limit=limit, offset=offset)
    log_admin_backup_action("list", admin, detail={"total": data["total"]}, request=request)
    db.commit()
    return AdminBackupRunListResponse(
        items=[AdminBackupRunRow.model_validate(x) for x in data["items"]],
        total=data["total"],
        limit=data["limit"],
        offset=data["offset"],
    )


@router.get("/status", response_model=AdminBackupStatusResponse)
def admin_backup_status(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBackupStatusResponse:
    data = get_backup_status_admin(db)
    last = {}
    for k, v in data["last_runs"].items():
        last[k] = AdminBackupRunRow.model_validate(v) if v else None
    return AdminBackupStatusResponse(last_runs=last, timers=data["timers"], lock_active=data["lock_active"])


@router.get("/runs/{run_id}", response_model=AdminBackupRunDetail)
def admin_get_backup_run(
    run_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBackupRunDetail:
    row = get_backup_run_admin(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy backup.")
    d = AdminBackupRunDetail.model_validate(row)
    d.manifest = parse_manifest(row)
    return d


@router.post("/trigger", response_model=AdminBackupActionResponse)
def admin_trigger_backup(
    request: Request,
    mode: str = Query(default="db"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBackupActionResponse:
    result = trigger_backup_admin(db, admin, mode)
    log_admin_backup_action("trigger", admin, detail={"mode": mode, "ok": result["ok"]}, request=request)
    db.commit()
    return AdminBackupActionResponse(ok=result["ok"], message=result["message"], run_id=result.get("run_id"))


@router.post("/runs/{run_id}/verify", response_model=AdminBackupActionResponse)
def admin_verify_backup(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBackupActionResponse:
    result = verify_backup_admin(db, run_id)
    log_admin_backup_action("verify", admin, detail={"run_id": run_id, "ok": result["ok"]}, request=request)
    db.commit()
    return AdminBackupActionResponse(ok=result["ok"], message=result["message"], run_id=run_id)
