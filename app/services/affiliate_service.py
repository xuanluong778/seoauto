"""Affiliate program business logic."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY
from app.models.affiliate import (
    AffiliateAccount,
    AffiliateAdjustment,
    AffiliateClick,
    AffiliateCommission,
    AffiliatePayout,
    AffiliateReferral,
    AffiliateSettings,
)
from app.models.payment_transaction import PaymentTransaction
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User

AFFILIATE_COOKIE = "seo_aff_ref"
AFFILIATE_CLICK_COOKIE = "seo_aff_click_id"
REFERRAL_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,32}$")
AFFILIATE_ACCOUNT_STATUSES = frozenset({"active", "review", "suspended"})
AFFILIATE_TRACKING_STATUSES = ("active", "review")
_LOG = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_value(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sign_affiliate_cookie(*, referral_code: str, click_id: int | None, cookie_days: int) -> str:
    """Signed cookie payload — prevents forged referral attribution."""
    days = max(1, int(cookie_days or 60))
    expire = _utcnow() + timedelta(days=days)
    payload = {
        "typ": "aff_ref",
        "code": str(referral_code or "").strip().upper(),
        "cid": int(click_id) if click_id else None,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_affiliate_cookie(raw: str | None) -> dict[str, Any] | None:
    token = str(raw or "").strip()
    if not token:
        return None
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if data.get("typ") != "aff_ref":
        return None
    code = str(data.get("code") or "").strip().upper()
    if not REFERRAL_CODE_RE.match(code):
        return None
    cid = data.get("cid")
    click_id = int(cid) if cid is not None else None
    return {"referral_code": code, "click_id": click_id}


def _mask_email(email: str) -> str:
    e = str(email or "").strip()
    if "@" not in e:
        return "***"
    local, domain = e.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def _gen_referral_code(db: Session) -> str:
    for _ in range(20):
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
        if not db.query(AffiliateAccount).filter(AffiliateAccount.referral_code == code).first():
            return code
    raise HTTPException(status_code=500, detail="Không tạo được mã giới thiệu, thử lại.")


def get_settings(db: Session) -> AffiliateSettings:
    row = db.query(AffiliateSettings).order_by(AffiliateSettings.id.asc()).first()
    if row is None:
        row = AffiliateSettings()
        db.add(row)
        db.flush()
    return row


def get_account_by_user(db: Session, user_id: int) -> AffiliateAccount | None:
    return db.query(AffiliateAccount).filter(AffiliateAccount.user_id == int(user_id)).one_or_none()


def get_account_by_code(db: Session, code: str, *, for_tracking: bool = False) -> AffiliateAccount | None:
    c = str(code or "").strip().upper()
    if not c:
        return None
    q = db.query(AffiliateAccount).filter(AffiliateAccount.referral_code == c)
    if for_tracking:
        q = q.filter(AffiliateAccount.status.in_(AFFILIATE_TRACKING_STATUSES))
    else:
        q = q.filter(AffiliateAccount.status == "active")
    return q.one_or_none()


def migrate_legacy_affiliate_accounts(db: Session) -> int:
    """Chuyển tài khoản affiliate legacy pending → active."""
    rows = db.query(AffiliateAccount).filter(AffiliateAccount.status == "pending").all()
    if not rows:
        return 0
    now = _utcnow()
    for acc in rows:
        acc.status = "active"
        acc.updated_at = now
    db.flush()
    return len(rows)


def register_affiliate(db: Session, user: User) -> AffiliateAccount:
    existing = get_account_by_user(db, user.id)
    if existing:
        if existing.status == "pending":
            existing.status = "active"
            existing.updated_at = _utcnow()
            db.flush()
        return existing
    settings = get_settings(db)
    acc = AffiliateAccount(
        user_id=user.id,
        referral_code=_gen_referral_code(db),
        status="active",
        commission_rate=int(settings.default_commission_rate or 30),
        cookie_days=int(settings.cookie_days or 60),
        payout_method="bank",
    )
    db.add(acc)
    db.flush()
    return acc


def update_payout_info(db: Session, user: User, payload: dict[str, Any]) -> AffiliateAccount:
    acc = get_account_by_user(db, user.id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Chưa đăng ký affiliate.")
    bank_name = str(payload.get("bank_name") or "").strip()
    bank_account_name = str(payload.get("bank_account_name") or "").strip()
    bank_account_number = str(payload.get("bank_account_number") or "").strip()
    payout_method = str(payload.get("payout_method") or "bank").strip() or "bank"
    if bank_name:
        acc.bank_name = bank_name
    if bank_account_name:
        acc.bank_account_name = bank_account_name
    if bank_account_number:
        acc.bank_account_number = bank_account_number
    acc.payout_method = payout_method
    acc.updated_at = _utcnow()
    db.flush()
    return acc


def build_referral_link(request: Request | None, code: str) -> str:
    base = ""
    if request is not None:
        base = str(request.base_url).rstrip("/")
    if not base:
        base = "https://seoauto.vn"
    return f"{base}/?ref={code}"


def track_click(
    db: Session,
    *,
    referral_code: str,
    request: Request,
    landing_page: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
) -> dict[str, Any] | None:
    code = str(referral_code or "").strip().upper()
    if not REFERRAL_CODE_RE.match(code):
        return None
    acc = get_account_by_code(db, code, for_tracking=True)
    if acc is None:
        return None
    settings = get_settings(db)
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent") or ""
    click = AffiliateClick(
        affiliate_id=acc.id,
        referral_code=code,
        landing_page=(landing_page or str(request.url))[:512],
        ip_hash=_hash_value(ip) if ip else None,
        user_agent_hash=_hash_value(ua) if ua else None,
        utm_source=(utm_source or request.query_params.get("utm_source") or "")[:128] or None,
        utm_medium=(utm_medium or request.query_params.get("utm_medium") or "")[:128] or None,
        utm_campaign=(utm_campaign or request.query_params.get("utm_campaign") or "")[:128] or None,
    )
    db.add(click)
    db.flush()
    if click.ip_hash:
        _check_fraud_ip_overlap(db, acc.id, click.ip_hash)
    return {
        "click_id": click.id,
        "referral_code": code,
        "cookie_days": int(acc.cookie_days or settings.cookie_days or 60),
        "affiliate_id": acc.id,
    }


def try_attach_referral_from_request(request: Request, user: User, db: Session) -> AffiliateReferral | None:
    """Đọc cookie referral đã ký và gắn affiliate_referrals (không ghi đè nếu đã có)."""
    parsed = verify_affiliate_cookie(request.cookies.get(AFFILIATE_COOKIE))
    if parsed is None:
        return None
    try:
        ref = attach_referral_from_cookie(
            db,
            user=user,
            referral_code=parsed.get("referral_code"),
            click_id=parsed.get("click_id"),
        )
        if ref is not None:
            db.commit()
        return ref
    except Exception:
        db.rollback()
        return None


def attach_referral_from_cookie(db: Session, *, user: User, referral_code: str | None, click_id: int | None) -> AffiliateReferral | None:
    code = str(referral_code or "").strip().upper()
    if not code:
        return None
    acc = get_account_by_code(db, code, for_tracking=True)
    if acc is None:
        return None
    if int(acc.user_id) == int(user.id):
        return None
    # Click must belong to this referral code when provided.
    if click_id is not None:
        click = db.query(AffiliateClick).filter(AffiliateClick.id == int(click_id)).one_or_none()
        if click is None:
            return None
        if int(click.affiliate_id) != int(acc.id):
            return None
        if str(click.referral_code or "").strip().upper() != code:
            return None
    existing = db.query(AffiliateReferral).filter(AffiliateReferral.referred_user_id == user.id).one_or_none()
    if existing is not None:
        return existing
    ref = AffiliateReferral(
        affiliate_id=acc.id,
        referred_user_id=user.id,
        first_click_id=int(click_id) if click_id else None,
        status="registered",
        registered_at=_utcnow(),
    )
    db.add(ref)
    db.flush()
    if click_id:
        click = db.query(AffiliateClick).filter(AffiliateClick.id == int(click_id)).one_or_none()
        if click and click.ip_hash:
            _check_fraud_ip_overlap(db, acc.id, click.ip_hash)
    _check_fraud_signup_ratio(db, acc.id)
    return ref


def _commission_idempotency_key(*, payment_transaction_id: int | None, subscription_id: int | None) -> str | None:
    if payment_transaction_id:
        return f"ptx:{int(payment_transaction_id)}"
    if subscription_id:
        return f"sub:{int(subscription_id)}"
    return None


def record_commission_for_payment(
    db: Session,
    *,
    user_id: int,
    order_amount: int,
    payment_transaction_id: int | None = None,
    subscription_id: int | None = None,
    invoice_id: str | None = None,
) -> AffiliateCommission | None:
    """Tạo hoa hồng từ *order_amount* — phải là doanh thu thực nhận sau giảm giá."""
    if order_amount <= 0:
        return None
    idem_key = _commission_idempotency_key(
        payment_transaction_id=payment_transaction_id,
        subscription_id=subscription_id,
    )
    if not idem_key:
        _LOG.warning("affiliate commission skipped: missing payment/subscription id user_id=%s", user_id)
        return None
    existing = (
        db.query(AffiliateCommission)
        .filter(AffiliateCommission.idempotency_key == idem_key)
        .one_or_none()
    )
    if existing is not None:
        return existing

    ref = db.query(AffiliateReferral).filter(AffiliateReferral.referred_user_id == int(user_id)).one_or_none()
    if ref is None or ref.status == "cancelled":
        return None
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == ref.affiliate_id).one_or_none()
    if acc is None or acc.status != "active":
        return None
    if int(acc.user_id) == int(user_id):
        return None

    settings = get_settings(db)
    rate = int(acc.commission_rate or settings.default_commission_rate or 30)
    commission_amount = int(round(order_amount * rate / 100))
    hold_days = int(settings.commission_hold_days or 0)
    hold_until = _utcnow() + timedelta(days=hold_days) if hold_days > 0 else None
    can_auto = bool(settings.auto_approve_commissions) and (hold_until is None or hold_until <= _utcnow())
    st = "approved" if can_auto else "pending"
    order_key = str(payment_transaction_id or subscription_id or "")
    comm = AffiliateCommission(
        affiliate_id=acc.id,
        referred_user_id=int(user_id),
        order_id=order_key or None,
        idempotency_key=idem_key,
        invoice_id=invoice_id,
        subscription_id=subscription_id,
        order_amount=int(order_amount),
        commission_rate=rate,
        commission_amount=commission_amount,
        paid_amount=0,
        status=st,
        hold_until=hold_until,
        approved_at=_utcnow() if st == "approved" else None,
    )
    db.add(comm)
    if ref.status == "registered":
        ref.status = "paid"
        ref.first_paid_at = _utcnow()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        dup = (
            db.query(AffiliateCommission)
            .filter(AffiliateCommission.idempotency_key == idem_key)
            .one_or_none()
        )
        return dup
    return comm


def _create_refund_adjustment(
    db: Session,
    *,
    commission: AffiliateCommission,
    idem_key: str,
) -> AffiliateAdjustment | None:
    existing = (
        db.query(AffiliateAdjustment)
        .filter(AffiliateAdjustment.idempotency_key == idem_key)
        .one_or_none()
    )
    if existing is not None:
        return existing
    paid_out = int(commission.paid_amount or 0)
    if commission.status == "paid":
        paid_out = max(paid_out, int(commission.commission_amount or 0))
    if paid_out <= 0:
        return None
    adj = AffiliateAdjustment(
        affiliate_id=int(commission.affiliate_id),
        commission_id=int(commission.id),
        amount=paid_out,
        reason="refund_after_paid",
        order_id=commission.order_id,
        idempotency_key=idem_key,
        status="open",
    )
    db.add(adj)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        return (
            db.query(AffiliateAdjustment)
            .filter(AffiliateAdjustment.idempotency_key == idem_key)
            .one_or_none()
        )
    return adj


def cancel_commission_for_refund(
    db: Session,
    *,
    payment_transaction_id: int | None = None,
    subscription_id: int | None = None,
) -> int:
    """Cancel pending/approved commissions; claw back paid ones via open debt adjustments."""
    idem_key = _commission_idempotency_key(
        payment_transaction_id=payment_transaction_id,
        subscription_id=subscription_id,
    )
    q = db.query(AffiliateCommission)
    if payment_transaction_id:
        q = q.filter(AffiliateCommission.order_id == str(payment_transaction_id))
    elif subscription_id:
        q = q.filter(AffiliateCommission.subscription_id == int(subscription_id))
    else:
        return 0
    n = 0
    affiliate_ids: set[int] = set()
    for row in q.all():
        if row.status in ("pending", "approved"):
            row.status = "cancelled"
            row.updated_at = _utcnow()
            affiliate_ids.add(int(row.affiliate_id))
            n += 1
        elif row.status == "paid" or int(row.paid_amount or 0) > 0:
            adj_key = f"refund:{idem_key or row.idempotency_key or row.id}"
            if _create_refund_adjustment(db, commission=row, idem_key=adj_key) is not None:
                affiliate_ids.add(int(row.affiliate_id))
                n += 1
    for aid in affiliate_ids:
        _check_fraud_refund_ratio(db, aid)
    return n


def release_held_commissions(db: Session) -> int:
    """Move pending commissions past hold_until to approved."""
    now = _utcnow()
    rows = (
        db.query(AffiliateCommission)
        .filter(
            AffiliateCommission.status == "pending",
            AffiliateCommission.hold_until.isnot(None),
            AffiliateCommission.hold_until <= now,
        )
        .all()
    )
    n = 0
    for row in rows:
        row.status = "approved"
        row.approved_at = now
        row.updated_at = now
        n += 1
    if n:
        db.flush()
    return n


def _commission_remaining(comm: AffiliateCommission) -> int:
    return max(0, int(comm.commission_amount or 0) - int(comm.paid_amount or 0))


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sum_approved_withdrawable(db: Session, affiliate_id: int) -> int:
    """Approved commissions eligible for payout (hold period elapsed, unpaid remainder)."""
    now = _utcnow()
    rows = (
        db.query(AffiliateCommission)
        .filter(
            AffiliateCommission.affiliate_id == int(affiliate_id),
            AffiliateCommission.status == "approved",
        )
        .all()
    )
    total = 0
    for c in rows:
        hold_until = _as_utc(c.hold_until)
        if hold_until is not None and hold_until > now:
            continue
        total += _commission_remaining(c)
    return total


def _open_debt(db: Session, affiliate_id: int) -> int:
    val = (
        db.query(func.coalesce(func.sum(AffiliateAdjustment.amount), 0))
        .filter(
            AffiliateAdjustment.affiliate_id == int(affiliate_id),
            AffiliateAdjustment.status == "open",
        )
        .scalar()
    )
    return int(val or 0)


def _sum_commissions(db: Session, affiliate_id: int, statuses: tuple[str, ...]) -> int:
    val = (
        db.query(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0))
        .filter(
            AffiliateCommission.affiliate_id == int(affiliate_id),
            AffiliateCommission.status.in_(statuses),
        )
        .scalar()
    )
    return int(val or 0)


def _payout_reserved(db: Session, affiliate_id: int) -> int:
    val = (
        db.query(func.coalesce(func.sum(AffiliatePayout.amount), 0))
        .filter(
            AffiliatePayout.affiliate_id == int(affiliate_id),
            AffiliatePayout.status.in_(("requested", "processing")),
        )
        .scalar()
    )
    return int(val or 0)


def compute_balances(db: Session, affiliate_id: int) -> dict[str, int]:
    release_held_commissions(db)
    pending = _sum_commissions(db, affiliate_id, ("pending",))
    approved = _sum_approved_withdrawable(db, affiliate_id)
    paid_comm = _sum_commissions(db, affiliate_id, ("paid",))
    reserved = _payout_reserved(db, affiliate_id)
    debt = _open_debt(db, affiliate_id)
    withdrawable = max(0, approved - reserved - debt)
    approved_total = _sum_commissions(db, affiliate_id, ("approved",))
    return {
        "pending": pending,
        "approved": approved_total,
        "withdrawable": withdrawable,
        "paid": paid_comm,
        "reserved": reserved,
        "debt": debt,
    }


def build_overview(db: Session, user: User, request: Request | None = None) -> dict[str, Any]:
    acc = get_account_by_user(db, user.id)
    settings = get_settings(db)
    if acc is None:
        return {
            "registered": False,
            "status": None,
            "referral_code": None,
            "referral_link": None,
            "commission_rate": settings.default_commission_rate,
            "cookie_days": settings.cookie_days,
            "stats": {
                "clicks": 0,
                "signups": 0,
                "paid_users": 0,
                "conversion_rate": 0.0,
            },
            "balances": {"pending": 0, "approved": 0, "withdrawable": 0, "paid": 0, "debt": 0},
            "min_payout_amount": int(settings.min_payout_amount or 0),
        }
    clicks = db.query(func.count(AffiliateClick.id)).filter(AffiliateClick.affiliate_id == acc.id).scalar() or 0
    signups = db.query(func.count(AffiliateReferral.id)).filter(AffiliateReferral.affiliate_id == acc.id).scalar() or 0
    paid_users = (
        db.query(func.count(AffiliateReferral.id))
        .filter(AffiliateReferral.affiliate_id == acc.id, AffiliateReferral.status == "paid")
        .scalar()
        or 0
    )
    conv = round((paid_users / clicks * 100), 2) if clicks else 0.0
    balances = compute_balances(db, acc.id)
    return {
        "registered": True,
        "status": acc.status,
        "referral_code": acc.referral_code,
        "referral_link": build_referral_link(request, acc.referral_code),
        "commission_rate": acc.commission_rate,
        "cookie_days": acc.cookie_days,
        "stats": {
            "clicks": int(clicks),
            "signups": int(signups),
            "paid_users": int(paid_users),
            "conversion_rate": conv,
        },
        "balances": balances,
        "min_payout_amount": int(settings.min_payout_amount or 0),
        "payout_info": {
            "payout_method": acc.payout_method,
            "bank_name": acc.bank_name,
            "bank_account_name": acc.bank_account_name,
            "bank_account_number_masked": _mask_bank(acc.bank_account_number),
            "has_bank_info": bool(acc.bank_name and acc.bank_account_name and acc.bank_account_number),
        },
    }


def _mask_bank(num: str | None) -> str | None:
    s = str(num or "").strip()
    if not s:
        return None
    if len(s) <= 4:
        return "***"
    return "*" * (len(s) - 4) + s[-4:]


def request_payout(db: Session, user: User, amount: int | None = None) -> AffiliatePayout:
    acc = get_account_by_user(db, user.id)
    if acc is None or acc.status != "active":
        raise HTTPException(status_code=400, detail="Tài khoản affiliate chưa active.")
    if not (acc.bank_name and acc.bank_account_name and acc.bank_account_number):
        raise HTTPException(status_code=400, detail="Cập nhật thông tin ngân hàng trước khi rút.")

    # Row lock prevents two concurrent payout requests from sharing the same balance.
    locked = (
        db.execute(
            select(AffiliateAccount)
            .where(AffiliateAccount.id == int(acc.id))
            .with_for_update()
        )
        .scalars()
        .one()
    )
    open_payout = (
        db.query(AffiliatePayout)
        .filter(
            AffiliatePayout.affiliate_id == int(locked.id),
            AffiliatePayout.status.in_(("requested", "processing")),
        )
        .order_by(AffiliatePayout.id.asc())
        .first()
    )
    if open_payout is not None:
        raise HTTPException(
            status_code=400,
            detail="Bạn đã có yêu cầu rút tiền đang chờ xử lý. Vui lòng đợi admin duyệt trước khi gửi thêm.",
        )
    settings = get_settings(db)
    balances = compute_balances(db, locked.id)
    avail = int(balances["withdrawable"])
    req_amount = int(amount) if amount is not None else avail
    min_amount = int(settings.min_payout_amount or 0)
    if req_amount < min_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Số tiền rút tối thiểu là {min_amount:,} VND.",
        )
    if req_amount <= 0 or req_amount > avail:
        raise HTTPException(status_code=400, detail="Số dư khả dụng không đủ.")
    payout = AffiliatePayout(
        affiliate_id=locked.id,
        amount=req_amount,
        status="requested",
        payout_method=locked.payout_method or "bank",
    )
    db.add(payout)
    db.flush()
    return payout


def approve_commission(db: Session, commission_id: int) -> AffiliateCommission:
    """Admin duyệt: pending → approved ngay và được cộng vào số dư có thể rút."""
    comm = (
        db.execute(
            select(AffiliateCommission)
            .where(AffiliateCommission.id == int(commission_id))
            .with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if comm is None:
        raise HTTPException(status_code=404, detail="Commission không tồn tại.")
    if comm.status == "approved":
        return comm
    if comm.status in ("paid", "cancelled", "rejected"):
        raise HTTPException(
            status_code=400,
            detail=f"Không thể duyệt commission trạng thái {comm.status}.",
        )
    if comm.status != "pending":
        raise HTTPException(status_code=400, detail=f"Không thể duyệt commission trạng thái {comm.status}.")
    now = _utcnow()
    # Admin duyệt chủ động: bỏ thời gian giữ để cộng ngay vào withdrawable.
    comm.status = "approved"
    comm.hold_until = None
    comm.approved_at = now
    comm.updated_at = now
    db.flush()
    return comm


def reject_commission(db: Session, commission_id: int, reason: str) -> AffiliateCommission:
    comm = db.query(AffiliateCommission).filter(AffiliateCommission.id == int(commission_id)).one_or_none()
    if comm is None:
        raise HTTPException(status_code=404, detail="Commission không tồn tại.")
    if comm.status in ("paid", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Không thể từ chối commission trạng thái {comm.status}.")
    comm.status = "rejected"
    comm.rejected_reason = str(reason or "").strip()[:500] or "Từ chối bởi admin"
    comm.updated_at = _utcnow()
    db.flush()
    return comm


def approve_payout_request(db: Session, payout_id: int) -> AffiliatePayout:
    payout = db.query(AffiliatePayout).filter(AffiliatePayout.id == int(payout_id)).one_or_none()
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout không tồn tại.")
    if payout.status != "requested":
        raise HTTPException(status_code=400, detail=f"Chỉ duyệt được yêu cầu đang chờ (requested), hiện tại: {payout.status}.")
    payout.status = "processing"
    db.flush()
    return payout


def mark_payout_paid(db: Session, payout_id: int, transaction_ref: str | None, note: str | None) -> AffiliatePayout:
    payout = (
        db.execute(
            select(AffiliatePayout)
            .where(AffiliatePayout.id == int(payout_id))
            .with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout không tồn tại.")
    if payout.status == "paid":
        raise HTTPException(status_code=400, detail="Payout đã thanh toán.")
    if payout.status not in ("processing",):
        raise HTTPException(
            status_code=400,
            detail=f"Chỉ đánh dấu đã thanh toán khi đang xử lý (processing), hiện tại: {payout.status}.",
        )

    db.execute(
        select(AffiliateAccount)
        .where(AffiliateAccount.id == int(payout.affiliate_id))
        .with_for_update()
    )

    now = _utcnow()
    approved_sum = _sum_approved_withdrawable(db, payout.affiliate_id)
    debt = _open_debt(db, payout.affiliate_id)
    if payout.amount > max(0, approved_sum - debt):
        raise HTTPException(status_code=400, detail="Số tiền payout vượt hoa hồng approved khả dụng.")

    remaining = int(payout.amount)
    comms = (
        db.execute(
            select(AffiliateCommission)
            .where(
                AffiliateCommission.affiliate_id == payout.affiliate_id,
                AffiliateCommission.status == "approved",
            )
            .order_by(AffiliateCommission.created_at.asc())
            .with_for_update()
        )
        .scalars()
        .all()
    )
    for c in comms:
        if remaining <= 0:
            break
        hold_until = _as_utc(c.hold_until)
        if hold_until is not None and hold_until > now:
            continue
        rem = _commission_remaining(c)
        if rem <= 0:
            continue
        take = min(rem, remaining)
        c.paid_amount = int(c.paid_amount or 0) + take
        c.updated_at = now
        if _commission_remaining(c) <= 0:
            c.status = "paid"
            c.paid_at = now
        remaining -= take

    if remaining > 0:
        raise HTTPException(
            status_code=400,
            detail="Không phân bổ đủ hoa hồng cho số tiền payout (có thể đã bị rút đồng thời).",
        )

    # Apply open debt against this payout cycle when commissions are exhausted.
    # Debt remains open and continues reducing future withdrawable balances.

    payout.status = "paid"
    payout.transaction_ref = (transaction_ref or "").strip()[:128] or None
    payout.note = (note or "").strip()[:500] or None
    payout.paid_at = now
    db.flush()
    return payout


def activate_affiliate_account(db: Session, account_id: int) -> AffiliateAccount:
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == int(account_id)).one_or_none()
    if acc is None:
        raise HTTPException(status_code=404, detail="Affiliate không tồn tại.")
    acc.status = "active"
    acc.updated_at = _utcnow()
    db.flush()
    return acc


def review_affiliate_account(db: Session, account_id: int) -> AffiliateAccount:
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == int(account_id)).one_or_none()
    if acc is None:
        raise HTTPException(status_code=404, detail="Affiliate không tồn tại.")
    acc.status = "review"
    acc.updated_at = _utcnow()
    db.flush()
    return acc


def suspend_affiliate_account(db: Session, account_id: int) -> AffiliateAccount:
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == int(account_id)).one_or_none()
    if acc is None:
        raise HTTPException(status_code=404, detail="Affiliate không tồn tại.")
    acc.status = "suspended"
    acc.updated_at = _utcnow()
    db.flush()
    return acc


def _check_fraud_signup_ratio(db: Session, affiliate_id: int) -> None:
    signups = db.query(func.count(AffiliateReferral.id)).filter(AffiliateReferral.affiliate_id == affiliate_id).scalar() or 0
    paid = (
        db.query(func.count(AffiliateReferral.id))
        .filter(AffiliateReferral.affiliate_id == affiliate_id, AffiliateReferral.status == "paid")
        .scalar()
        or 0
    )
    if signups >= 10 and paid == 0:
        _flag_fraud(db, affiliate_id, "Nhiều đăng ký nhưng chưa có khách trả phí.")


def _check_fraud_ip_overlap(db: Session, affiliate_id: int, ip_hash: str) -> None:
    if not ip_hash:
        return
    same_ip_signups = (
        db.query(func.count(AffiliateReferral.id))
        .join(AffiliateClick, AffiliateReferral.first_click_id == AffiliateClick.id)
        .filter(
            AffiliateReferral.affiliate_id == int(affiliate_id),
            AffiliateClick.ip_hash == ip_hash,
        )
        .scalar()
        or 0
    )
    if same_ip_signups >= 3:
        _flag_fraud(
            db,
            affiliate_id,
            "Nhiều tài khoản đăng ký trùng IP/thiết bị bất thường.",
        )


def _check_fraud_refund_ratio(db: Session, affiliate_id: int) -> None:
    total = (
        db.query(func.count(AffiliateCommission.id))
        .filter(AffiliateCommission.affiliate_id == int(affiliate_id))
        .scalar()
        or 0
    )
    if total < 5:
        return
    refunds = (
        db.query(func.count(AffiliateCommission.id))
        .filter(
            AffiliateCommission.affiliate_id == int(affiliate_id),
            AffiliateCommission.status == "cancelled",
        )
        .scalar()
        or 0
    )
    if refunds / total >= 0.4:
        _flag_fraud(db, affiliate_id, "Tỷ lệ hoàn tiền/hủy đơn cao bất thường.")


def _flag_fraud(db: Session, affiliate_id: int, note: str) -> None:
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == int(affiliate_id)).one_or_none()
    if acc and not acc.fraud_flag:
        acc.fraud_flag = True
        acc.fraud_note = str(note)[:500]
        if acc.status == "active":
            acc.status = "review"
        acc.updated_at = _utcnow()


def reject_payout(db: Session, payout_id: int, reason: str) -> AffiliatePayout:
    payout = db.query(AffiliatePayout).filter(AffiliatePayout.id == int(payout_id)).one_or_none()
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout không tồn tại.")
    if payout.status == "paid":
        raise HTTPException(status_code=400, detail="Payout đã thanh toán.")
    if payout.status not in ("requested", "processing"):
        raise HTTPException(status_code=400, detail=f"Không thể từ chối payout trạng thái {payout.status}.")
    payout.status = "rejected"
    payout.note = str(reason or "").strip()[:500] or "Từ chối bởi admin"
    db.flush()
    return payout


def list_fraud_flags(db: Session) -> list[dict[str, Any]]:
    rows = db.query(AffiliateAccount).filter(AffiliateAccount.fraud_flag.is_(True)).order_by(desc(AffiliateAccount.updated_at)).all()
    out = []
    for acc in rows:
        user = db.query(User).filter(User.id == acc.user_id).one_or_none()
        signups = db.query(func.count(AffiliateReferral.id)).filter(AffiliateReferral.affiliate_id == acc.id).scalar() or 0
        paid = (
            db.query(func.count(AffiliateReferral.id))
            .filter(AffiliateReferral.affiliate_id == acc.id, AffiliateReferral.status == "paid")
            .scalar()
            or 0
        )
        refunds = (
            db.query(func.count(AffiliateCommission.id))
            .filter(AffiliateCommission.affiliate_id == acc.id, AffiliateCommission.status == "cancelled")
            .scalar()
            or 0
        )
        out.append(
            {
                "affiliate_id": acc.id,
                "user_id": acc.user_id,
                "email": user.email if user else None,
                "referral_code": acc.referral_code,
                "status": acc.status,
                "fraud_note": acc.fraud_note,
                "signups": int(signups),
                "paid_users": int(paid),
                "refunds": int(refunds),
            }
        )
    return out


def admin_overview(db: Session) -> dict[str, Any]:
    total_aff = db.query(func.count(AffiliateAccount.id)).scalar() or 0
    active_aff = db.query(func.count(AffiliateAccount.id)).filter(AffiliateAccount.status == "active").scalar() or 0
    total_clicks = db.query(func.count(AffiliateClick.id)).scalar() or 0
    total_signups = db.query(func.count(AffiliateReferral.id)).scalar() or 0
    total_paid_users = (
        db.query(func.count(AffiliateReferral.id)).filter(AffiliateReferral.status == "paid").scalar() or 0
    )
    pending_comm = (
        db.query(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0))
        .filter(AffiliateCommission.status == "pending")
        .scalar()
        or 0
    )
    approved_comm = (
        db.query(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0))
        .filter(AffiliateCommission.status == "approved")
        .scalar()
        or 0
    )
    paid_comm = (
        db.query(func.coalesce(func.sum(AffiliateCommission.commission_amount), 0))
        .filter(AffiliateCommission.status == "paid")
        .scalar()
        or 0
    )
    return {
        "total_affiliates": int(total_aff),
        "active_affiliates": int(active_aff),
        "total_clicks": int(total_clicks),
        "total_signups": int(total_signups),
        "total_paid_users": int(total_paid_users),
        "commission_pending": int(pending_comm),
        "commission_approved": int(approved_comm),
        "commission_paid": int(paid_comm),
    }


def admin_account_detail(db: Session, account_id: int) -> dict[str, Any]:
    acc = db.query(AffiliateAccount).filter(AffiliateAccount.id == int(account_id)).one_or_none()
    if acc is None:
        raise HTTPException(status_code=404, detail="Affiliate không tồn tại.")
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
    refunds = (
        db.query(func.count(AffiliateCommission.id))
        .filter(AffiliateCommission.affiliate_id == acc.id, AffiliateCommission.status == "cancelled")
        .scalar()
        or 0
    )
    balances = compute_balances(db, acc.id)
    return {
        "id": acc.id,
        "user_id": acc.user_id,
        "email": user.email if user else None,
        "referral_code": acc.referral_code,
        "status": acc.status,
        "commission_rate": acc.commission_rate,
        "cookie_days": acc.cookie_days,
        "fraud_flag": bool(acc.fraud_flag),
        "fraud_note": acc.fraud_note,
        "clicks": int(clicks),
        "signups": int(signups),
        "paid_users": int(paid_users),
        "refunds": int(refunds),
        "total_commission": int(total_comm),
        "balances": balances,
        "payout_info": {
            "bank_name": acc.bank_name,
            "bank_account_name": acc.bank_account_name,
            "bank_account_number_masked": _mask_bank(acc.bank_account_number),
        },
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
        "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
    }


def count_referrals_for_user(db: Session, affiliate_id: int) -> int:
    return int(
        db.query(func.count(AffiliateReferral.id))
        .filter(AffiliateReferral.affiliate_id == int(affiliate_id))
        .scalar()
        or 0
    )


def count_commissions_for_user(db: Session, affiliate_id: int) -> int:
    return int(
        db.query(func.count(AffiliateCommission.id))
        .filter(AffiliateCommission.affiliate_id == int(affiliate_id))
        .scalar()
        or 0
    )


def count_payouts_for_user(db: Session, affiliate_id: int) -> int:
    return int(
        db.query(func.count(AffiliatePayout.id))
        .filter(AffiliatePayout.affiliate_id == int(affiliate_id))
        .scalar()
        or 0
    )


def referral_rows_for_user(db: Session, affiliate_id: int, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = (
        db.query(AffiliateReferral)
        .filter(AffiliateReferral.affiliate_id == affiliate_id)
        .order_by(desc(AffiliateReferral.registered_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        u = db.query(User).filter(User.id == r.referred_user_id).one_or_none()
        plan_name = None
        sub = (
            db.query(Subscription)
            .join(Plan, Subscription.plan_id == Plan.id)
            .filter(
                Subscription.user_id == r.referred_user_id,
                Subscription.status.in_(("active", "trialing")),
            )
            .order_by(desc(Subscription.current_period_start))
            .first()
        )
        if sub is not None:
            plan = db.query(Plan).filter(Plan.id == sub.plan_id).one_or_none()
            plan_name = plan.name if plan else None
        out.append(
            {
                "id": r.id,
                "registered_at": r.registered_at.isoformat() if r.registered_at else None,
                "customer_email": (u.email if u else None),
                "customer_masked": _mask_email(u.email if u else ""),
                "status": r.status,
                "plan_name": plan_name,
                "first_paid_at": r.first_paid_at.isoformat() if r.first_paid_at else None,
            }
        )
    return out


def commission_rows_for_user(db: Session, affiliate_id: int, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = (
        db.query(AffiliateCommission)
        .filter(AffiliateCommission.affiliate_id == affiliate_id)
        .order_by(desc(AffiliateCommission.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    out = []
    for c in rows:
        u = db.query(User).filter(User.id == c.referred_user_id).one_or_none()
        out.append(
            {
                "id": c.id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "customer_masked": _mask_email(u.email if u else ""),
                "order_amount": c.order_amount,
                "commission_rate": c.commission_rate,
                "commission_amount": c.commission_amount,
                "status": c.status,
                "note": c.rejected_reason,
            }
        )
    return out


def payout_rows_for_user(db: Session, affiliate_id: int, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    rows = (
        db.query(AffiliatePayout)
        .filter(AffiliatePayout.affiliate_id == affiliate_id)
        .order_by(desc(AffiliatePayout.requested_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "amount": p.amount,
            "status": p.status,
            "requested_at": p.requested_at.isoformat() if p.requested_at else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "transaction_ref": p.transaction_ref,
            "note": p.note,
        }
        for p in rows
    ]
