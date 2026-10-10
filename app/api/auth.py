import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.security import create_google_login_state
from app.core.settings import get_google_oauth_settings
from app.db import get_db
from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.user import User
from app.schemas.auth import (
    CreditCostCatalogItem,
    CreditCostCatalogResponse,
    CreditGrantRequest,
    CreditGrantResult,
    CreditLedgerListResponse,
    CreditLedgerRow,
    CreditTransactionListResponse,
    CreditTransactionRow,
    CreditPackagesResponse,
    CreditPackagePublic,
    CreditsConfigResponse,
    MessageResponse,
    OtpSendRequest,
    OtpVerifyRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.admin_auth import ensure_admin_user_fields, is_configured_admin_email, is_platform_admin_email, skips_otp_for_user
from app.services.auth import (
    get_bearer_or_cookie_token,
    get_current_user,
    get_optional_current_user,
    get_token_optional,
    login_user,
    register_user,
    user_from_token,
)
from app.services.auth_tokens import public_token_json
from app.services.session_auth_rollout import refresh_token_http_only_only, server_sessions_enabled
from app.services.affiliate_service import try_attach_referral_from_request
from app.services.rbac import normalize_role
from app.services.security_audit_log import log_audit_event
from app.services.credits import (
    admin_grant_secret,
    credits_enforced,
    get_available_balance,
    grant_credits,
    public_credit_packages,
    public_credit_transaction_note,
)
from app.services.otp_flow import send_login_otp, verify_login_otp
from app.services.oauth_cookie import (
    SEO_REFRESH_COOKIE,
    attach_session_cookies,
    attach_seo_token_cookie,
    clear_seo_token_cookie,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    if server_sessions_enabled():
        from app.services.user_session_service import revoke_session_by_access_token

        access = (request.cookies.get("seo_token") or "").strip()
        if not access:
            access = (request.headers.get("authorization") or "").replace("Bearer ", "", 1).strip()
        if access:
            revoke_session_by_access_token(db, access, reason="logout")
            db.commit()
    response = JSONResponse(content={"message": "Đã đăng xuất."})
    clear_seo_token_cookie(response, request)
    return response


@router.post("/refresh", response_model=TokenResponse)
def auth_refresh(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not server_sessions_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    refresh = (request.cookies.get(SEO_REFRESH_COOKIE) or "").strip()
    if not refresh:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    from app.services.user_session_service import refresh_user_session, tokens_to_response

    tokens = refresh_user_session(db, refresh_token=refresh, request=request)
    body = tokens_to_response(tokens)
    response = JSONResponse(content=public_token_json(body))
    attach_session_cookies(
        response,
        request,
        access_token=body.access_token,
        refresh_token=body.refresh_token or None,
    )
    return response


@router.post("/sessions/revoke-all", response_model=MessageResponse)
def revoke_all_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not server_sessions_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    from app.core.security import decode_access_token
    from app.services.user_session_service import revoke_all_user_sessions

    except_sid = None
    token = (request.cookies.get("seo_token") or "").strip()
    if not token:
        auth = (request.headers.get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if token:
        try:
            except_sid = str(decode_access_token(token).get("sid") or "").strip() or None
        except ValueError:
            except_sid = None
    count = revoke_all_user_sessions(
        db,
        user_id=int(current_user.id),
        except_session_id=except_sid,
        reason="revoke_all",
    )
    db.commit()
    return MessageResponse(message=f"Đã thu hồi {count} phiên đăng nhập khác.")


@router.get("/session", response_model=TokenResponse)
def auth_session(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Depends(get_token_optional),
) -> JSONResponse | TokenResponse:
    """Trả access_token từ cookie HttpOnly (hoặc Bearer) để SPA hydrate sessionStorage.

    Luồng Google OAuth chỉ Set-Cookie HttpOnly — JS không đọc được document.cookie.
    Password login vẫn trả token trong JSON; endpoint này đồng bộ OAuth với cùng mô hình.
    Khi SERVER_SESSIONS_ENABLED: access hết hạn thì tự refresh từ cookie seo_refresh (không cần đổi UI).
    """
    if token:
        try:
            user_from_token(db, token)
            return TokenResponse(access_token=token, token_type="bearer")
        except HTTPException:
            if not server_sessions_enabled():
                raise

    refresh = (request.cookies.get(SEO_REFRESH_COOKIE) or "").strip()
    if server_sessions_enabled() and refresh:
        from app.services.user_session_service import refresh_user_session, tokens_to_response

        tokens = refresh_user_session(db, refresh_token=refresh, request=request)
        body = tokens_to_response(tokens)
        response = JSONResponse(content=public_token_json(body))
        attach_session_cookies(
            response,
            request,
            access_token=body.access_token,
            refresh_token=body.refresh_token or None,
        )
        return response

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Đăng nhập để tiếp tục.")
    user_from_token(db, token)
    return TokenResponse(access_token=token, token_type="bearer")


@router.get("/google/configured")
def google_login_configured() -> dict:
    return {"configured": get_google_oauth_settings() is not None}


@router.get("/google/login")
def google_login_start(request: Request) -> RedirectResponse:
    from app.services.google_login import build_google_login_flow, oauth_redirect_uri

    if not get_google_oauth_settings():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình OAuth Google trong backend.",
        )
    redirect_uri = oauth_redirect_uri()
    flow = build_google_login_flow(redirect_uri)
    state = create_google_login_state()
    auth_url, _ = flow.authorization_url(
        access_type="online",
        prompt="select_account",
        state=state,
    )
    if request.url.scheme == "http" and (request.url.hostname or "").lower() in ("127.0.0.1", "localhost"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    return RedirectResponse(url=auth_url, status_code=302)


@router.post("/register", response_model=MessageResponse)
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)) -> MessageResponse:
    user = register_user(payload, db)
    try_attach_referral_from_request(request, user, db)
    return MessageResponse(message="Đăng ký thành công. Bạn có thể đăng nhập bằng email và mật khẩu.")


@router.get("/login/flags")
def login_flags(email: str = Query(..., min_length=3), db: Session = Depends(get_db)) -> dict:
    """UI: ẩn OTP khi email là admin (role admin hoặc ADMIN_EMAIL trong env.local)."""
    email_norm = email.strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()
    skip = skips_otp_for_user(user, email_norm)
    return {
        "skip_otp": skip,
        "is_admin": bool(user and str(getattr(user, "role", "") or "").lower() == "admin"),
    }


@router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)) -> JSONResponse:
    token = login_user(payload.email, payload.password, db, payload.otp, request=request)
    user = user_from_token(db, token.access_token)
    log_audit_event(action="login", user_id=user.id, resource_type="user", resource_id=str(user.id), request=request)
    response = JSONResponse(content=public_token_json(token))
    attach_session_cookies(
        response,
        request,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
    )
    return response


