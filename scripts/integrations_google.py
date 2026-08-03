"""OAuth + API Google Search Console & Google Analytics (GA4)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.core.security import (
    create_google_oauth_state,
    decode_google_oauth_state,
    is_google_login_state,
)
from app.core.settings import GOOGLE_OAUTH_SCOPES, get_google_oauth_settings, google_oauth_client_config
from app.db import get_db
from app.models.user import User
from app.schemas.integrations import (
    Ga4RunReportRequest,
    GscSearchAnalyticsRequest,
    GoogleStartResponse,
    GoogleStatusResponse,
)
from app.services.auth import get_current_user
from app.services.google_apis import (
    ga4_list_account_summaries,
    ga4_run_report,
    gsc_list_sites,
    gsc_search_analytics_query,
    user_google_credentials,
)
from app.services.google_token_store import disconnect_google, has_google_connection, save_google_refresh_token

router = APIRouter(prefix="/integrations", tags=["integrations"])
_LOG = logging.getLogger(__name__)

_GOOGLE_LOGIN_ERRORS = {
    "access_denied": (
        "Bạn đã hủy hoặc Google chưa cho phép app đăng nhập với tài khoản này. "
        "Nếu app OAuth đang ở chế độ Testing, thêm email vào Test users trong Google Cloud Console."
    ),
    "no_token": "Google không trả access token. Thử đăng nhập lại.",
    "token": "Không đổi được mã đăng nhập từ Google (mạng chậm hoặc mã đã hết hạn). Vui lòng bấm Đăng nhập Google lại.",
    "user": "Không tạo được tài khoản từ email Google.",
}


def _login_error_redirect(code: str) -> RedirectResponse:
    msg = _GOOGLE_LOGIN_ERRORS.get(code, "Đăng nhập Google thất bại.")
    from urllib.parse import quote

    return RedirectResponse(
        url=f"/?google_login_error={code}&detail={quote(msg)}",
        status_code=302,
    )


def _google_oauth_redirect_uri(request: Request) -> str:
    """Ưu tiên GOOGLE_OAUTH_REDIRECT_URI trong env.local (production https)."""
    s = get_google_oauth_settings()
    if s and s.get("redirect_uri"):
        return s["redirect_uri"]
    base = str(request.base_url).rstrip("/")
    return f"{base}/integrations/google/callback"


def _allow_oauth_insecure_transport_local(request: Request) -> None:
    """OAuthlib mặc định chặn http://; chỉ bật cho dev local (127.0.0.1 / localhost)."""
    if request.url.scheme != "http":
        return
    host = (request.url.hostname or "").lower()
    if host in ("127.0.0.1", "localhost"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _require_google_config():
    s = get_google_oauth_settings()
    if not s:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chưa cấu hình Google OAuth. Thêm GOOGLE_CLIENT_ID và GOOGLE_CLIENT_SECRET vào env.local "
                "(Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID loại Web)."
            ),
        )
    return s


@router.get("/google/status", response_model=GoogleStatusResponse)
def google_status(current_user: User = Depends(get_current_user)) -> GoogleStatusResponse:
    configured = get_google_oauth_settings() is not None
    return GoogleStatusResponse(
        connected=has_google_connection(current_user.id),
        configured=configured,
    )


@router.post("/google/start", response_model=GoogleStartResponse)
def google_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> GoogleStartResponse:
    s = _require_google_config()
    redirect_uri = _google_oauth_redirect_uri(request)
    client_cfg = google_oauth_client_config(redirect_uri)
    # Web client có client_secret → không dùng PKCE. Nếu bật PKCE, callback tạo Flow mới sẽ mất code_verifier
    # → Google trả (invalid_grant) Missing code verifier.
    flow = Flow.from_client_config(
        client_cfg,
        scopes=list(GOOGLE_OAUTH_SCOPES),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    state = create_google_oauth_state(current_user.id)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return GoogleStartResponse(auth_url=auth_url, configured=True)


@router.get("/google/callback")
def google_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str | None = None,
    db: Session = Depends(get_db),
):
    login_flow = bool(state) and is_google_login_state(state)
    if error:
        if login_flow or error == "access_denied":
            return _login_error_redirect("access_denied" if error == "access_denied" else error)
        return RedirectResponse(url=f"/tool?google_error={error}", status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Thiếu code hoặc state từ Google.")

    _require_google_config()
    redirect_uri = _google_oauth_redirect_uri(request)
    _allow_oauth_insecure_transport_local(request)

    if login_flow:
        from app.services.google_login import (
            email_from_login_tokens,
            exchange_login_code,
            issue_login_token,
            login_or_register_google_user,
        )
        from app.services.oauth_cookie import attach_seo_token_cookie

        try:
            token_data = exchange_login_code(request, redirect_uri)
        except Exception:
            _LOG.exception("Google login token exchange failed")
            return _login_error_redirect("token")
        if not token_data.get("access_token"):
            return _login_error_redirect("no_token")
        try:
            email = email_from_login_tokens(token_data)
            user = login_or_register_google_user(email, db)
            token = issue_login_token(user)
        except Exception:
            _LOG.exception("Google login user setup failed")
            return _login_error_redirect("user")
        response = RedirectResponse(url="/tool?google_login=1", status_code=302)
        attach_seo_token_cookie(response, request, token)
        return response

    try:
        user_id = decode_google_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="State OAuth không hợp lệ hoặc đã hết hạn.") from exc
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")

    client_cfg = google_oauth_client_config(redirect_uri)
    flow = Flow.from_client_config(
        client_cfg,
        scopes=list(GOOGLE_OAUTH_SCOPES),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    try:
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        from app.services.google_login import _public_callback_url

        flow.fetch_token(authorization_response=_public_callback_url(request))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Không đổi được mã code lấy token: {exc}",
        ) from exc

    creds = flow.credentials
    if not creds.refresh_token:
        return RedirectResponse(
            url="/tool?google_error=no_refresh_token",
            status_code=302,
        )
    save_google_refresh_token(user.id, creds.refresh_token)
    return RedirectResponse(url="/tool?google=connected", status_code=302)


@router.delete("/google/disconnect")
def google_disconnect(current_user: User = Depends(get_current_user)) -> dict:
    ok = disconnect_google(current_user.id)
    return {"ok": ok}


@router.get("/gsc/sites")
def integrations_gsc_sites(current_user: User = Depends(get_current_user)) -> dict:
    _require_google_config()
    creds = user_google_credentials(current_user.id)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa kết nối Google. Gọi POST /integrations/google/start rồi hoàn tất đăng nhập Google.",
        )
    try:
        return gsc_list_sites(creds)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search Console API: {exc}") from exc


@router.post("/gsc/search-analytics")
def integrations_gsc_search_analytics(
    payload: GscSearchAnalyticsRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_google_config()
    creds = user_google_credentials(current_user.id)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa kết nối Google.",
        )
    try:
        return gsc_search_analytics_query(
            creds,
            site_url=payload.site_url,
            start_date=payload.start_date,
            end_date=payload.end_date,
            dimensions=payload.dimensions,
            row_limit=payload.row_limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search Analytics API: {exc}") from exc


@router.get("/ga4/summaries")
def integrations_ga4_summaries(current_user: User = Depends(get_current_user)) -> dict:
    """Danh sách tài khoản + property GA4 (để chọn property_id khi chạy báo cáo)."""
    _require_google_config()
    creds = user_google_credentials(current_user.id)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa kết nối Google.",
        )
    try:
        return ga4_list_account_summaries(creds)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analytics Admin API: {exc}") from exc


@router.post("/ga4/run-report")
def integrations_ga4_run_report(
    payload: Ga4RunReportRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_google_config()
    creds = user_google_credentials(current_user.id)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa kết nối Google.",
        )
    try:
        return ga4_run_report(
            creds,
            property_resource=payload.property_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            metrics=payload.metrics,
            dimensions=payload.dimensions,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analytics Data API: {exc}") from exc
