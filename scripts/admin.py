"""Admin panel: user management and per-user data inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth_request import optional_user_from_request
from app.services.admin_auth import is_platform_admin
from app.schemas.admin import (
    AdminAuditListResponse,
    AdminAuditLogRow,
    AdminUserApiAccessUpdate,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserRoleUpdate,
    AdminUserStatusUpdate,
)
from app.services.admin_service import (
    get_user_detail,
    list_admin_audit_logs,
    list_users,
    update_user_api_access,
    update_user_role,
    update_user_status,
)
from app.services.rbac import require_admin_user
from app.services.security_audit_log import log_audit_event

router = APIRouter(tags=["admin"])
api_router = APIRouter(tags=["admin-api"])
templates = Jinja2Templates(directory="templates")


def _admin_page_user(request: Request, db: Session) -> User | RedirectResponse:
    """Same rules as require_admin_user; HTML routes redirect instead of JSON 403."""
    user = optional_user_from_request(request, db)
    if not user:
        return RedirectResponse(url="/settings#account", status_code=302)
    if not is_platform_admin(user):
        return RedirectResponse(url="/?error=admin_forbidden", status_code=302)
    return user


@router.get("/admin", response_class=HTMLResponse, response_model=None)
def admin_page(request: Request, db: Session = Depends(get_db)):
    """Admin UI — protected server-side (not only hidden nav link)."""
    gate = _admin_page_user(request, db)
    if isinstance(gate, RedirectResponse):
        return gate
    log_audit_event(
        action="admin.page.view",
        user_id=gate.id,
        resource_type="admin",
        resource_id="page",
        detail={"path": "/admin"},
        request=request,
    )
    return templates.TemplateResponse(request=request, name="admin.html", context={})


def _parse_use_admin_api_filter(raw: str | None) -> bool | None:
    if raw is None or str(raw).strip() == "":
        return None
    v = str(raw).strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


@api_router.get("/users", response_model=AdminUserListResponse)
def admin_list_users(
    q: str = Query(default=""),
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    segment: str = Query(default="all"),
    trial_status: str | None = Query(default=None),
    use_admin_api: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminUserListResponse:
    items, total = list_users(
        db,
        q=q,
        role=role,
        status=status,
        segment=segment,
        trial_status=trial_status,
        use_admin_api=_parse_use_admin_api_filter(use_admin_api),
        limit=limit,
        offset=offset,
    )
    return AdminUserListResponse(items=items, total=total)


@api_router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def admin_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminUserDetailResponse:
    data = get_user_detail(db, user_id)
    return AdminUserDetailResponse(**data)


@api_router.patch("/users/{user_id}/role")
def admin_update_role(
    user_id: int,
    payload: AdminUserRoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> JSONResponse:
    before = db.query(User).filter(User.id == user_id).first()
    updated = update_user_role(db, target_user_id=user_id, new_role=payload.role, actor=admin)
    log_audit_event(
        action="admin.user.role_update",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={
            "target_email": updated.email,
            "old_role": getattr(before, "role", None) if before else None,
            "new_role": updated.role,
        },
        request=request,
    )
    return JSONResponse({"ok": True, "user": updated.model_dump(mode="json")})


@api_router.patch("/users/{user_id}/api-access")
def admin_update_api_access(
    user_id: int,
    payload: AdminUserApiAccessUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> JSONResponse:
    before = db.query(User).filter(User.id == user_id).first()
    updated = update_user_api_access(
        db,
        target_user_id=user_id,
        api_access_enabled=payload.api_access_enabled,
        use_admin_api_pool=payload.use_admin_api_pool,
        actor=admin,
    )
    log_audit_event(
        action="admin.user.api_access_update",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={
            "target_email": updated.email,
            "old_api_access": bool(getattr(before, "api_access_enabled", False)) if before else None,
            "new_api_access": updated.api_access_enabled,
            "old_admin_pool": bool(getattr(before, "use_admin_api_pool", False)) if before else None,
            "new_admin_pool": updated.use_admin_api_pool,
        },
        request=request,
    )
    return JSONResponse({"ok": True, "user": updated.model_dump(mode="json")})


@api_router.patch("/users/{user_id}/status")
def admin_update_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> JSONResponse:
    before = db.query(User).filter(User.id == user_id).first()
    updated = update_user_status(db, target_user_id=user_id, new_status=payload.status, actor=admin)
    log_audit_event(
        action="admin.user.status_update",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={
            "target_email": updated.email,
            "old_status": getattr(before, "status", None) if before else None,
            "new_status": updated.status,
        },
        request=request,
    )
    return JSONResponse({"ok": True, "user": updated.model_dump(mode="json")})


@api_router.get("/audit-logs", response_model=AdminAuditListResponse)
def admin_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminAuditListResponse:
    rows = list_admin_audit_logs(db, limit=limit)
    return AdminAuditListResponse(items=[AdminAuditLogRow(**r) for r in rows])


@api_router.get("/check")
def admin_check(_admin: User = Depends(require_admin_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "role": _admin.role, "email": _admin.email})
