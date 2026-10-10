from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.password_policy import validate_password_strength
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserCreate
from app.services.credits import apply_signup_bonus_if_configured, credits_enforced
from app.services.admin_auth import ensure_admin_user_fields, is_configured_admin_email, skips_otp_for_user
from app.services.otp_flow import validate_otp_for_register
from app.services.admin_auth import _is_admin_role as _user_is_admin
from app.services.session_auth_rollout import server_sessions_enabled

_USER_STATUSES = frozenset({"active", "inactive", "banned"})


def _normalize_status(status: str | None) -> str:
    s = str(status or "active").strip().lower()
    return s if s in _USER_STATUSES else "active"


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
_bearer_optional = HTTPBearer(auto_error=False)


def get_token_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
) -> str | None:
    if credentials and credentials.credentials:
        t = credentials.credentials.strip()
        if t:
            return t
    cookie = (request.cookies.get("seo_token") or "").strip()
    return cookie or None


def user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("user_id", 0))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from app.core.security import is_service_token_payload, is_session_token_payload
    from app.services.session_auth_rollout import (
        legacy_cutoff_active,
        legacy_user_jwt_blocked,
        server_sessions_enabled,
        service_tokens_enabled,
    )

    sid = str(payload.get("sid") or "").strip()
    jti = str(payload.get("jti") or "").strip()
    is_service = is_service_token_payload(payload)
    is_session = is_session_token_payload(payload)

    if server_sessions_enabled() and legacy_user_jwt_blocked() and legacy_cutoff_active():
        if is_service:
            if not service_tokens_enabled():
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        elif not is_session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        else:
            from app.services.user_session_service import validate_session_claims

            validate_session_claims(db, user_id=user_id, session_id=sid, jti=jti)
    elif server_sessions_enabled() and is_session:
        from app.services.user_session_service import validate_session_claims

        validate_session_claims(db, user_id=user_id, session_id=sid, jti=jti)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    _raise_if_user_blocked(user)
    return user


def issue_login_tokens(db: Session, user: User, request: Request | None = None) -> TokenResponse:
    if server_sessions_enabled():
        from app.services.user_session_service import create_user_session, tokens_to_response

        tokens = create_user_session(db, user=user, request=request)
        db.commit()
        return tokens_to_response(tokens)
    token = create_access_token(user_id=user.id)
    return TokenResponse(access_token=token, token_type="bearer")


def _raise_if_user_blocked(user: User) -> None:
    st = _normalize_status(getattr(user, "status", None))
    if st == "banned":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa. Liên hệ quản trị viên.",
        )
    if st == "inactive":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa được kích hoạt hoặc đã tạm ngưng.",
        )


def register_user(payload: UserCreate, db: Session) -> User:
    email = payload.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    skip_otp = skips_otp_for_user(existing, email) or is_configured_admin_email(email)
    row = None
    if not skip_otp:
        row = validate_otp_for_register(email, payload.otp, db)
    if existing and existing.has_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email đã được đăng ký. Hãy đăng nhập.",
        )

    user: User
    if row is not None:
        row.used = True
    if existing:
        existing.password_hash = hash_password(payload.password)
        existing.has_password = True
        if server_sessions_enabled():
            from app.services.user_session_service import revoke_all_user_sessions

            revoke_all_user_sessions(db, user_id=int(existing.id), reason="password_change")
        if skip_otp:
            ensure_admin_user_fields(existing)
        user = existing
    else:
        user = User(
            email=email,
            password_hash=hash_password(payload.password),
            has_password=True,
            api_access_enabled=False,
            use_admin_api_pool=False,
        )
        if skip_otp:
            ensure_admin_user_fields(user)
        db.add(user)
        db.flush()
    if user.has_password:
        apply_signup_bonus_if_configured(db, user)
    db.commit()
    db.refresh(user)
    return user


def login_user(
    email: str,
    password: str,
    db: Session,
    otp: str | None = None,
    request: Request | None = None,
) -> TokenResponse:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai email hoặc mật khẩu.",
        )
    if not user.has_password:
        skip_otp = skips_otp_for_user(user, email)
        if not skip_otp and not otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Tài khoản chưa kích hoạt. Nhập mã OTP từ Gmail và mật khẩu (đủ tiêu chí), "
                    "rồi bấm Đăng nhập để kích hoạt."
                ),
            )
        try:
            validate_password_strength(password)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        if skip_otp:
            user.password_hash = hash_password(password)
            user.has_password = True
            if server_sessions_enabled():
                from app.services.user_session_service import revoke_all_user_sessions

                revoke_all_user_sessions(db, user_id=int(user.id), reason="password_change")
            if is_configured_admin_email(email) or _user_is_admin(user):
                ensure_admin_user_fields(user)
            db.commit()
            db.refresh(user)
        else:
            register_user(
                UserCreate(email=email, password=password, otp=otp or ""),
                db,
            )
            user = db.query(User).filter(User.email == email).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Không thể hoàn tất kích hoạt tài khoản.",
                )
            if request is not None:
                from app.services.affiliate_service import try_attach_referral_from_request

                try_attach_referral_from_request(request, user, db)
        token = issue_login_tokens(db, user, request=request)
        return token

    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai email hoặc mật khẩu.",
        )

    if _normalize_status(getattr(user, "status", None)) != "active":
        _raise_if_user_blocked(user)

    if is_configured_admin_email(email) or _user_is_admin(user):
        ensure_admin_user_fields(user)
        db.commit()
        db.refresh(user)

    return issue_login_tokens(db, user, request=request)


def get_bearer_or_cookie_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
) -> str:
    if credentials and credentials.credentials:
        t = credentials.credentials.strip()
        if t:
            return t
    cookie = (request.cookies.get("seo_token") or "").strip()
    if cookie:
        return cookie
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Đăng nhập để tiếp tục.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    token: str = Depends(get_bearer_or_cookie_token),
    db: Session = Depends(get_db),
) -> User:
    from app.services.business_api_rollout import request_auth_dedup_enabled

    if request_auth_dedup_enabled():
        cached = getattr(request.state, "current_user", None)
        if isinstance(cached, User):
            return cached
    user = user_from_token(db, token)
    if request_auth_dedup_enabled():
        try:
            db.expunge(user)
        except Exception:
            pass
        request.state.current_user = user
    return user


def get_billing_user(
    token: str | None = Depends(get_token_optional),
    db: Session = Depends(get_db),
) -> User | None:
    if not credits_enforced():
        return None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Đăng nhập để dùng công cụ (hệ thống credit đang bật). Mở trang chủ → đăng nhập.",
        )
    return user_from_token(db, token)


def get_optional_current_user(
    token: str | None = Depends(get_token_optional),
    db: Session = Depends(get_db),
) -> User | None:
    if not token:
        return None
    try:
        return user_from_token(db, token)
    except HTTPException:
        return None
