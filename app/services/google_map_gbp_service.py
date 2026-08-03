"""Google Map SEO — Google Business Profile OAuth & đồng bộ địa điểm."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from google_auth_oauthlib.flow import Flow
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.gbp_settings import GBP_OAUTH_SCOPES, get_gbp_oauth_settings, gbp_api_setup_links, gbp_oauth_client_config
from app.core.secrets_crypto import decrypt_secret, encrypt_secret
from app.core.security import create_gbp_oauth_state, decode_gbp_oauth_state
from app.models.google_map_gbp import GbpLocation, GbpOAuthConnection
from app.models.user import User
from app.services.google_map_gbp_api import (
    ACCOUNTS_LIST_ENDPOINT,
    GBP_QUOTA_FRIENDLY_MSG,
    GbpApiError,
    classify_gbp_api_error,
    credentials_from_tokens,
    fetch_google_user_email,
    list_accounts,
    list_locations,
    parse_location_row,
    token_expiry_from_creds,
)
from app.services.google_map_gbp_sync_guard import (
    GbpSyncGuard,
    ensure_google_api_allowed,
    friendly_sync_error,
    get_accounts_cached,
    invalidate_accounts_cache,
    is_rate_limited,
    mark_rate_limited,
    rate_limit_until_iso,
    retry_after_seconds,
    set_accounts_cached,
)
from app.services.google_login import _public_callback_url
from app.services.rbac import is_admin

_LOG = logging.getLogger("google_map_gbp.service")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def oauth_configured() -> bool:
    return get_gbp_oauth_settings() is not None


def _redirect_uri() -> str:
    s = get_gbp_oauth_settings()
    if not s:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình Google Business Profile OAuth.",
        )
    return s["redirect_uri"]


def _allow_insecure_local(request: Request) -> None:
    if request.url.scheme != "http":
        return
    host = (request.url.hostname or "").lower()
    if host in ("127.0.0.1", "localhost"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _require_config() -> dict:
    s = get_gbp_oauth_settings()
    if not s:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chưa cấu hình Google Business Profile OAuth. "
                "Thêm GOOGLE_CLIENT_ID và GOOGLE_CLIENT_SECRET (hoặc GBP_GOOGLE_*) vào env.local."
            ),
        )
    return s


def _conn_tokens(conn: GbpOAuthConnection) -> tuple[str, str | None, datetime | None]:
    refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
    access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
    return refresh, access, conn.token_expires_at


def connection_to_public(conn: GbpOAuthConnection, *, locations_count: int = 0) -> dict[str, Any]:
    return {
        "id": conn.id,
        "google_account_resource": conn.google_account_resource,
        "google_account_name": conn.google_account_name,
        "google_email": conn.google_email,
        "status": conn.status,
        "locations_count": locations_count,
        "last_synced_at": _iso(conn.last_synced_at),
        "last_sync_error": _friendly_last_error(conn.last_sync_error),
        "has_token": bool(conn.refresh_token_encrypted),
    }


def _audit_from_row(row: GbpLocation) -> dict[str, Any] | None:
    raw = str(row.audit_snapshot_json or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def location_to_ui(row: GbpLocation) -> dict[str, Any]:
    audit = _audit_from_row(row) or {"synced": True, "source": "google_business_profile"}
    addr_parts = [p for p in (row.address_line, row.locality) if p]
    verified = str(row.verification_status or "") == "verified"
    return {
        "id": f"gbp_{row.id}",
        "db_id": row.id,
        "google_location_resource": row.google_location_resource,
        "name": row.title or "Địa điểm chưa đặt tên",
        "address": ", ".join(addr_parts) if addr_parts else "",
        "category": row.primary_category or "",
        "rating": None,
        "reviews": 0,
        "unrepliedReviews": 0,
        "views": 0,
        "calls": 0,
        "directions": 0,
        "websiteClicks": 0,
        "mapScore": None,
        "profileComplete": None,
        "verified": verified,
        "verificationStatus": row.verification_status or "unknown",
        "latestPost": None,
        "gbp": audit,
        "source": "google_business_profile",
        "last_synced_at": _iso(row.last_synced_at),
    }


def _pending_account_resource(user_id: int) -> str:
    return f"accounts/__pending__{user_id}"


def _is_pending_connection(conn: GbpOAuthConnection) -> bool:
    return "__pending__" in str(conn.google_account_resource or "")


def _is_quota_error_text(msg: str | None) -> bool:
    if not msg:
        return False
    low = msg.lower()
    return "429" in msg or "quota" in low or "resource_exhausted" in low


def _resolve_error_code(last_sync_error: str | None, connection_state: str) -> str | None:
    if connection_state == "rate_limited" or _is_quota_error_text(last_sync_error):
        return "api_quota"
    if not last_sync_error:
        return None
    low = last_sync_error.lower()
    if "401" in low or "unauthorized" in low or "invalid_grant" in low:
        return "oauth_invalid"
    if "403" in low and ("disabled" in low or "not enabled" in low):
        return "api_disabled"
    if "403" in low or "permission" in low:
        return "api_forbidden"
    return "sync_failed"


def _resolve_sync_status(
    user_id: int,
    *,
    connected: bool,
    loc_count: int,
    last_sync_error: str | None,
    syncing: bool = False,
) -> str:
    if syncing:
        return "syncing"
    if not connected:
        return "not_connected"
    if is_rate_limited(user_id) or _is_quota_error_text(last_sync_error):
        return "rate_limited"
    if loc_count == 0 and last_sync_error:
        return "error"
    if loc_count == 0:
        return "pending"
    return "ok"


def _friendly_last_error(last_sync_error: str | None) -> str | None:
    if not last_sync_error:
        return None
    if _is_quota_error_text(last_sync_error):
        return GBP_QUOTA_FRIENDLY_MSG
    return last_sync_error[:240]


def _list_accounts_for_user(
    creds: Any,
    *,
    user_id: int,
    google_account: str | None,
    source_action: str,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    if use_cache:
        cached = get_accounts_cached(user_id)
        if cached is not None:
            _LOG.info(
                "GBP accounts.list cache hit user_id=%s source_action=%s",
                user_id,
                source_action,
            )
            return cached
    ensure_google_api_allowed(user_id, source_action)
    accounts = list_accounts(
        creds,
        user_id=user_id,
        google_account=google_account,
        source_action=source_action,
    )
    set_accounts_cached(user_id, accounts)
    return accounts


def get_status(db: Session, user: User) -> dict[str, Any]:
    configured = oauth_configured()
    admin = is_admin(user)
    connections = db.execute(
        select(GbpOAuthConnection)
        .where(GbpOAuthConnection.user_id == user.id, GbpOAuthConnection.status == "active")
        .order_by(GbpOAuthConnection.updated_at.desc())
    ).scalars().all()
    loc_count = db.execute(
        select(func.count(GbpLocation.id)).where(
            GbpLocation.user_id == user.id,
            GbpLocation.is_active.is_(True),
        )
    ).scalar_one()
    conn_public = []
    last_sync_error: str | None = None
    for c in connections:
        n = db.execute(
            select(func.count(GbpLocation.id)).where(
                GbpLocation.connection_id == c.id,
                GbpLocation.is_active.is_(True),
            )
        ).scalar_one()
        conn_public.append(connection_to_public(c, locations_count=int(n or 0)))
        if c.last_sync_error and not last_sync_error:
            last_sync_error = c.last_sync_error

    loc_count_int = int(loc_count or 0)
    connected = bool(connections)
    oauth_valid = connected and all(bool(c.refresh_token_encrypted) and c.status == "active" for c in connections)
    connection_state = _resolve_sync_status(
        user.id,
        connected=connected,
        loc_count=loc_count_int,
        last_sync_error=last_sync_error,
    )
    if connection_state == "pending":
        legacy_state = "connected_no_locations"
    elif connection_state == "rate_limited":
        legacy_state = "rate_limited"
    elif connection_state == "not_connected":
        legacy_state = "not_connected"
    else:
        legacy_state = "connected"
    friendly_error = _friendly_last_error(last_sync_error)
    rate_until = rate_limit_until_iso(user.id)
    retry_sec = retry_after_seconds(user.id)
    error_code = _resolve_error_code(last_sync_error, connection_state)
    out: dict[str, Any] = {
        "configured": configured,
        "connected": connected,
        "oauth_valid": oauth_valid,
        "connection_state": legacy_state,
        "sync_status": connection_state,
        "error_code": error_code,
        "locations_count": loc_count_int,
        "sync_pending": connection_state in ("rate_limited", "pending", "error"),
        "api_quota_limited": connection_state == "rate_limited",
        "last_sync_error": friendly_error,
        "rate_limit_until": rate_until,
        "retry_after_seconds": retry_sec,
        "friendly_message": friendly_error or (
            GBP_QUOTA_FRIENDLY_MSG if connection_state == "rate_limited" else None
        ),
        "connections": conn_public,
        "is_admin": admin,
    }
    if not configured and admin:
        out["admin_message"] = (
            "Chưa cấu hình API — thêm GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET "
            "(hoặc GBP_GOOGLE_CLIENT_ID / GBP_GOOGLE_CLIENT_SECRET) và bật Business Profile APIs trên Google Cloud."
        )
    if admin:
        out["api_setup_links"] = gbp_api_setup_links()
    return out


def list_user_locations(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GbpLocation)
        .where(GbpLocation.user_id == user_id, GbpLocation.is_active.is_(True))
        .order_by(GbpLocation.title.asc())
    ).scalars().all()
    return [location_to_ui(r) for r in rows]


def oauth_start_url(request: Request, user_id: int) -> dict[str, str]:
    _require_config()
    redirect_uri = _redirect_uri()
    _allow_insecure_local(request)
    client_cfg = gbp_oauth_client_config(redirect_uri)
    flow = Flow.from_client_config(
        client_cfg,
        scopes=list(GBP_OAUTH_SCOPES),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    state = create_gbp_oauth_state(user_id)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return {"auth_url": auth_url}


def _upsert_connection(
    db: Session,
    *,
    user_id: int,
    account_resource: str,
    account_name: str | None,
    google_email: str | None,
    refresh_token: str,
    access_token: str | None,
    token_expires_at: datetime | None,
) -> GbpOAuthConnection:
    row = db.execute(
        select(GbpOAuthConnection).where(
            GbpOAuthConnection.user_id == user_id,
            GbpOAuthConnection.google_account_resource == account_resource,
        )
    ).scalar_one_or_none()
    scopes = ",".join(GBP_OAUTH_SCOPES)
    if row is None:
        row = GbpOAuthConnection(
            user_id=user_id,
            google_account_resource=account_resource,
            google_account_name=account_name,
            google_email=google_email,
            refresh_token_encrypted=encrypt_secret(refresh_token),
            access_token_encrypted=encrypt_secret(access_token or ""),
            token_expires_at=token_expires_at,
            scopes=scopes,
            status="active",
            last_sync_error=None,
        )
        db.add(row)
    else:
        row.google_account_name = account_name or row.google_account_name
        row.google_email = google_email or row.google_email
        row.refresh_token_encrypted = encrypt_secret(refresh_token)
        row.access_token_encrypted = encrypt_secret(access_token or "")
        row.token_expires_at = token_expires_at
        row.scopes = scopes
        row.status = "active"
        row.last_sync_error = None
    db.flush()
    return row


def _upsert_location(db: Session, *, user_id: int, connection_id: int, parsed: dict[str, Any]) -> None:
    resource = str(parsed["google_location_resource"])
    row = db.execute(
        select(GbpLocation).where(
            GbpLocation.connection_id == connection_id,
            GbpLocation.google_location_resource == resource,
        )
    ).scalar_one_or_none()
    audit = parsed.get("audit_snapshot")
    audit_json = json.dumps(audit, ensure_ascii=False) if audit else None
    now = _now()
    if row is None:
        row = GbpLocation(
            user_id=user_id,
            connection_id=connection_id,
            google_location_resource=resource,
            google_account_resource=str(parsed["google_account_resource"]),
            title=parsed.get("title"),
            address_line=parsed.get("address_line"),
            locality=parsed.get("locality"),
            phone=parsed.get("phone"),
            website_uri=parsed.get("website_uri"),
            primary_category=parsed.get("primary_category"),
            verification_status=parsed.get("verification_status"),
            audit_snapshot_json=audit_json,
            is_active=True,
            last_synced_at=now,
        )
        db.add(row)
    else:
        row.title = parsed.get("title")
        row.address_line = parsed.get("address_line")
        row.locality = parsed.get("locality")
        row.phone = parsed.get("phone")
        row.website_uri = parsed.get("website_uri")
        row.primary_category = parsed.get("primary_category")
        row.verification_status = parsed.get("verification_status")
        row.audit_snapshot_json = audit_json
        row.is_active = True
        row.last_synced_at = now


def sync_connection_locations(
    db: Session,
    conn: GbpOAuthConnection,
    *,
    source_action: str = "manual_sync",
    use_cache: bool = False,
    accounts: list[dict[str, Any]] | None = None,
) -> int:
    ensure_google_api_allowed(conn.user_id, source_action)

    refresh, access, expiry = _conn_tokens(conn)
    creds = credentials_from_tokens(
        refresh_token=refresh,
        access_token=access,
        token_expiry=expiry,
    )
    if not creds or not creds.refresh_token:
        raise RuntimeError("Không có refresh token hợp lệ.")

    if creds.token and creds.token != access:
        conn.access_token_encrypted = encrypt_secret(creds.token)
        conn.token_expires_at = token_expiry_from_creds(creds)
        db.flush()

    google_account = conn.google_email or conn.google_account_name or conn.google_account_resource
    if accounts is None:
        try:
            accounts = _list_accounts_for_user(
                creds,
                user_id=conn.user_id,
                google_account=google_account,
                source_action=source_action,
                use_cache=use_cache,
            )
        except GbpApiError as exc:
            if exc.is_quota:
                mark_rate_limited(
                    conn.user_id,
                    retry_after_sec=exc.retry_after_sec,
                    endpoint=exc.endpoint,
                    reason="google_429",
                )
                conn.last_sync_error = GBP_QUOTA_FRIENDLY_MSG
            raise

    if _is_pending_connection(conn) and accounts:
        first = accounts[0]
        acc_name = str(first.get("name") or "")
        if acc_name:
            conn.google_account_resource = acc_name
            conn.google_account_name = str(first.get("accountName") or first.get("name") or "") or None
            db.flush()

    synced = 0
    seen_resources: set[str] = set()
    for acc in accounts:
        acc_name = str(acc.get("name") or "")
        if not acc_name:
            continue
        locs = list_locations(
            creds,
            acc_name,
            user_id=conn.user_id,
            google_account=google_account,
            connection_id=conn.id,
            source_action=source_action,
        )
        for loc in locs:
            parsed = parse_location_row(acc_name, loc)
            resource = str(parsed["google_location_resource"])
            if not resource:
                continue
            seen_resources.add(resource)
            _upsert_location(
                db,
                user_id=conn.user_id,
                connection_id=conn.id,
                parsed=parsed,
            )
            synced += 1

    if seen_resources:
        stale = db.execute(
            select(GbpLocation).where(
                GbpLocation.connection_id == conn.id,
                GbpLocation.is_active.is_(True),
            )
        ).scalars().all()
        for row in stale:
            if row.google_location_resource not in seen_resources:
                row.is_active = False

    conn.last_synced_at = _now()
    conn.last_sync_error = None
    return synced


def sync_user_locations(db: Session, user_id: int, *, connection_id: int | None = None) -> dict[str, Any]:
    retry_sec = retry_after_seconds(user_id)
    if is_rate_limited(user_id):
        loc_count = db.execute(
            select(func.count(GbpLocation.id)).where(
                GbpLocation.user_id == user_id,
                GbpLocation.is_active.is_(True),
            )
        ).scalar_one()
        return {
            "synced_locations": 0,
            "connections": 0,
            "errors": [GBP_QUOTA_FRIENDLY_MSG],
            "already_syncing": False,
            "api_quota_limited": True,
            "connected": True,
            "sync_status": "rate_limited",
            "error_code": "api_quota",
            "rate_limit_until": rate_limit_until_iso(user_id),
            "retry_after_seconds": retry_sec,
            "message": GBP_QUOTA_FRIENDLY_MSG,
            "locations_count": int(loc_count or 0),
        }

    with GbpSyncGuard(user_id, connection_id) as guard:
        if not guard.acquired:
            return {
                "synced_locations": 0,
                "connections": 0,
                "errors": [],
                "already_syncing": True,
                "api_quota_limited": False,
                "connected": True,
                "sync_status": "syncing",
                "error_code": None,
                "rate_limit_until": None,
                "retry_after_seconds": None,
                "message": "Đang đồng bộ Google Business Profile — vui lòng đợi.",
            }

        q = select(GbpOAuthConnection).where(
            GbpOAuthConnection.user_id == user_id,
            GbpOAuthConnection.status == "active",
        )
        if connection_id is not None:
            q = q.where(GbpOAuthConnection.id == connection_id)
        connections = db.execute(q).scalars().all()
        if not connections:
            raise HTTPException(status_code=404, detail="Chưa có kết nối Google Business Profile.")

        total = 0
        errors: list[str] = []
        api_quota_limited = False
        rate_until: str | None = None
        for conn in connections:
            with GbpSyncGuard(user_id, conn.id) as conn_guard:
                if not conn_guard.acquired:
                    errors.append("Đang đồng bộ connection khác — bỏ qua lần gọi trùng.")
                    continue
                try:
                    total += sync_connection_locations(
                        db,
                        conn,
                        source_action="manual_sync",
                        use_cache=False,
                    )
                except GbpApiError as exc:
                    msg = friendly_sync_error(exc)
                    conn.last_sync_error = msg
                    errors.append(msg)
                    if exc.is_quota:
                        api_quota_limited = True
                        rate_until = mark_rate_limited(
                            conn.user_id,
                            retry_after_sec=exc.retry_after_sec,
                            endpoint=exc.endpoint,
                            reason="google_429",
                        )
                        invalidate_accounts_cache(user_id)
                        break
                except Exception as exc:
                    _LOG.exception(
                        "GBP sync failed user_id=%s conn=%s google_account=%s",
                        user_id,
                        conn.id,
                        conn.google_email or conn.google_account_resource,
                    )
                    msg = friendly_sync_error(exc)
                    conn.last_sync_error = msg
                    errors.append(msg)
                    if _is_quota_error_text(str(exc)):
                        api_quota_limited = True
                        rate_until = mark_rate_limited(user_id, reason="google_429")

        db.commit()
        loc_count = db.execute(
            select(func.count(GbpLocation.id)).where(
                GbpLocation.user_id == user_id,
                GbpLocation.is_active.is_(True),
            )
        ).scalar_one()
        message = None
        sync_status = "ok"
        error_code: str | None = None
        if api_quota_limited:
            message = GBP_QUOTA_FRIENDLY_MSG
            sync_status = "rate_limited"
            error_code = "api_quota"
        elif errors and not total:
            message = errors[0]
            sync_status = "error"
            error_code = "sync_failed"
        elif total:
            message = f"Đã đồng bộ {total} địa điểm."
            invalidate_accounts_cache(user_id)

        return {
            "synced_locations": total,
            "connections": len(connections),
            "errors": errors,
            "already_syncing": False,
            "api_quota_limited": api_quota_limited,
            "connected": True,
            "sync_status": sync_status,
            "error_code": error_code,
            "rate_limit_until": rate_until or rate_limit_until_iso(user_id),
            "retry_after_seconds": retry_after_seconds(user_id),
            "message": message,
            "locations_count": int(loc_count or 0),
        }


def handle_oauth_callback(
    request: Request,
    db: Session,
    *,
    code: str,
    state: str,
) -> str:
    """Đổi code → lưu token → đồng bộ accounts/locations. Trả redirect path."""
    _require_config()
    redirect_uri = _redirect_uri()
    _allow_insecure_local(request)

    try:
        user_id = decode_gbp_oauth_state(state)
    except ValueError:
        _LOG.warning("GBP oauth invalid state")
        return "/google-map-seo?gbp_error=invalid_state"

    user = db.get(User, user_id)
    if not user:
        return "/google-map-seo?gbp_error=user_not_found"

    client_cfg = gbp_oauth_client_config(redirect_uri)
    flow = Flow.from_client_config(
        client_cfg,
        scopes=list(GBP_OAUTH_SCOPES),
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    try:
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        flow.fetch_token(authorization_response=_public_callback_url(request))
    except Exception as exc:
        _LOG.exception("GBP token exchange failed user=%s", user_id)
        return f"/google-map-seo?gbp_error={classify_gbp_api_error(exc)}"

    creds = flow.credentials
    if not creds or not creds.refresh_token:
        return "/google-map-seo?gbp_error=no_refresh_token"

    google_email = fetch_google_user_email(str(creds.token or ""))
    expiry = token_expiry_from_creds(creds)

    def _save_pending_connection(err_msg: str | None = None) -> str:
        conn = _upsert_connection(
            db,
            user_id=user_id,
            account_resource=_pending_account_resource(user_id),
            account_name="Chờ đồng bộ địa điểm",
            google_email=google_email,
            refresh_token=str(creds.refresh_token),
            access_token=str(creds.token or ""),
            token_expires_at=expiry,
        )
        if err_msg:
            conn.last_sync_error = err_msg
        db.commit()
        return "/google-map-seo?gbp=connected&gbp_sync=pending"

    if is_rate_limited(user_id):
        _LOG.info(
            "GBP oauth skip API user_id=%s source_action=oauth_connect reason=cooldown",
            user_id,
        )
        try:
            return _save_pending_connection(GBP_QUOTA_FRIENDLY_MSG)
        except Exception as save_exc:
            _LOG.exception("GBP save pending connection failed user_id=%s", user_id)
            db.rollback()
            return f"/google-map-seo?gbp_error={classify_gbp_api_error(save_exc)}"

    try:
        accounts = _list_accounts_for_user(
            creds,
            user_id=user_id,
            google_account=google_email,
            source_action="oauth_connect",
            use_cache=True,
        )
    except Exception as exc:
        _LOG.exception("GBP list accounts failed user_id=%s", user_id)
        err_code = classify_gbp_api_error(exc)
        if err_code in ("api_quota", "accounts_failed") and creds.refresh_token:
            try:
                if err_code == "api_quota":
                    mark_rate_limited(
                        user_id,
                        retry_after_sec=getattr(exc, "retry_after_sec", None),
                        endpoint=getattr(exc, "endpoint", ACCOUNTS_LIST_ENDPOINT),
                        reason="google_429",
                    )
                return _save_pending_connection(friendly_sync_error(exc))
            except Exception as save_exc:
                _LOG.exception("GBP save pending connection failed user_id=%s", user_id)
                db.rollback()
                return f"/google-map-seo?gbp_error={classify_gbp_api_error(save_exc)}"
        return f"/google-map-seo?gbp_error={err_code}"

    if not accounts:
        return "/google-map-seo?gbp_error=no_accounts"

    for acc in accounts:
        acc_resource = str(acc.get("name") or "")
        if not acc_resource:
            continue
        acc_title = str(acc.get("accountName") or acc.get("name") or "")
        conn = _upsert_connection(
            db,
            user_id=user_id,
            account_resource=acc_resource,
            account_name=acc_title or None,
            google_email=google_email,
            refresh_token=str(creds.refresh_token),
            access_token=str(creds.token or ""),
            token_expires_at=expiry,
        )
        try:
            sync_connection_locations(
                db,
                conn,
                source_action="oauth_connect",
                use_cache=True,
                accounts=accounts,
            )
        except Exception as exc:
            _LOG.exception("GBP initial sync failed conn=%s", conn.id)
            conn.last_sync_error = friendly_sync_error(exc)
            if classify_gbp_api_error(exc) == "api_quota":
                mark_rate_limited(
                    user_id,
                    retry_after_sec=getattr(exc, "retry_after_sec", None),
                    endpoint=getattr(exc, "endpoint", "locations.list"),
                    reason="google_429",
                )

    db.commit()
    return "/google-map-seo?gbp=connected"


def disconnect_user(db: Session, user_id: int, *, connection_id: int | None = None) -> int:
    q = select(GbpOAuthConnection).where(GbpOAuthConnection.user_id == user_id)
    if connection_id is not None:
        q = q.where(GbpOAuthConnection.id == connection_id)
    rows = db.execute(q).scalars().all()
    if not rows:
        return 0
    for conn in rows:
        locs = db.execute(select(GbpLocation).where(GbpLocation.connection_id == conn.id)).scalars().all()
        for loc in locs:
            db.delete(loc)
        conn.status = "revoked"
        conn.refresh_token_encrypted = ""
        conn.access_token_encrypted = ""
    db.commit()
    return len(rows)
