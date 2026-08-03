"""Google Map SEO — Lead Map Scanner (cost-optimized, 2-step)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.lead_scanner_settings import (
    lead_allowed_limits,
    lead_api_cost_estimate_usd,
    lead_cache_ttl_sec,
    lead_scanner_enabled,
    lead_user_rate_limit_per_min,
    limits_for_plan,
    plan_limits,
)
from app.core.places_settings import places_api_configured
from app.models.google_map_gbp import GbpLead, GbpLeadApiLog, GbpLeadScan
from app.models.user import User
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.cost_control import CostGateRequest, ExternalApiProvider, cost_gate_session
from app.services.credits import (
    consume_credits,
    cost_lead_export,
    cost_lead_geocode,
    cost_lead_place_detail,
    cost_lead_scan_search,
    credits_enforced,
    ensure_sufficient_credits,
    get_available_balance,
    quote_lead_basic_scan,
    quote_lead_detail,
)
from app.services.google_map_lead_guard import (
    LeadScanGuard,
    check_ip_rate_limit,
    check_scan_cooldown,
    check_user_rate_limit,
    ensure_google_api_allowed,
    mark_google_cooldown,
    mark_scan_cooldown,
)
from app.services.google_places_api import (
    ApiUsage,
    PlacesApiError,
    category_to_place_type,
    geocode_address,
    get_place_contact_details,
    norm_phone,
    norm_website,
    search_nearby_basic,
    search_text_basic,
)

_LOG = logging.getLogger("google_map_lead_scanner")

LEAD_STATUS_LABELS = {
    "new": "Mới",
    "contacted": "Đã liên hệ",
    "qualified": "Tiềm năng",
    "rejected": "Loại",
}

LOW_RATING_THRESHOLD = 4.0
FEW_REVIEWS_THRESHOLD = 10

_EXPORT_HEADERS = [
    "STT",
    "Tên doanh nghiệp",
    "SĐT",
    "Địa chỉ",
    "Website",
    "Rating",
    "Review",
    "Category",
    "Link Google Map",
    "Trạng thái lead",
    "place_id",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _valid_limit(limit: int, plan_slug: str | None = None) -> int:
    lim = int(limit or 20)
    if lim not in lead_allowed_limits():
        lim = 20
    plan_max = limits_for_plan(plan_slug).get("max_results", 20)
    return min(lim, plan_max)


def _valid_radius_km(radius_km: float) -> float:
    try:
        r = float(radius_km)
    except (TypeError, ValueError):
        r = 5.0
    return max(0.5, min(50.0, r))


def _norm_part(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def build_cache_key(user_id: int, params: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(user_id),
            _norm_part(params.get("mode") or "keyword"),
            _norm_part(params.get("keyword") or ""),
            _norm_part(params.get("category") or ""),
            _norm_part(params.get("province") or ""),
            _norm_part(params.get("district") or ""),
            str(round(_valid_radius_km(float(params.get("radius_km") or 5)), 1)),
            str(_valid_limit(int(params.get("limit") or 20))),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _area_label(province: str, district: str) -> str:
    parts = [p for p in (district.strip(), province.strip()) if p]
    return ", ".join(parts)


def _build_location_bias(lat: float, lng: float, radius_m: float) -> dict[str, Any]:
    return {
        "circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": float(radius_m),
        }
    }


def _log_api_error(
    db: Session,
    *,
    user_id: int,
    scan_id: int | None,
    exc: PlacesApiError,
    params: dict[str, Any],
) -> None:
    db.add(
        GbpLeadApiLog(
            user_id=user_id,
            scan_id=scan_id,
            endpoint=str(exc.endpoint or "places")[:120],
            status_code=exc.status_code,
            error_code=exc.code,
            message=str(exc.message or "")[:500],
            keyword=str(params.get("keyword") or params.get("category") or "")[:300] or None,
            province=str(params.get("province") or "")[:120] or None,
            district=str(params.get("district") or "")[:120] or None,
        )
    )


def _scan_count_since(db: Session, user_id: int, since: datetime) -> int:
    return int(
        db.query(func.count(GbpLeadScan.id))
        .filter(
            GbpLeadScan.user_id == user_id,
            GbpLeadScan.created_at >= since,
            GbpLeadScan.status.in_(("completed", "empty", "cached")),
            GbpLeadScan.data_source != "cache",
        )
        .scalar()
        or 0
    )


def _check_plan_limits(db: Session, user: User, limit: int) -> dict[str, Any]:
    from app.services.plan_quota_service import quota_exceeded_detail

    plan_slug = resolve_cau_ai_plan_slug(db, user) or "free"
    lim = limits_for_plan(plan_slug)
    now = _utc_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    daily_used = _scan_count_since(db, user.id, day_start)
    monthly_used = _scan_count_since(db, user.id, month_start)
    if daily_used >= lim["daily_scans"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                **quota_exceeded_detail(
                    feature_key="lead_map_scan",
                    plan_slug=plan_slug,
                    message=f"Đã đạt giới hạn {lim['daily_scans']} lượt quét/ngày cho gói {plan_slug}.",
                ),
                "code": "daily_limit",
            },
        )
    if monthly_used >= lim["monthly_scans"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                **quota_exceeded_detail(
                    feature_key="lead_map_scan",
                    plan_slug=plan_slug,
                    message=f"Đã đạt giới hạn {lim['monthly_scans']} lượt quét/tháng cho gói {plan_slug}.",
                ),
                "code": "monthly_limit",
            },
        )
    if limit > lim["max_results"]:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "max_results_exceeded",
                "message": f"Gói {plan_slug} chỉ cho phép tối đa {lim['max_results']} lead/lần quét.",
            },
        )
    return {
        "plan_slug": plan_slug,
        "daily_used": daily_used,
        "daily_limit": lim["daily_scans"],
        "monthly_used": monthly_used,
        "monthly_limit": lim["monthly_scans"],
        "max_results": lim["max_results"],
    }


def _find_cached_scan(db: Session, user_id: int, cache_key: str) -> GbpLeadScan | None:
    cutoff = _utc_now() - timedelta(seconds=lead_cache_ttl_sec())
    return (
        db.query(GbpLeadScan)
        .filter(
            GbpLeadScan.user_id == user_id,
            GbpLeadScan.cache_key == cache_key,
            GbpLeadScan.status.in_(("completed", "empty")),
            GbpLeadScan.created_at >= cutoff,
        )
        .order_by(GbpLeadScan.created_at.desc())
        .first()
    )


def _dedupe_leads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_place: set[str] = set()
    seen_phone: set[str] = set()
    seen_web: set[str] = set()
    for row in rows:
        pid = str(row.get("place_id") or "")
        phone_key = norm_phone(row.get("phone"))
        web_key = norm_website(row.get("website"))
        if pid and pid in seen_place:
            continue
        if phone_key and phone_key in seen_phone:
            continue
        if web_key and web_key in seen_web:
            continue
        if pid:
            seen_place.add(pid)
        if phone_key:
            seen_phone.add(phone_key)
        if web_key:
            seen_web.add(web_key)
        row["dedupe_key"] = pid or (f"ph:{phone_key}" if phone_key else f"web:{web_key}")
        out.append(row)
    return out


def _lead_row_dict(lead: GbpLead, idx: int | None = None) -> dict[str, Any]:
    return {
        "index": idx,
        "id": lead.id,
        "place_id": lead.place_id,
        "name": lead.name,
        "phone": lead.phone,
        "address": lead.address,
        "website": lead.website,
        "rating": lead.rating,
        "review_count": lead.review_count,
        "category": lead.category,
        "latitude": lead.latitude,
        "longitude": lead.longitude,
        "maps_url": lead.maps_url,
        "lead_status": lead.lead_status,
        "lead_status_label": LEAD_STATUS_LABELS.get(lead.lead_status or "new", "Mới"),
        "detail_fetched": bool(lead.detail_fetched),
    }


def _scan_summary(scan: GbpLeadScan) -> dict[str, Any]:
    return {
        "id": scan.id,
        "mode": scan.mode,
        "keyword": scan.keyword,
        "category": scan.category,
        "province": scan.province,
        "district": scan.district,
        "radius_km": round((scan.radius_m or 0) / 1000.0, 1) if scan.radius_m else None,
        "limit": scan.result_limit,
        "status": scan.status,
        "result_count": scan.result_count,
        "unique_count": scan.unique_count,
        "credits_charged": scan.credits_charged,
        "data_source": scan.data_source,
        "api_request_count": scan.api_request_count,
        "search_request_count": scan.search_request_count,
        "detail_request_count": scan.detail_request_count,
        "geocode_request_count": scan.geocode_request_count,
        "cached_from_scan_id": scan.cached_from_scan_id,
        "error_message": scan.error_message,
        "created_at": scan.created_at.isoformat() if scan.created_at else None,
    }


def get_scanner_config(db: Session, user: User) -> dict[str, Any]:
    plan_slug = resolve_cau_ai_plan_slug(db, user) or "free"
    lim = limits_for_plan(plan_slug)
    balance, _ = ensure_sufficient_credits(db, user.id, 0)
    now = _utc_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    return {
        "enabled": lead_scanner_enabled(),
        "places_configured": places_api_configured(),
        "credits_enforced": credits_enforced(),
        "balance": balance,
        "plan_slug": plan_slug,
        "limits": lead_allowed_limits(),
        "plan_limits": lim,
        "usage": {
            "daily_used": _scan_count_since(db, user.id, day_start),
            "daily_limit": lim["daily_scans"],
            "monthly_used": _scan_count_since(db, user.id, month_start),
            "monthly_limit": lim["monthly_scans"],
        },
        "costs": {
            "basic_scan_search": cost_lead_scan_search(),
            "place_detail": cost_lead_place_detail(),
            "geocode": cost_lead_geocode(),
            "export": cost_lead_export(),
        },
        "cache_ttl_sec": lead_cache_ttl_sec(),
        "detail_cost_warning": "Lấy SĐT/website sẽ tốn credit cao hơn — chỉ gọi khi bạn bấm «Lấy SĐT».",
        "filters": [
            {"id": "has_phone", "label": "Có SĐT"},
            {"id": "no_phone", "label": "Không có SĐT"},
            {"id": "has_website", "label": "Có website"},
            {"id": "no_website", "label": "Chưa có website"},
            {"id": "low_rating", "label": "Rating thấp"},
            {"id": "few_reviews", "label": "Ít review"},
        ],
    }


def quote_scan(db: Session, user: User, params: dict[str, Any]) -> dict[str, Any]:
    _ensure_feature_ready()
    plan_slug = resolve_cau_ai_plan_slug(db, user) or "free"
    limit = _valid_limit(int(params.get("limit") or 20), plan_slug)
    _check_plan_limits(db, user, limit)
    cache_key = build_cache_key(user.id, {**params, "limit": limit})
    cached = _find_cached_scan(db, user.id, cache_key)
    quote = quote_lead_basic_scan(
        mode=str(params.get("mode") or "keyword"),
        limit=limit,
        from_cache=bool(cached),
    )
    detail_quote = quote_lead_detail(1)
    return {
        **quote,
        "mode": str(params.get("mode") or "keyword"),
        "limit": limit,
        "from_cache": bool(cached),
        "cache_scan_id": cached.id if cached else None,
        "expected_leads": limit,
        "data_included": [
            "place_id",
            "tên doanh nghiệp",
            "địa chỉ",
            "rating",
            "số review",
            "category",
            "link Google Map (ước tính)",
        ],
        "data_excluded_until_detail": ["SĐT", "website chính xác"],
        "detail_credit_per_lead": detail_quote["detail_cost"],
        "detail_warning": "Lấy SĐT/website sẽ tốn credit cao hơn — chỉ gọi khi bạn bấm «Lấy SĐT».",
    }


def _ensure_feature_ready() -> None:
    if not lead_scanner_enabled():
        raise HTTPException(status_code=503, detail={"code": "feature_disabled", "message": "Lead Map Scanner đang tắt."})
    if not places_api_configured():
        raise HTTPException(
            status_code=503,
            detail={"code": "places_not_configured", "message": "Chưa cấu hình Google Places API"},
        )


def _collect_basic_rows(params: dict[str, Any], usage: ApiUsage) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = str(params.get("mode") or "keyword").strip().lower()
    limit = _valid_limit(int(params.get("limit") or 20))
    radius_km = _valid_radius_km(float(params.get("radius_km") or 5))
    radius_m = radius_km * 1000.0
    meta: dict[str, Any] = {"mode": mode, "limit": limit, "radius_km": radius_km}

    if mode == "keyword":
        keyword = str(params.get("keyword") or "").strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="Nhập từ khóa tìm kiếm.")
        province = str(params.get("province") or "").strip()
        district = str(params.get("district") or "").strip()
        location_bias = None
        if province or district:
            try:
                coords = geocode_address(_area_label(province, district), usage)
                location_bias = _build_location_bias(coords["latitude"], coords["longitude"], radius_m)
                meta["geocoded"] = True
            except PlacesApiError:
                meta["geocoded"] = False
        rows = search_text_basic(keyword, limit=limit, location_bias=location_bias, usage=usage)
        meta["query"] = keyword
        return rows, meta

    if mode == "category":
        category = str(params.get("category") or "").strip()
        province = str(params.get("province") or "").strip()
        district = str(params.get("district") or "").strip()
        if not category:
            raise HTTPException(status_code=400, detail="Nhập ngành nghề/danh mục.")
        if not province:
            raise HTTPException(status_code=400, detail="Nhập tỉnh/thành.")
        area = _area_label(province, district)
        coords = geocode_address(area, usage)
        meta["geocoded"] = True
        meta["center"] = coords
        place_type = category_to_place_type(category)
        rows: list[dict[str, Any]] = []
        if place_type:
            rows = search_nearby_basic(
                coords["latitude"],
                coords["longitude"],
                radius_m=radius_m,
                included_types=[place_type],
                limit=limit,
                usage=usage,
            )
            meta["nearby_type"] = place_type
        if len(rows) < limit:
            text_q = f"{category} {area}".strip()
            text_rows = search_text_basic(
                text_q,
                limit=limit,
                location_bias=_build_location_bias(coords["latitude"], coords["longitude"], radius_m),
                usage=usage,
            )
            seen = {r.get("place_id") for r in rows}
            for row in text_rows:
                pid = row.get("place_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    rows.append(row)
                if len(rows) >= limit:
                    break
            meta["text_query"] = text_q
        return rows[:limit], meta

    raise HTTPException(status_code=400, detail="Chế độ quét không hợp lệ.")


def _apply_filter(leads: list[dict[str, Any]], filt: str | None) -> list[dict[str, Any]]:
    f = str(filt or "").strip().lower()
    if not f:
        return leads
    out: list[dict[str, Any]] = []
    for row in leads:
        phone = str(row.get("phone") or "").strip()
        website = str(row.get("website") or "").strip()
        rating = row.get("rating")
        reviews = row.get("review_count")
        if f == "has_phone" and not phone:
            continue
        if f == "no_phone" and phone:
            continue
        if f == "has_website" and not website:
            continue
        if f == "no_website" and website:
            continue
        if f == "low_rating":
            if rating is None or float(rating) >= LOW_RATING_THRESHOLD:
                continue
        if f == "few_reviews":
            if reviews is None or int(reviews) >= FEW_REVIEWS_THRESHOLD:
                continue
        out.append(row)
    return out


def _response_from_scan(db: Session, scan: GbpLeadScan, *, from_cache: bool = False) -> dict[str, Any]:
    leads = [_lead_row_dict(l, i + 1) for i, l in enumerate(_leads_for_scan(db, scan.id))]
    return {
        "scan": _scan_summary(scan),
        "leads": leads,
        "credits_charged": scan.credits_charged,
        "from_cache": from_cache,
        "balance_after": get_available_balance(db, scan.user_id),
    }


def run_scan(
    db: Session,
    user: User,
    params: dict[str, Any],
    *,
    client_ip: str | None = None,
) -> dict[str, Any]:
    _ensure_feature_ready()
    check_user_rate_limit(user.id)
    check_ip_rate_limit(client_ip)

    plan_slug = resolve_cau_ai_plan_slug(db, user) or "free"
    limit = _valid_limit(int(params.get("limit") or 20), plan_slug)
    _check_plan_limits(db, user, limit)
    cache_key = build_cache_key(user.id, {**params, "limit": limit})

    cached = _find_cached_scan(db, user.id, cache_key)
    if cached:
        return _response_from_scan(db, cached, from_cache=True)

    check_scan_cooldown(user.id, cache_key)
    quote = quote_lead_basic_scan(mode=str(params.get("mode") or "keyword"), limit=limit, from_cache=False)
    required = int(quote["credit_required"])

    gate_req = CostGateRequest(
        db=db,
        user=user,
        provider=ExternalApiProvider.GOOGLE_PLACES,
        action="lead_scan",
        credit_cost=required,
        require_paid_plan=True,
        single_flight_key=f"lead_scan:{user.id}",
        cooldown_key=f"google_places:{user.id}",
        cooldown_message="Google Places API tạm thời bị giới hạn. Vui lòng thử lại sau vài phút.",
        rate_limit_per_min=lead_user_rate_limit_per_min(),
    )

    with cost_gate_session(gate_req):
        with LeadScanGuard(user.id):
            ensure_google_api_allowed(user.id, action="lead_scan")
            mark_scan_cooldown(user.id, cache_key)

            scan = GbpLeadScan(
                user_id=user.id,
                mode=str(params.get("mode") or "keyword").strip().lower(),
                keyword=str(params.get("keyword") or "").strip() or None,
                category=str(params.get("category") or "").strip() or None,
                province=str(params.get("province") or "").strip() or None,
                district=str(params.get("district") or "").strip() or None,
                radius_m=int(_valid_radius_km(float(params.get("radius_km") or 5)) * 1000),
                result_limit=limit,
                status="running",
                cache_key=cache_key,
                data_source="api",
                params_json=json.dumps(params, ensure_ascii=False),
            )
            db.add(scan)
            db.flush()

            usage = ApiUsage()
            try:
                raw_rows, search_meta = _collect_basic_rows({**params, "limit": limit}, usage)
                unique_rows = _dedupe_leads(raw_rows)
                for row in unique_rows:
                    db.add(
                        GbpLead(
                            scan_id=scan.id,
                            user_id=user.id,
                            place_id=row["place_id"],
                            name=row.get("name"),
                            phone=row.get("phone"),
                            address=row.get("address"),
                            website=row.get("website"),
                            rating=row.get("rating"),
                            review_count=row.get("review_count"),
                            category=row.get("category"),
                            latitude=row.get("latitude"),
                            longitude=row.get("longitude"),
                            maps_url=row.get("maps_url"),
                            lead_status="new",
                            dedupe_key=row.get("dedupe_key"),
                            detail_fetched=False,
                            data_source="search",
                        )
                    )
                scan.status = "completed" if unique_rows else "empty"
                scan.result_count = len(raw_rows)
                scan.unique_count = len(unique_rows)
                scan.api_request_count = usage.total
                scan.search_request_count = usage.search_requests
                scan.geocode_request_count = usage.geocode_requests
                scan.detail_request_count = usage.detail_requests
                scan.params_json = json.dumps({**params, "search_meta": search_meta}, ensure_ascii=False)
            except PlacesApiError as exc:
                scan.status = "failed"
                scan.error_message = exc.message[:500]
                _log_api_error(db, user_id=user.id, scan_id=scan.id, exc=exc, params=params)
                db.commit()
                if exc.code == "quota_exceeded":
                    mark_google_cooldown(user.id)
                code = status.HTTP_429_TOO_MANY_REQUESTS if exc.code == "quota_exceeded" else status.HTTP_503_SERVICE_UNAVAILABLE
                raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message}) from exc
            except HTTPException:
                scan.status = "failed"
                db.commit()
                raise
            except Exception as exc:
                scan.status = "failed"
                scan.error_message = str(exc)[:500]
                db.commit()
                _LOG.exception("lead scan failed user=%s", user.id)
                raise HTTPException(status_code=500, detail="Quét lead thất bại. Vui lòng thử lại.") from exc

            if required > 0 and scan.status in ("completed", "empty"):
                balance_after = consume_credits(
                    db,
                    user_id=user.id,
                    amount=required,
                    reason="lead_map_basic_scan",
                    note=f"scan_id={scan.id} api_calls={usage.total}",
                )
                scan.credits_charged = required
            else:
                balance_after = get_available_balance(db, user.id)

            if scan.status in ("completed", "empty"):
                from app.services.plan_quota_registry import feature_key_for
                from app.services.plan_quota_service import record_quota_usage

                record_quota_usage(
                    db,
                    user.id,
                    feature_key_for("lead_scan"),
                    quantity=1,
                    credits_used=required if required > 0 else 0,
                )

            db.commit()
            db.refresh(scan)
            out = _response_from_scan(db, scan, from_cache=False)
            out["balance_after"] = balance_after
            return out


def quote_lead_detail_for_user(db: Session, user_id: int, count: int = 1) -> dict[str, Any]:
    return quote_lead_detail(count)


def fetch_lead_detail(
    db: Session,
    user: User,
    scan_id: int,
    lead_id: int,
    *,
    client_ip: str | None = None,
) -> dict[str, Any]:
    _ensure_feature_ready()
    check_user_rate_limit(user.id)
    check_ip_rate_limit(client_ip)

    scan = (
        db.query(GbpLeadScan)
        .filter(GbpLeadScan.id == scan_id, GbpLeadScan.user_id == user.id)
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt quét.")
    lead = (
        db.query(GbpLead)
        .filter(GbpLead.id == lead_id, GbpLead.scan_id == scan_id, GbpLead.user_id == user.id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Không tìm thấy lead.")

    if lead.detail_fetched and (lead.phone or lead.website):
        return {"lead": _lead_row_dict(lead), "credits_charged": 0, "from_cache": True}

    required = int(quote_lead_detail(1)["credit_required"])

    from app.services.plan_quota_registry import feature_key_for
    from app.services.plan_quota_service import assert_quota_available, record_quota_usage

    assert_quota_available(db, user, feature_key_for("lead_detail"), units=1)

    gate_req = CostGateRequest(
        db=db,
        user=user,
        provider=ExternalApiProvider.GOOGLE_PLACES,
        action="lead_detail",
        credit_cost=required,
        feature_key=feature_key_for("lead_detail"),
        quota_units=1,
        require_paid_plan=True,
        single_flight_key=f"lead_detail:{user.id}:{lead_id}",
        cooldown_key=f"google_places:{user.id}",
        cooldown_message="Google Places API tạm thời bị giới hạn. Vui lòng thử lại sau vài phút.",
        rate_limit_per_min=lead_user_rate_limit_per_min(),
    )

    with cost_gate_session(gate_req):
        ensure_google_api_allowed(user.id, action="lead_detail")
        usage = ApiUsage()
        try:
            detail = get_place_contact_details(lead.place_id, usage)
        except PlacesApiError as exc:
            _log_api_error(db, user_id=user.id, scan_id=scan_id, exc=exc, params={"place_id": lead.place_id})
            if exc.code == "quota_exceeded":
                mark_google_cooldown(user.id)
            code = status.HTTP_429_TOO_MANY_REQUESTS if exc.code == "quota_exceeded" else status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message}) from exc

        lead.phone = detail.get("phone") or lead.phone
        lead.website = detail.get("website") or lead.website
        lead.maps_url = detail.get("maps_url") or lead.maps_url
        lead.detail_fetched = True
        lead.data_source = "detail"
        scan.detail_request_count = int(scan.detail_request_count or 0) + usage.detail_requests
        scan.api_request_count = int(scan.api_request_count or 0) + usage.total

        balance_after = get_available_balance(db, user.id)
        if required > 0:
            balance_after = consume_credits(
                db,
                user_id=user.id,
                amount=required,
                reason="lead_map_place_detail",
                note=f"scan_id={scan_id} lead_id={lead_id}",
            )
            scan.credits_charged = int(scan.credits_charged or 0) + required

        record_quota_usage(
            db,
            user.id,
            feature_key_for("lead_detail"),
            quantity=1,
            credits_used=required,
        )
        db.commit()
        db.refresh(lead)
        return {
            "lead": _lead_row_dict(lead),
            "credits_charged": required,
            "balance_after": balance_after,
            "from_cache": False,
        }


def _leads_for_scan(db: Session, scan_id: int) -> list[GbpLead]:
    return (
        db.query(GbpLead)
        .filter(GbpLead.scan_id == scan_id)
        .order_by(GbpLead.id.asc())
        .all()
    )


def list_scan_history(db: Session, user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = (
        db.query(GbpLeadScan)
        .filter(GbpLeadScan.user_id == user_id)
        .order_by(GbpLeadScan.created_at.desc())
        .limit(max(1, min(100, int(limit))))
        .all()
    )
    return [_scan_summary(r) for r in rows]


def get_scan_detail(
    db: Session,
    user_id: int,
    scan_id: int,
    *,
    filt: str | None = None,
) -> dict[str, Any]:
    scan = (
        db.query(GbpLeadScan)
        .filter(GbpLeadScan.id == scan_id, GbpLeadScan.user_id == user_id)
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch sử quét.")
    leads = [_lead_row_dict(l) for l in _leads_for_scan(db, scan.id)]
    leads = _apply_filter(leads, filt)
    for i, row in enumerate(leads):
        row["index"] = i + 1
    return {
        "scan": _scan_summary(scan),
        "leads": leads,
        "filter": filt or "",
        "from_cache": scan.data_source == "cache",
    }


def _export_rows(leads: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for lead in leads:
        rows.append(
            [
                lead.get("index"),
                lead.get("name") or "",
                lead.get("phone") or "",
                lead.get("address") or "",
                lead.get("website") or "",
                lead.get("rating") if lead.get("rating") is not None else "",
                lead.get("review_count") if lead.get("review_count") is not None else "",
                lead.get("category") or "",
                lead.get("maps_url") or "",
                lead.get("lead_status_label") or LEAD_STATUS_LABELS.get("new"),
                lead.get("place_id") or "",
            ]
        )
    return rows


def export_scan(
    db: Session,
    user: User,
    scan_id: int,
    *,
    fmt: str = "csv",
    filt: str | None = None,
) -> tuple[bytes, str, str]:
    detail = get_scan_detail(db, user.id, scan_id, filt=filt)
    leads = detail.get("leads") or []
    export_cost = cost_lead_export()
    if export_cost > 0 and credits_enforced():
        balance, sufficient = ensure_sufficient_credits(db, user.id, export_cost)
        if not sufficient:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "insufficient_credits",
                    "message": f"Không đủ credit để xuất file. Cần {export_cost}, còn {balance}.",
                    "credit_required": export_cost,
                    "upgrade_required": True,
                    "upgrade_url": "/pricing",
                },
            )
        consume_credits(
            db,
            user_id=user.id,
            amount=export_cost,
            reason="lead_map_export",
            note=f"scan_id={scan_id} format={fmt}",
        )
        db.commit()

    safe = f"lead-scan-{scan_id}"
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Leads"
        ws.append(_EXPORT_HEADERS)
        for row in _export_rows(leads):
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{safe}.xlsx"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_EXPORT_HEADERS)
    for row in _export_rows(leads):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"{safe}.csv"


def admin_usage_stats(db: Session) -> dict[str, Any]:
    now = _utc_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    day_scans = int(db.query(func.count(GbpLeadScan.id)).filter(GbpLeadScan.created_at >= day_start).scalar() or 0)
    month_scans = int(db.query(func.count(GbpLeadScan.id)).filter(GbpLeadScan.created_at >= month_start).scalar() or 0)
    day_api = int(
        db.query(func.coalesce(func.sum(GbpLeadScan.api_request_count), 0))
        .filter(GbpLeadScan.created_at >= day_start)
        .scalar()
        or 0
    )
    month_api = int(
        db.query(func.coalesce(func.sum(GbpLeadScan.api_request_count), 0))
        .filter(GbpLeadScan.created_at >= month_start)
        .scalar()
        or 0
    )
    costs = lead_api_cost_estimate_usd()
    est_day = day_api * costs["search_page"] * 0.3 + day_api * costs["place_detail"] * 0.1
    est_month = month_api * costs["search_page"] * 0.3 + month_api * costs["place_detail"] * 0.1
    from app.core.lead_scanner_settings import admin_snapshot, lead_cost_alert_daily_usd, lead_cost_alert_monthly_usd

    return {
        "config": admin_snapshot(),
        "plan_limits": plan_limits(),
        "usage": {
            "scans_today": day_scans,
            "scans_month": month_scans,
            "api_requests_today": day_api,
            "api_requests_month": month_api,
            "estimated_cost_usd_today": round(est_day, 4),
            "estimated_cost_usd_month": round(est_month, 4),
            "alert_daily_usd": lead_cost_alert_daily_usd(),
            "alert_monthly_usd": lead_cost_alert_monthly_usd(),
            "daily_cost_alert": est_day >= lead_cost_alert_daily_usd(),
            "monthly_cost_alert": est_month >= lead_cost_alert_monthly_usd(),
        },
    }
