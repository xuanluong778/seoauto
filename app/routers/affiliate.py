"""User-facing affiliate APIs + click tracking."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.routers.affiliate_api_common import api_fail, api_ok
from app.schemas.affiliate import (
    AffiliateApiResponse,
    AffiliatePayoutInfoBody,
    AffiliatePayoutRequestBody,
    AffiliateRegisterBody,
    AffiliateTrackClickBody,
)
from app.services.affiliate_service import (
    AFFILIATE_CLICK_COOKIE,
    AFFILIATE_COOKIE,
    build_overview,
    build_referral_link,
    commission_rows_for_user,
    count_commissions_for_user,
    count_payouts_for_user,
    count_referrals_for_user,
    get_account_by_user,
    migrate_legacy_affiliate_accounts,
    payout_rows_for_user,
    referral_rows_for_user,
    register_affiliate,
    request_payout,
    sign_affiliate_cookie,
    track_click,
    update_payout_info,
)
from app.services.admin_auth import is_platform_admin_email
from app.services.auth import get_current_user, get_optional_current_user

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


@router.get("/overview", response_model=AffiliateApiResponse)
def affiliate_overview(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    migrate_legacy_affiliate_accounts(db)
    db.commit()
    data = build_overview(db, user, request)
    data["show_admin_registrations"] = is_platform_admin_email(str(getattr(user, "email", "") or ""))
    return api_ok(data)


@router.post("/register", response_model=AffiliateApiResponse)
def affiliate_register(
    _body: AffiliateRegisterBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    existing = get_account_by_user(db, user.id)
    acc = register_affiliate(db, user)
    db.commit()
    if existing:
        msg = "Bạn đã đăng ký affiliate trước đó."
    else:
        msg = "Đã đăng ký affiliate. Tài khoản đã được kích hoạt."
    return api_ok(
        {
            "id": acc.id,
            "referral_code": acc.referral_code,
            "status": acc.status,
            "commission_rate": acc.commission_rate,
            "already_registered": existing is not None,
        },
        message=msg,
    )


@router.get("/referral-link", response_model=AffiliateApiResponse)
def affiliate_referral_link(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse | JSONResponse:
    acc = get_account_by_user(db, user.id)
    if acc is None:
        return api_fail("Chưa đăng ký affiliate.", "not_registered", status_code=404)
    return api_ok(
        {
            "referral_code": acc.referral_code,
            "referral_link": build_referral_link(request, acc.referral_code),
            "status": acc.status,
        }
    )


@router.get("/referrals", response_model=AffiliateApiResponse)
def affiliate_referrals(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    acc = get_account_by_user(db, user.id)
    if acc is None:
        return api_ok({"items": [], "total": 0, "limit": limit, "offset": offset})
    total = count_referrals_for_user(db, acc.id)
    items = referral_rows_for_user(db, acc.id, limit=limit, offset=offset)
    return api_ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/commissions", response_model=AffiliateApiResponse)
def affiliate_commissions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    acc = get_account_by_user(db, user.id)
    if acc is None:
        return api_ok({"items": [], "total": 0, "limit": limit, "offset": offset})
    total = count_commissions_for_user(db, acc.id)
    items = commission_rows_for_user(db, acc.id, limit=limit, offset=offset)
    return api_ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/payouts", response_model=AffiliateApiResponse)
def affiliate_payouts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    acc = get_account_by_user(db, user.id)
    if acc is None:
        return api_ok({"items": [], "total": 0, "limit": limit, "offset": offset})
    total = count_payouts_for_user(db, acc.id)
    items = payout_rows_for_user(db, acc.id, limit=limit, offset=offset)
    return api_ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.post("/payout-request", response_model=AffiliateApiResponse)
def affiliate_payout_request(
    body: AffiliatePayoutRequestBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    payout = request_payout(db, user, body.amount)
    db.commit()
    return api_ok(
        {"id": payout.id, "amount": payout.amount, "status": payout.status},
        message="Đã gửi yêu cầu rút tiền.",
    )


@router.put("/payout-info", response_model=AffiliateApiResponse)
def affiliate_payout_info(
    body: AffiliatePayoutInfoBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AffiliateApiResponse:
    acc = update_payout_info(db, user, body.model_dump())
    db.commit()
    return api_ok(
        {
            "payout_method": acc.payout_method,
            "bank_name": acc.bank_name,
            "bank_account_name": acc.bank_account_name,
        },
        message="Đã lưu thông tin thanh toán.",
    )


@router.post("/track-click", response_model=AffiliateApiResponse)
def affiliate_track_click(
    body: AffiliateTrackClickBody,
    request: Request,
    db: Session = Depends(get_db),
    _user: User | None = Depends(get_optional_current_user),
) -> JSONResponse:
    result = track_click(
        db,
        referral_code=body.referral_code,
        request=request,
        landing_page=body.landing_page,
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign,
    )
    if result is None:
        return api_fail("Mã giới thiệu không hợp lệ.", "invalid_code", status_code=400)
    db.commit()
    payload = api_ok(result, message="Đã ghi nhận click.")
    response = JSONResponse(content=payload.model_dump())
    set_referral_cookies(response, result, request=request)
    return response


def set_referral_cookies(response, result: dict, request: Request | None = None) -> None:
    days = int(result.get("cookie_days") or 60)
    max_age = days * 86400
    code = str(result.get("referral_code") or "")
    click_id_raw = result.get("click_id")
    click_id = int(click_id_raw) if click_id_raw is not None else None
    token = sign_affiliate_cookie(referral_code=code, click_id=click_id, cookie_days=days)
    secure = False
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip().lower()
        secure = proto == "https"
    response.set_cookie(
        AFFILIATE_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    if click_id is not None:
        response.set_cookie(
            AFFILIATE_CLICK_COOKIE,
            token,
            max_age=max_age,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )
