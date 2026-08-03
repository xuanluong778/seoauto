"""Admin affiliate management APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.affiliate import AffiliateAccount, AffiliateClick, AffiliateCommission, AffiliatePayout, AffiliateReferral
from app.models.user import User
from app.schemas.affiliate import (
    AffiliateApiResponse,
    AffiliatePayoutPaidBody,
    AffiliateRejectBody,
    AffiliateSettingsBody,
)
from app.services.affiliate_service import (
    _mask_email,
    activate_affiliate_account,
    admin_account_detail,
    admin_overview,
    approve_payout_request,
    approve_commission,
    compute_balances,
    get_settings,
    list_fraud_flags,
    mark_payout_paid,
    migrate_legacy_affiliate_accounts,
    reject_commission,
    reject_payout,
    review_affiliate_account,
    suspend_affiliate_account,
)
from app.services.rbac import require_admin_user

from app.routers.affiliate_api_common import api_ok

router = APIRouter(prefix="/affiliate", tags=["admin-affiliate"])


@router.get("/overview", response_model=AffiliateApiResponse)
def admin_aff_overview(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    return api_ok(admin_overview(db))


@router.get("/accounts", response_model=AffiliateApiResponse)
def admin_aff_accounts(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    migrate_legacy_affiliate_accounts(db)
    db.commit()
    query = db.query(AffiliateAccount).join(User, AffiliateAccount.user_id == User.id)
    if status:
        query = query.filter(AffiliateAccount.status == status.strip())
    if q and q.strip():
        term = q.strip()
        query = query.filter(
            or_(
                User.email.ilike(f"%{term}%"),
                AffiliateAccount.referral_code.ilike(f"%{term.upper()}%"),
            )
        )
    total = query.count()
    rows = query.order_by(desc(AffiliateAccount.created_at)).offset(offset).limit(limit).all()
    items = []
    for acc in rows:
        user = db.query(User).filter(User.id == acc.user_id).one_or_none()
        clicks = db.query(func.count(AffiliateClick.id)).filter(AffiliateClick.affiliate_id == acc.id).scalar() or 0
        signups = db.query(func.count(AffiliateReferral.id)).filter(AffiliateReferral.affiliate_id == acc.id).scalar() or 0
        paid_users = (
            db.query(func.count(AffiliateReferral.id))
            .filter(AffiliateReferral.affiliate_id == acc.id, AffiliateReferral.status == "paid")
            .scalar()
            or 0
        )
        total_comm = (
            db.query(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0))
            .filter(AffiliateCommission.affiliate_id == acc.id, AffiliateCommission.status.in_(("pending", "approved", "paid")))
            .scalar()
            or 0
        )
        items.append(
            {
                "id": acc.id,
                "user_id": acc.user_id,
                "email": user.email if user else None,
                "referral_code": acc.referral_code,
                "status": acc.status,
                "fraud_flag": bool(acc.fraud_flag),
                "fraud_note": acc.fraud_note,
                "clicks": int(clicks),
                "signups": int(signups),
                "paid_users": int(paid_users),
                "total_commission": int(total_comm),
                "created_at": acc.created_at.isoformat() if acc.created_at else None,
            }
        )
    return api_ok({"items": items, "total": int(total), "limit": limit, "offset": offset})


@router.get("/accounts/{account_id}", response_model=AffiliateApiResponse)
def admin_aff_account_detail(
    account_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    return api_ok(admin_account_detail(db, account_id))


@router.post("/accounts/{account_id}/activate", response_model=AffiliateApiResponse)
def admin_activate_account(
    account_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    acc = activate_affiliate_account(db, account_id)
    db.commit()
    return api_ok({"id": acc.id, "status": acc.status}, message="Đã mở khóa affiliate.")


@router.post("/accounts/{account_id}/review", response_model=AffiliateApiResponse)
def admin_review_account(
    account_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    acc = review_affiliate_account(db, account_id)
    db.commit()
    return api_ok({"id": acc.id, "status": acc.status}, message="Đã chuyển affiliate sang cần xem xét.")


@router.post("/accounts/{account_id}/suspend", response_model=AffiliateApiResponse)
def admin_suspend_account(
    account_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    acc = suspend_affiliate_account(db, account_id)
    db.commit()
    return api_ok({"id": acc.id, "status": acc.status}, message="Đã khóa affiliate.")


@router.get("/commissions", response_model=AffiliateApiResponse)
def admin_commissions(
    status: str | None = Query(default="pending"),
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    query = db.query(AffiliateCommission)
    if status:
        query = query.filter(AffiliateCommission.status == status.strip())
    if q and q.strip():
        term = q.strip().lower()
        aff_ids = [
            a.id
            for a in db.query(AffiliateAccount)
            .join(User, AffiliateAccount.user_id == User.id)
            .filter(or_(User.email.ilike(f"%{term}%"), AffiliateAccount.referral_code.ilike(f"%{term.upper()}%")))
            .all()
        ]
        if aff_ids:
            query = query.filter(AffiliateCommission.affiliate_id.in_(aff_ids))
        else:
            query = query.filter(AffiliateCommission.id == -1)
    total = query.count()
    rows = query.order_by(desc(AffiliateCommission.created_at)).offset(offset).limit(limit).all()
    items = []
    for c in rows:
        aff = db.query(AffiliateAccount).filter(AffiliateAccount.id == c.affiliate_id).one_or_none()
        aff_user = db.query(User).filter(User.id == aff.user_id).one_or_none() if aff else None
        cust = db.query(User).filter(User.id == c.referred_user_id).one_or_none()
        items.append(
            {
                "id": c.id,
                "affiliate_email": aff_user.email if aff_user else None,
                "customer_email": (cust.email if cust else None),
                "customer_masked": _mask_email(cust.email if cust else ""),
                "order_id": c.order_id,
                "order_amount": c.order_amount,
                "commission_rate": c.commission_rate,
                "commission_amount": c.commission_amount,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "note": c.rejected_reason,
            }
        )
    return api_ok({"items": items, "total": int(total), "limit": limit, "offset": offset})


@router.post("/commissions/{commission_id}/approve", response_model=AffiliateApiResponse)
def admin_approve_commission(
    commission_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    comm = approve_commission(db, commission_id)
    balances = compute_balances(db, int(comm.affiliate_id))
    db.commit()
    return api_ok(
        {
            "id": comm.id,
            "status": comm.status,
            "hold_until": None,
            "balances": balances,
        },
        message="Đã duyệt hoa hồng.",
    )


@router.post("/commissions/{commission_id}/reject", response_model=AffiliateApiResponse)
def admin_reject_commission(
    commission_id: int,
    body: AffiliateRejectBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    comm = reject_commission(db, commission_id, body.reason)
    db.commit()
    return api_ok({"id": comm.id, "status": comm.status}, message="Đã từ chối hoa hồng.")


@router.get("/payouts", response_model=AffiliateApiResponse)
def admin_payouts(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    query = db.query(AffiliatePayout).join(AffiliateAccount, AffiliatePayout.affiliate_id == AffiliateAccount.id)
    if status:
        query = query.filter(AffiliatePayout.status == status.strip())
    if q and q.strip():
        term = q.strip()
        query = query.join(User, AffiliateAccount.user_id == User.id).filter(
            or_(
                User.email.ilike(f"%{term}%"),
                AffiliateAccount.referral_code.ilike(f"%{term.upper()}%"),
            )
        )
    total = query.count()
    rows = query.order_by(desc(AffiliatePayout.requested_at)).offset(offset).limit(limit).all()
    items = []
    for p in rows:
        acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == p.affiliate_id).one_or_none()
        user = db.query(User).filter(User.id == acc.user_id).one_or_none() if acc else None
        items.append(
            {
                "id": p.id,
                "affiliate_email": user.email if user else None,
                "amount": p.amount,
                "status": p.status,
                "bank_name": acc.bank_name if acc else None,
                "bank_account_name": acc.bank_account_name if acc else None,
                "bank_account_number": acc.bank_account_number if acc else None,
                "requested_at": p.requested_at.isoformat() if p.requested_at else None,
                "transaction_ref": p.transaction_ref,
                "note": p.note,
            }
        )
    return api_ok({"items": items, "total": int(total), "limit": limit, "offset": offset})


@router.post("/payouts/{payout_id}/approve", response_model=AffiliateApiResponse)
def admin_approve_payout(
    payout_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    payout = approve_payout_request(db, payout_id)
    db.commit()
    return api_ok({"id": payout.id, "status": payout.status}, message="Đã duyệt yêu cầu rút tiền.")


@router.post("/payouts/{payout_id}/mark-paid", response_model=AffiliateApiResponse)
def admin_mark_payout_paid(
    payout_id: int,
    body: AffiliatePayoutPaidBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    payout = mark_payout_paid(db, payout_id, body.transaction_ref, body.note)
    db.commit()
    return api_ok({"id": payout.id, "status": payout.status}, message="Đã đánh dấu đã thanh toán.")


@router.post("/payouts/{payout_id}/reject", response_model=AffiliateApiResponse)
def admin_reject_payout(
    payout_id: int,
    body: AffiliateRejectBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    payout = reject_payout(db, payout_id, body.reason)
    db.commit()
    return api_ok({"id": payout.id, "status": payout.status}, message="Đã từ chối yêu cầu rút tiền.")


@router.get("/fraud-flags", response_model=AffiliateApiResponse)
def admin_fraud_flags(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    items = list_fraud_flags(db)
    total = len(items)
    page = items[offset : offset + limit]
    return api_ok({"items": page, "total": total, "limit": limit, "offset": offset})


@router.get("/settings", response_model=AffiliateApiResponse)
def admin_get_settings(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    s = get_settings(db)
    return api_ok(
        {
            "default_commission_rate": s.default_commission_rate,
            "cookie_days": s.cookie_days,
            "min_payout_amount": s.min_payout_amount,
            "commission_hold_days": s.commission_hold_days,
            "auto_approve_commissions": bool(s.auto_approve_commissions),
        }
    )


@router.put("/settings", response_model=AffiliateApiResponse)
def admin_put_settings(
    body: AffiliateSettingsBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> AffiliateApiResponse:
    s = get_settings(db)
    s.default_commission_rate = body.default_commission_rate
    s.cookie_days = body.cookie_days
    s.min_payout_amount = body.min_payout_amount
    s.commission_hold_days = body.commission_hold_days
    s.auto_approve_commissions = body.auto_approve_commissions
    db.commit()
    return api_ok(message="Đã lưu cài đặt affiliate.")