@router.post("/otp/send", response_model=MessageResponse)
def otp_send(payload: OtpSendRequest, db: Session = Depends(get_db)) -> MessageResponse:
    send_login_otp(payload.email, db)
    return MessageResponse(message="Đã gửi OTP tới email của bạn (kiểm tra cả thư mục spam).")


@router.post("/otp/verify", response_model=TokenResponse)
def otp_verify(request: Request, payload: OtpVerifyRequest, db: Session = Depends(get_db)) -> JSONResponse:
    token = verify_login_otp(payload.email, payload.otp, db)
    user = user_from_token(db, token.access_token)
    log_audit_event(action="login", user_id=user.id, resource_type="user", resource_id=str(user.id), request=request)
    response = JSONResponse(content=public_token_json(token))
    attach_session_cookies(
        response,
        request,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
    )
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    from app.services.business_api_cache import cache_get, cache_set, tenant_cache_key
    from app.services.business_api_rollout import business_api_cache_enabled
    from app.services.rbac import is_admin, is_admin_role_name
    from app.services.tenant_org import resolve_organization_id

    org_id = resolve_organization_id(int(current_user.id))
    if business_api_cache_enabled():
        key = tenant_cache_key(
            user_id=int(current_user.id),
            organization_id=org_id,
            scope="auth_me",
        )
        cached = cache_get(key)
        if isinstance(cached, dict) and cached.get("id") == current_user.id:
            return UserResponse.model_validate(cached)

    # Bootstrap legacy configured admins that still have a non-admin role.
    # Never downgrade an existing admin / super_admin.
    if is_configured_admin_email(current_user.email) and not is_admin_role_name(current_user.role):
        ensure_admin_user_fields(current_user)
        db.commit()
        db.refresh(current_user)
    credit_balance = get_available_balance(db, current_user.id, sync=False)
    out = UserResponse.model_validate(current_user).model_copy(
        update={
            "show_admin_nav": is_admin(current_user),
            "credit_balance": int(credit_balance),
        }
    )
    if business_api_cache_enabled():
        cache_set(key, out.model_dump(), ttl=int(os.getenv("BUSINESS_API_AUTH_ME_TTL", "30")))
    return out


