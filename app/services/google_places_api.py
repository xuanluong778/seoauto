"""Google Places API (New) — Text/Nearby Search, Place Details, Geocoding."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from app.core.places_settings import GEOCODE_API_URL, PLACES_API_BASE, get_places_api_key
from app.services.cost_control.executor import (
    CostControlBypassError,
    execute_guarded_external,
    guarded_requests_get,
    guarded_requests_post,
)
from app.services.cost_control.types import ExternalApiProvider

_LOG = logging.getLogger("google_places_api")

SEARCH_BASIC_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.types,nextPageToken"
)
DETAIL_CONTACT_MASK = "nationalPhoneNumber,websiteUri,googleMapsUri"
DETAIL_BASIC_MASK = "id,displayName,formattedAddress,rating,userRatingCount,types,location"

_CATEGORY_TYPE_MAP: dict[str, str] = {
    "spa": "spa",
    "nha khoa": "dentist",
    "dentist": "dentist",
    "gara": "car_repair",
    "gara ô tô": "car_repair",
    "nhà hàng": "restaurant",
    "nha hang": "restaurant",
    "restaurant": "restaurant",
    "cafe": "cafe",
    "cà phê": "cafe",
    "khách sạn": "lodging",
    "khach san": "lodging",
    "hotel": "lodging",
    "gym": "gym",
    "salon": "beauty_salon",
    "tiệm tóc": "hair_care",
    "bệnh viện": "hospital",
    "pharmacy": "pharmacy",
    "nhà thuốc": "pharmacy",
    "lawyer": "lawyer",
    "luật sư": "lawyer",
    "real estate": "real_estate_agency",
    "bất động sản": "real_estate_agency",
}


@dataclass
class ApiUsage:
    search_requests: int = 0
    detail_requests: int = 0
    geocode_requests: int = 0

    @property
    def total(self) -> int:
        return self.search_requests + self.detail_requests + self.geocode_requests

    def merge(self, other: ApiUsage) -> None:
        self.search_requests += other.search_requests
        self.detail_requests += other.detail_requests
        self.geocode_requests += other.geocode_requests


class PlacesApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        endpoint: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.endpoint = endpoint


def category_to_place_type(category: str) -> str | None:
    key = str(category or "").strip().lower()
    if not key:
        return None
    if key in _CATEGORY_TYPE_MAP:
        return _CATEGORY_TYPE_MAP[key]
    for frag, ptype in _CATEGORY_TYPE_MAP.items():
        if frag in key or key in frag:
            return ptype
    return None


def _api_key() -> str:
    key = get_places_api_key()
    if not key:
        raise PlacesApiError("not_configured", "Chưa cấu hình Google Places API", endpoint="config")
    return key


def _headers(field_mask: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": field_mask,
    }


def _parse_places_error(resp: requests.Response, *, endpoint: str) -> PlacesApiError:
    try:
        data = resp.json()
        err = data.get("error") or {}
        msg = str(err.get("message") or resp.text or "Lỗi Google Places API").strip()
        status = str(err.get("status") or "").upper()
    except Exception:
        msg = (resp.text or "Lỗi Google Places API")[:500]
        status = ""

    low = msg.lower()
    if resp.status_code == 403 or "REQUEST_DENIED" in status:
        return PlacesApiError(
            "not_configured",
            "Chưa cấu hình Google Places API hoặc API key không hợp lệ.",
            status_code=resp.status_code,
            endpoint=endpoint,
        )
    if resp.status_code == 429 or "RESOURCE_EXHAUSTED" in status or "quota" in low:
        return PlacesApiError(
            "quota_exceeded",
            "Google Places API đã vượt quota/giới hạn. Vui lòng thử lại sau vài phút.",
            retryable=True,
            status_code=resp.status_code,
            endpoint=endpoint,
        )
    if resp.status_code >= 500:
        return PlacesApiError(
            "upstream_error",
            "Google Places API tạm thời không phản hồi. Thử lại sau.",
            retryable=True,
            status_code=resp.status_code,
            endpoint=endpoint,
        )
    return PlacesApiError("api_error", msg[:500], status_code=resp.status_code, endpoint=endpoint)


def _with_retry(fn: Callable[[], Any], *, action: str) -> Any:
    def _is_retryable(exc: BaseException) -> bool:
        return isinstance(exc, PlacesApiError) and bool(exc.retryable)

    try:
        return execute_guarded_external(
            ExternalApiProvider.GOOGLE_PLACES,
            action,
            fn,
            is_retryable=_is_retryable,
        )
    except CostControlBypassError as exc:
        raise PlacesApiError(
            "cost_gate_blocked",
            "Yêu cầu chưa qua kiểm soát chi phí.",
            endpoint=action,
        ) from exc


def _normalize_place_id(raw: str) -> str:
    pid = str(raw or "").strip()
    if pid.startswith("places/"):
        return pid.split("/", 1)[1]
    return pid


def _display_name(obj: dict[str, Any] | None) -> str:
    if not obj:
        return ""
    dn = obj.get("displayName")
    if isinstance(dn, dict):
        return str(dn.get("text") or "").strip()
    return str(dn or "").strip()


def _category_from_types(types: list[Any] | None) -> str | None:
    if not types:
        return None
    return str(types[0] or "").replace("_", " ").strip() or None


def _maps_url_for_place(place_id: str, existing: str | None = None) -> str:
    url = str(existing or "").strip()
    if url:
        return url
    pid = _normalize_place_id(place_id)
    return f"https://www.google.com/maps/place/?q=place_id:{pid}"


def _parse_basic_place(place: dict[str, Any]) -> dict[str, Any]:
    pid = _normalize_place_id(str(place.get("id") or ""))
    return {
        "place_id": pid,
        "name": _display_name(place) or None,
        "address": str(place.get("formattedAddress") or "").strip() or None,
        "rating": float(place["rating"]) if place.get("rating") is not None else None,
        "review_count": int(place["userRatingCount"]) if place.get("userRatingCount") is not None else None,
        "category": _category_from_types(place.get("types")),
        "phone": None,
        "website": None,
        "latitude": None,
        "longitude": None,
        "maps_url": _maps_url_for_place(pid),
        "detail_fetched": False,
    }


def geocode_address(address: str, usage: ApiUsage | None = None) -> dict[str, float]:
    addr = str(address or "").strip()
    if not addr:
        raise PlacesApiError("invalid_request", "Thiếu địa chỉ để geocode.", endpoint="geocode")
    if "vietnam" not in addr.lower() and "việt nam" not in addr.lower():
        addr = f"{addr}, Vietnam"

    def _call() -> dict[str, float]:
        if usage is not None:
            usage.geocode_requests += 1
        resp = guarded_requests_get(
            ExternalApiProvider.GOOGLE_PLACES,
            "geocode",
            GEOCODE_API_URL,
            params={"address": addr, "key": _api_key(), "region": "vn"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise _parse_places_error(resp, endpoint="geocode")
        data = resp.json()
        status = str(data.get("status") or "")
        if status == "ZERO_RESULTS":
            raise PlacesApiError("geocode_not_found", f"Không tìm thấy tọa độ cho «{address}».", endpoint="geocode")
        if status != "OK":
            msg = str(data.get("error_message") or status)
            if status in ("OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"):
                raise PlacesApiError("quota_exceeded", "Google Geocoding API vượt quota.", endpoint="geocode", retryable=True)
            if status == "REQUEST_DENIED":
                raise PlacesApiError("not_configured", "Chưa cấu hình Google Places API.", endpoint="geocode")
            raise PlacesApiError("geocode_error", msg[:300], endpoint="geocode")
        results = data.get("results") or []
        if not results:
            raise PlacesApiError("geocode_not_found", f"Không tìm thấy tọa độ cho «{address}».", endpoint="geocode")
        loc = ((results[0] or {}).get("geometry") or {}).get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is None or lng is None:
            raise PlacesApiError("geocode_not_found", f"Không tìm thấy tọa độ cho «{address}».", endpoint="geocode")
        return {"latitude": float(lat), "longitude": float(lng)}

    try:
        return _with_retry(_call, action="geocode")
    except requests.RequestException as exc:
        raise PlacesApiError("network_error", "Không kết nối được Google Geocoding API.", endpoint="geocode") from exc


def _search_text_page(
    *,
    text_query: str,
    max_result_count: int,
    page_token: str | None = None,
    location_bias: dict[str, Any] | None = None,
    usage: ApiUsage | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "maxResultCount": max(1, min(20, int(max_result_count))),
        "languageCode": "vi",
        "regionCode": "VN",
    }
    if page_token:
        body["pageToken"] = page_token
    if location_bias:
        body["locationBias"] = location_bias

    if usage is not None:
        usage.search_requests += 1

    resp = guarded_requests_post(
        ExternalApiProvider.GOOGLE_PLACES,
        "places:searchText",
        f"{PLACES_API_BASE}/places:searchText",
        headers=_headers(SEARCH_BASIC_MASK),
        json=body,
        timeout=25,
    )
    if resp.status_code != 200:
        raise _parse_places_error(resp, endpoint="places:searchText")

    data = resp.json()
    rows = [_parse_basic_place(p) for p in (data.get("places") or [])]
    return rows, str(data.get("nextPageToken") or "") or None


def search_text_basic(
    text_query: str,
    *,
    limit: int = 20,
    location_bias: dict[str, Any] | None = None,
    usage: ApiUsage | None = None,
) -> list[dict[str, Any]]:
    q = str(text_query or "").strip()
    if not q:
        return []
    want = max(1, min(100, int(limit)))
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_token: str | None = None

    while len(collected) < want:
        def _page() -> tuple[list[dict[str, Any]], str | None]:
            return _search_text_page(
                text_query=q,
                max_result_count=min(20, want - len(collected)),
                page_token=page_token,
                location_bias=location_bias,
                usage=usage,
            )

        try:
            batch, page_token = _with_retry(_page, action="places:searchText")
        except requests.RequestException as exc:
            raise PlacesApiError("network_error", "Không kết nối được Google Places API.", endpoint="places:searchText") from exc

        for row in batch:
            pid = row.get("place_id") or ""
            if pid and pid not in seen:
                seen.add(pid)
                collected.append(row)
                if len(collected) >= want:
                    break
        if not page_token or not batch:
            break
        time.sleep(2.0)
    return collected[:want]


def _search_nearby_page(
    *,
    lat: float,
    lng: float,
    radius_m: float,
    included_types: list[str],
    max_result_count: int,
    page_token: str | None = None,
    usage: ApiUsage | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    body: dict[str, Any] = {
        "includedTypes": included_types[:1],
        "maxResultCount": max(1, min(20, int(max_result_count))),
        "locationRestriction": {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(max(100.0, min(radius_m, 50000.0))),
            }
        },
        "languageCode": "vi",
        "regionCode": "VN",
    }
    if page_token:
        body["pageToken"] = page_token

    if usage is not None:
        usage.search_requests += 1

    resp = guarded_requests_post(
        ExternalApiProvider.GOOGLE_PLACES,
        "places:searchNearby",
        f"{PLACES_API_BASE}/places:searchNearby",
        headers=_headers(SEARCH_BASIC_MASK),
        json=body,
        timeout=25,
    )
    if resp.status_code != 200:
        raise _parse_places_error(resp, endpoint="places:searchNearby")

    data = resp.json()
    rows = [_parse_basic_place(p) for p in (data.get("places") or [])]
    return rows, str(data.get("nextPageToken") or "") or None


def search_nearby_basic(
    lat: float,
    lng: float,
    *,
    radius_m: float,
    included_types: list[str],
    limit: int = 20,
    usage: ApiUsage | None = None,
) -> list[dict[str, Any]]:
    types = [t for t in included_types if t]
    if not types:
        return []
    want = max(1, min(100, int(limit)))
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_token: str | None = None

    while len(collected) < want:
        def _page() -> tuple[list[dict[str, Any]], str | None]:
            return _search_nearby_page(
                lat=lat,
                lng=lng,
                radius_m=radius_m,
                included_types=types,
                max_result_count=min(20, want - len(collected)),
                page_token=page_token,
                usage=usage,
            )

        try:
            batch, page_token = _with_retry(_page, action="places:searchNearby")
        except requests.RequestException as exc:
            raise PlacesApiError("network_error", "Không kết nối được Google Places API.", endpoint="places:searchNearby") from exc

        for row in batch:
            pid = row.get("place_id") or ""
            if pid and pid not in seen:
                seen.add(pid)
                collected.append(row)
                if len(collected) >= want:
                    break
        if not page_token or not batch:
            break
        time.sleep(2.0)
    return collected[:want]


def get_place_contact_details(place_id: str, usage: ApiUsage | None = None) -> dict[str, Any]:
    """Place Details tối thiểu — SĐT, website, link Map."""
    pid = _normalize_place_id(place_id)
    if not pid:
        raise PlacesApiError("invalid_request", "place_id không hợp lệ.", endpoint="places.get")

    def _call() -> dict[str, Any]:
        if usage is not None:
            usage.detail_requests += 1
        resp = guarded_requests_get(
            ExternalApiProvider.GOOGLE_PLACES,
            "places.get",
            f"{PLACES_API_BASE}/places/{pid}",
            headers=_headers(DETAIL_CONTACT_MASK),
            params={"languageCode": "vi"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise _parse_places_error(resp, endpoint="places.get")
        data = resp.json()
        return {
            "phone": str(data.get("nationalPhoneNumber") or "").strip() or None,
            "website": str(data.get("websiteUri") or "").strip() or None,
            "maps_url": _maps_url_for_place(pid, str(data.get("googleMapsUri") or "").strip() or None),
        }

    try:
        return _with_retry(_call, action="places.get")
    except requests.RequestException as exc:
        raise PlacesApiError("network_error", "Không kết nối được Google Places API.", endpoint="places.get") from exc


def norm_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[-10:] if len(digits) >= 8 else digits


def norm_website(url: str | None) -> str:
    w = str(url or "").strip().lower()
    w = re.sub(r"^https?://", "", w)
    w = w.rstrip("/").split("/")[0]
    return w.split("?")[0]
