"""Google Business Profile API — accounts & locations (low-level)."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.core.gbp_settings import GBP_OAUTH_SCOPES, get_gbp_oauth_settings

_LOG = logging.getLogger("google_map_gbp.api")

ACCOUNT_MGMT_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
BUSINESS_INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
ACCOUNTS_LIST_ENDPOINT = "accounts.list"

GBP_QUOTA_FRIENDLY_MSG = "Google API đang giới hạn lượt gọi, vui lòng thử lại sau 1–2 phút."

_MAX_RETRIES = 5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_COOLDOWN_SEC = 600


def compute_retry_delay(attempt: int, retry_after_sec: int | None) -> float:
    """Exponential backoff + jitter; ưu tiên Retry-After từ Google."""
    if retry_after_sec and retry_after_sec > 0:
        return float(min(int(retry_after_sec), _MAX_COOLDOWN_SEC))
    bases = (2.0, 4.0, 8.0, 16.0, 32.0)
    base = bases[min(max(attempt, 0), len(bases) - 1)]
    jitter = random.uniform(0.0, base * 0.25)
    return base + jitter


@dataclass
class GbpApiError(RuntimeError):
    message: str
    status_code: int
    endpoint: str
    retry_count: int = 0
    retry_after_sec: int | None = None
    google_account: str | None = None
    user_id: int | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    @property
    def is_quota(self) -> bool:
        return self.status_code == 429 or "quota" in self.message.lower()


def classify_gbp_api_error(exc: BaseException) -> str:
    """Map lỗi Google API → mã lỗi hiển thị trên UI."""
    if isinstance(exc, GbpApiError) and exc.is_quota:
        return "api_quota"
    msg = str(exc).lower()
    if (
        "has not been used" in msg
        or "is disabled" in msg
        or "not enabled" in msg
        or ("403" in msg and "disabled" in msg)
    ):
        return "api_disabled"
    if "403" in msg or "permission denied" in msg or "access not configured" in msg:
        return "api_forbidden"
    if "401" in msg or "unauthorized" in msg:
        return "api_unauthorized"
    if "429" in msg or "quota" in msg or "rate limit" in msg:
        return "api_quota"
    return "accounts_failed"


def credentials_from_tokens(
    *,
    refresh_token: str,
    access_token: str | None = None,
    token_expiry: datetime | None = None,
) -> Credentials | None:
    s = get_gbp_oauth_settings()
    if not s or not refresh_token:
        return None
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s["client_id"],
        client_secret=s["client_secret"],
        scopes=list(GBP_OAUTH_SCOPES),
    )
    if token_expiry:
        creds.expiry = token_expiry.replace(tzinfo=None) if token_expiry.tzinfo else token_expiry
    if not creds.valid:
        creds.refresh(Request())
    return creds


def fetch_google_user_email(access_token: str) -> str | None:
    try:
        r = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return str(data.get("email") or "").strip() or None
    except Exception:
        _LOG.exception("GBP userinfo failed")
        return None


def _auth_headers(creds: Credentials) -> dict[str, str]:
    if not creds.valid:
        creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}"}


def _parse_retry_after(response: requests.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def _error_reason(response: requests.Response) -> str:
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            return str(err.get("status") or err.get("message") or "")[:120]
    except Exception:
        pass
    return (response.text or "")[:120]


def _log_api_call(
    *,
    user_id: int | None,
    endpoint: str,
    source_action: str,
    status_code: int,
    retry_count: int = 0,
) -> None:
    _LOG.info(
        "GBP API call user_id=%s endpoint=%s source_action=%s status_code=%s retry_count=%s",
        user_id,
        endpoint,
        source_action,
        status_code,
        retry_count,
    )


def _log_api_failure(
    *,
    user_id: int | None,
    endpoint: str,
    source_action: str,
    status_code: int,
    retry_count: int,
    retry_after_sec: int | None = None,
    error_reason: str | None = None,
    connection_id: int | None = None,
) -> None:
    _LOG.warning(
        "GBP API failure user_id=%s connection_id=%s endpoint=%s source_action=%s "
        "status_code=%s retry_count=%s retry_after=%s reason=%s",
        user_id,
        connection_id,
        endpoint,
        source_action,
        status_code,
        retry_count,
        retry_after_sec,
        (error_reason or "")[:120],
    )


def _request_with_retry(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    endpoint: str,
    source_action: str,
    user_id: int | None = None,
    google_account: str | None = None,
    connection_id: int | None = None,
    max_retries: int = _MAX_RETRIES,
) -> requests.Response:
    """Gọi HTTP với tối đa 5 lần retry (Retry-After hoặc exponential backoff + jitter)."""
    last_response: requests.Response | None = None
    retry_count = 0
    for attempt in range(max_retries + 1):
        if attempt > 0:
            ra = _parse_retry_after(last_response) if last_response is not None else None
            delay = compute_retry_delay(attempt - 1, ra)
            time.sleep(delay)
            retry_count = attempt
        r = requests.request(method, url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            _log_api_call(
                user_id=user_id,
                endpoint=endpoint,
                source_action=source_action,
                status_code=200,
                retry_count=retry_count,
            )
            return r
        last_response = r
        if r.status_code not in _RETRYABLE_STATUS or attempt >= max_retries:
            break
        _log_api_failure(
            user_id=user_id,
            connection_id=connection_id,
            endpoint=endpoint,
            source_action=source_action,
            status_code=r.status_code,
            retry_count=retry_count + 1,
            retry_after_sec=_parse_retry_after(r),
            error_reason=_error_reason(r),
        )
    assert last_response is not None
    retry_after = _parse_retry_after(last_response)
    _log_api_failure(
        user_id=user_id,
        connection_id=connection_id,
        endpoint=endpoint,
        source_action=source_action,
        status_code=last_response.status_code,
        retry_count=retry_count,
        retry_after_sec=retry_after,
        error_reason=_error_reason(last_response),
    )
    raise GbpApiError(
        f"{endpoint} HTTP {last_response.status_code}: {last_response.text[:300]}",
        status_code=last_response.status_code,
        endpoint=endpoint,
        retry_count=retry_count,
        retry_after_sec=retry_after,
        google_account=google_account,
        user_id=user_id,
    )


def list_accounts(
    creds: Credentials,
    *,
    user_id: int | None = None,
    google_account: str | None = None,
    connection_id: int | None = None,
    source_action: str = "accounts_list",
) -> list[dict[str, Any]]:
    headers = _auth_headers(creds)
    url = f"{ACCOUNT_MGMT_BASE}/accounts"
    r = _request_with_retry(
        method="GET",
        url=url,
        headers=headers,
        endpoint=ACCOUNTS_LIST_ENDPOINT,
        source_action=source_action,
        user_id=user_id,
        google_account=google_account,
        connection_id=connection_id,
    )
    data = r.json()
    return list(data.get("accounts") or [])


def list_locations(
    creds: Credentials,
    account_name: str,
    *,
    user_id: int | None = None,
    google_account: str | None = None,
    connection_id: int | None = None,
    source_action: str = "locations_list",
) -> list[dict[str, Any]]:
    from app.services.google_map_gbp_sync_guard import get_locations_cached, set_locations_cached

    if user_id is not None:
        cached = get_locations_cached(int(user_id), account_name)
        if cached is not None:
            _LOG.info(
                "GBP locations.list cache hit user_id=%s account=%s source_action=%s",
                user_id,
                account_name,
                source_action,
            )
            return cached

    headers = _auth_headers(creds)
    parent = account_name if account_name.startswith("accounts/") else f"accounts/{account_name}"
    url = f"{BUSINESS_INFO_BASE}/{parent}/locations"
    params: dict[str, Any] = {
        "readMask": "name,title,storefrontAddress,phoneNumbers,categories,websiteUri,metadata",
        "pageSize": 100,
    }
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        if page_token:
            params["pageToken"] = page_token
        r = _request_with_retry(
            method="GET",
            url=url,
            headers=headers,
            params=params,
            endpoint="locations.list",
            source_action=source_action,
            user_id=user_id,
            google_account=google_account or account_name,
            connection_id=connection_id,
        )
        data = r.json()
        items.extend(list(data.get("locations") or []))
        page_token = str(data.get("nextPageToken") or "")
        if not page_token:
            break
    if user_id is not None:
        set_locations_cached(int(user_id), account_name, items)
    return items


def location_to_audit_snapshot(loc: dict[str, Any]) -> dict[str, Any]:
    """Chuyển payload Google → snapshot cho Check Map (chỉ field có trong API)."""
    addr = loc.get("storefrontAddress") or {}
    lines = addr.get("addressLines") or []
    address_line = ", ".join(str(x) for x in lines if x)
    locality = str(addr.get("locality") or "")
    cats = loc.get("categories") or {}
    primary = cats.get("primaryCategory") or {}
    primary_name = str(primary.get("displayName") or primary.get("name") or "")
    phones = loc.get("phoneNumbers") or {}
    phone = str(phones.get("primaryPhone") or "")
    meta = loc.get("metadata") or {}
    verification = str(meta.get("hasVoiceOfMerchant") or "")
    verified = verification.lower() in ("true", "1") if verification else None
    title = str(loc.get("title") or "")
    website = str(loc.get("websiteUri") or "")
    desc_len = None
    if isinstance(meta.get("description"), str):
        desc_len = len(meta["description"])

    snapshot: dict[str, Any] = {
        "synced": True,
        "source": "google_business_profile",
        "google_location_resource": str(loc.get("name") or ""),
        "businessInfo": {
            "hasName": bool(title),
            "hasAddress": bool(address_line),
            "hasPhone": bool(phone),
            "hasHours": meta.get("regularHours") is not None,
            "hoursDaysCovered": None,
            "verified": verified if verified is not None else False,
        },
        "category": {
            "primary": primary_name or None,
            "secondaryCount": len(cats.get("additionalCategories") or []),
        },
        "description": {"textLength": desc_len, "hasLocalKeywords": None} if desc_len is not None else None,
        "media": None,
        "reviews": None,
        "posts": None,
        "services": None,
        "website": {
            "url": website or None,
            "napConsistent": None,
            "hasTracking": None,
            "hasLocalLanding": None,
        }
        if website
        else None,
    }
    return snapshot


def parse_location_row(account_resource: str, loc: dict[str, Any]) -> dict[str, Any]:
    addr = loc.get("storefrontAddress") or {}
    lines = addr.get("addressLines") or []
    cats = loc.get("categories") or {}
    primary = cats.get("primaryCategory") or {}
    phones = loc.get("phoneNumbers") or {}
    meta = loc.get("metadata") or {}
    return {
        "google_location_resource": str(loc.get("name") or ""),
        "google_account_resource": account_resource,
        "title": str(loc.get("title") or ""),
        "address_line": ", ".join(str(x) for x in lines if x),
        "locality": str(addr.get("locality") or ""),
        "phone": str(phones.get("primaryPhone") or ""),
        "website_uri": str(loc.get("websiteUri") or ""),
        "primary_category": str(primary.get("displayName") or primary.get("name") or ""),
        "verification_status": "verified" if meta.get("hasVoiceOfMerchant") else "unknown",
        "audit_snapshot": location_to_audit_snapshot(loc),
    }


def token_expiry_from_creds(creds: Credentials) -> datetime | None:
    if not creds.expiry:
        return None
    return creds.expiry.replace(tzinfo=timezone.utc)


def patch_location_description(creds: Credentials, location_resource: str, description: str) -> dict[str, Any]:
    """Cập nhật mô tả hồ sơ GBP qua Business Information API."""
    headers = {**_auth_headers(creds), "Content-Type": "application/json"}
    resource = location_resource if location_resource.startswith("locations/") else location_resource
    if not resource.startswith("locations/"):
        resource = f"locations/{resource.split('/')[-1]}"
    url = f"{BUSINESS_INFO_BASE}/{resource}?updateMask=profile.description"
    body = {"profile": {"description": str(description or "")[:750]}}
    r = requests.patch(url, headers=headers, json=body, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"locations.patch HTTP {r.status_code}: {r.text[:400]}")
    return r.json() if r.content else {}