@router.get("/credits/config", response_model=CreditsConfigResponse)
def credits_config() -> CreditsConfigResponse:
    return CreditsConfigResponse(enabled=credits_enforced())


_PACKAGES_FOOTNOTE = (
    "Kích hoạt trừ credit: bật CREDITS_ENABLED=1. Admin cộng credit: POST /auth/credits/admin/grant "
    "(header X-Credits-Admin-Key). Thanh toán online có thể tích hợp sau."
)


@router.get("/credits/packages", response_model=CreditPackagesResponse)
def credits_packages(user: User | None = Depends(get_optional_current_user)) -> CreditPackagesResponse:
    rows = public_credit_packages()
    packages = [CreditPackagePublic.model_validate(x) for x in rows]
    bal = int(user.credit_balance) if user else None
    return CreditPackagesResponse(
        credits_system_enabled=credits_enforced(),
        your_balance=bal,
        packages=packages,
        footnote=_PACKAGES_FOOTNOTE,
    )


@router.get("/credits/ledger", response_model=CreditLedgerListResponse)
def credits_ledger(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
) -> CreditLedgerListResponse:
    lim = max(1, min(500, limit))
    balance = get_available_balance(db, current_user.id)
    rows = (
        db.query(CreditLedgerEntry)
        .filter(CreditLedgerEntry.user_id == current_user.id)
        .order_by(desc(CreditLedgerEntry.id))
        .limit(lim)
        .all()
    )
    return CreditLedgerListResponse(
        items=[CreditLedgerRow.model_validate(r) for r in rows],
        balance=balance,
    )


@router.get("/credits/transactions", response_model=CreditTransactionListResponse)
def credits_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
) -> CreditTransactionListResponse:
    lim = max(1, min(500, limit))
    balance = get_available_balance(db, current_user.id)
    rows = (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == current_user.id)
        .order_by(desc(CreditLedger.id))
        .limit(lim)
        .all()
    )
    return CreditTransactionListResponse(
        balance=balance,
        items=[
            CreditTransactionRow(
                id=r.id,
                delta=r.delta,
                balance_after=r.balance_after,
                reason=r.reason,
                note=public_credit_transaction_note(r),
                module=getattr(r, "module", None),
                action=getattr(r, "action", None),
                credit_used=getattr(r, "credit_used", None),
                request_id=getattr(r, "request_id", None),
                source=getattr(r, "source", None),
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/credits/cost-catalog", response_model=CreditCostCatalogResponse)
def credits_cost_catalog(
    db: Session = Depends(get_db),
) -> CreditCostCatalogResponse:
    from app.services.credit_cost_registry import list_credit_cost_catalog

    items = list_credit_cost_catalog(db=db)
    return CreditCostCatalogResponse(
        credits_enabled=credits_enforced(),
        items=[CreditCostCatalogItem.model_validate(x) for x in items],
    )


@router.post("/credits/admin/grant", response_model=CreditGrantResult)
def credits_admin_grant(
    payload: CreditGrantRequest,
    db: Session = Depends(get_db),
    x_credits_admin_key: str | None = Header(default=None, alias="X-Credits-Admin-Key"),
) -> CreditGrantResult:
    secret = admin_grant_secret()
    if not secret or (x_credits_admin_key or "").strip() != secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    email = str(payload.email).strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy user.")
    grant_credits(
        db,
        user_id=user.id,
        amount=int(payload.amount),
        reason="admin_grant",
        source_type="admin_adjustment",
        note=None,
        expired_at=None,
    )
    db.commit()
    db.refresh(user)
    return CreditGrantResult(email=user.email, new_balance=int(user.credit_balance or 0))
