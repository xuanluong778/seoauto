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
    AdminCreditCostListResponse,
    AdminCreditCostPatch,
    AdminCreditCostRow,
    AdminGrantCreditsRequest,
    AdminGrantCreditsResponse,
    AdminGrantChatbotCreditsRequest,
    AdminGrantChatbotCreditsResponse,
    AdminUserApiAccessUpdate,
    AdminUserCreate,
    AdminUserCreateResponse,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserRoleUpdate,
    AdminUserStatusUpdate,
)
from app.services.admin_service import (
    create_user_by_admin,
    delete_user_by_admin,
    get_user_detail,
    grant_credits_to_user_by_admin,
    grant_chatbot_credits_to_user_by_admin,
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
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "admin_nav_active": "users",
            "admin_page_lead": (
                "Quản lý user, trial, quyền API và gói SaaS (gán thủ công — chưa bật enforcement)."
            ),
            "admin_extra_actions": (
                '<button type="button" class="btn" id="btnRefresh">Làm mới</button>'
            ),
        },
    )


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


@api_router.post("/users", response_model=AdminUserCreateResponse)
def admin_create_user(
    payload: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminUserCreateResponse:
    created = create_user_by_admin(
        db,
        email=str(payload.email),
        password=payload.password,
        role=payload.role,
        status=payload.status,
        api_access_enabled=payload.api_access_enabled,
        use_admin_api_pool=payload.use_admin_api_pool,
        initial_credits=payload.initial_credits,
        actor=admin,
    )
    log_audit_event(
        action="admin.user.create",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(created.id),
        detail={
            "target_email": created.email,
            "role": created.role,
            "status": created.status,
            "api_access_enabled": created.api_access_enabled,
            "use_admin_api_pool": created.use_admin_api_pool,
            "initial_credits": payload.initial_credits,
        },
        request=request,
    )
    return AdminUserCreateResponse(user=created)


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
        allow_custom_api_key=payload.allow_custom_api_key,
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
            "old_allow_custom_api_key": bool(getattr(before, "allow_custom_api_key", False)) if before else None,
            "new_allow_custom_api_key": updated.allow_custom_api_key,
            "llm_source": updated.llm_source,
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


@api_router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> JSONResponse:
    deleted = delete_user_by_admin(
        db,
        target_user_id=user_id,
        actor=admin,
    )
    log_audit_event(
        action="admin.user.delete",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={"target_email": deleted["email"], "permanent": True},
        request=request,
    )
    return JSONResponse(
        {
            "ok": True,
            "deleted_user_id": deleted["id"],
            "deleted_email": deleted["email"],
            "message": "Đã xóa user vĩnh viễn.",
        }
    )


@api_router.post("/users/{user_id}/grant-credits", response_model=AdminGrantCreditsResponse)
def admin_grant_user_credits(
    user_id: int,
    payload: AdminGrantCreditsRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminGrantCreditsResponse:
    updated, new_balance, trial_auto = grant_credits_to_user_by_admin(
        db,
        target_user_id=user_id,
        credit_type=payload.credit_type,
        amount=payload.amount,
        reason=payload.reason,
        note=payload.note,
        actor=admin,
    )
    log_audit_event(
        action="admin_grant_credit",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={
            "target_email": updated.email,
            "credit_type": payload.credit_type,
            "amount": payload.amount,
            "grant_reason": payload.reason,
            "internal_note": (payload.note or "")[:500] or None,
            "new_balance": new_balance,
            "trial_auto_activated": trial_auto,
        },
        request=request,
    )
    return AdminGrantCreditsResponse(user=updated, new_balance=new_balance)


@api_router.post("/users/{user_id}/grant-chatbot-credits", response_model=AdminGrantChatbotCreditsResponse)
def admin_grant_user_chatbot_credits(
    user_id: int,
    payload: AdminGrantChatbotCreditsRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminGrantChatbotCreditsResponse:
    updated, new_balance = grant_chatbot_credits_to_user_by_admin(
        db,
        target_user_id=user_id,
        amount=payload.amount,
        operation=payload.operation,
        reason=payload.reason,
        note=payload.note,
        actor=admin,
    )
    log_audit_event(
        action="admin.granted_chatbot_credit",
        user_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        detail={
            "target_email": updated.email,
            "operation": payload.operation,
            "amount": payload.amount,
            "grant_reason": payload.reason,
            "internal_note": (payload.note or "")[:500] or None,
            "new_balance": new_balance,
        },
        request=request,
    )
    verb = "cộng" if payload.operation == "add" else "trừ"
    return AdminGrantChatbotCreditsResponse(
        user=updated,
        new_balance=new_balance,
        message=f"Đã {verb} {payload.amount} credit chatbot CSKH.",
    )


@api_router.get("/credit-costs", response_model=AdminCreditCostListResponse)
def admin_list_credit_costs(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminCreditCostListResponse:
    from app.services.credit_cost_registry import list_credit_cost_catalog

    rows = list_credit_cost_catalog(db=db)
    return AdminCreditCostListResponse(
        items=[AdminCreditCostRow.model_validate({**r, "is_default": bool(r.get("is_default", True))}) for r in rows]
    )


@api_router.patch("/credit-costs/{module}/{action}", response_model=AdminCreditCostRow)
def admin_patch_credit_cost(
    module: str,
    action: str,
    payload: AdminCreditCostPatch,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AdminCreditCostRow:
    from app.services.credit_cost_registry import update_credit_cost_config

    row = update_credit_cost_config(
        db,
        module=module,
        action=action,
        credit_cost=payload.credit_cost,
        cache_discount_percent=payload.cache_discount_percent,
        cache_zero_cost=payload.cache_zero_cost,
        label=payload.label,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.commit()
    return AdminCreditCostRow.model_validate({**row, "is_default": False})


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
