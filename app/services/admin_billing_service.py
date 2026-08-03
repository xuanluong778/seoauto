"""Admin billing: list payment orders and manual fulfillment actions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.models.payment_order import PaymentOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.sepay_payment_transaction import SepayPaymentTransaction
from app.models.user import User
from app.services.affiliate_payment_hooks import on_payment_completed, on_payment_refunded
from app.services.payment_activation_service import ProductActivationError, activate_product
from app.services.payment_order_service import (
    expire_stale_pending_orders,
    mark_payment_order_paid,
    payment_order_status_payload,
)
from app.services.security_audit_log import log_audit_event
from app.services.seoauto_pricing_catalog import billing_product_display_name, get_billing_product_by_code

logger = logging.getLogger(__name__)

CANCELLABLE_STATUSES = frozenset({"pending", "partial_paid", "expired"})


class AdminBillingError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_state") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def log_admin_billing_action(
    action: str,
    admin: User,
    *,
    order: PaymentOrder | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    log_audit_event(
        action=f"admin.billing.{action}",
        user_id=int(admin.id),
        resource_type="payment_order",
        resource_id=str(order.id if order else ""),
        detail={
            "order_code": order.order_code if order else None,
            "user_id": order.user_id if order else None,
            **(detail or {}),
        },
        request=request,
    )


def _product_name(product_code: str) -> str:
    product = get_billing_product_by_code(product_code)
    return billing_product_display_name(product) if product else product_code


def _sepay_count_map(db: Session, order_codes: list[str]) -> dict[str, int]:
    codes = [c for c in order_codes if c]
    if not codes:
        return {}
    rows = (
        db.query(SepayPaymentTransaction.order_code, func.count(SepayPaymentTransaction.id))
        .filter(SepayPaymentTransaction.order_code.in_(codes))
        .group_by(SepayPaymentTransaction.order_code)
        .all()
    )
    return {str(code): int(cnt) for code, cnt in rows}


def _parse_raw_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _order_row(
    db: Session,
    order: PaymentOrder,
    *,
    user_email: str | None = None,
    sepay_count: int | None = None,
) -> dict[str, Any]:
    email = user_email
    if email is None:
        user = db.query(User).filter(User.id == order.user_id).one_or_none()
        email = user.email if user else ""
    if sepay_count is None:
        sepay_count = (
            db.query(func.count(SepayPaymentTransaction.id))
            .filter(SepayPaymentTransaction.order_code == order.order_code)
            .scalar()
            or 0
        )
    return {
        "id": int(order.id),
        "user_id": int(order.user_id),
        "user_email": str(email or ""),
        "order_code": order.order_code,
        "product_code": str(order.product_code or ""),
        "product_name": _product_name(str(order.product_code or "")),
        "amount": int(order.amount or 0),
        "status": str(order.status or ""),
        "activation_status": order.activation_status,
        "activation_error": order.activation_error,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
        "expired_at": order.expired_at,
        "sepay_transaction_count": int(sepay_count or 0),
    }


def list_payment_orders_admin(
    db: Session,
    *,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    expire_stale_pending_orders(db)
    query = db.query(PaymentOrder, User.email).join(User, PaymentOrder.user_id == User.id)

    st = str(status or "").strip().lower()
    if st == "activation_failed":
        query = query.filter(
            PaymentOrder.status == "paid",
            PaymentOrder.activation_status == "activation_failed",
        )
    elif st:
        query = query.filter(PaymentOrder.status == st)

    term = str(q or "").strip()
    if term:
        if term.isdigit():
            query = query.filter(
                or_(
                    PaymentOrder.user_id == int(term),
                    PaymentOrder.order_code.ilike(f"%{term}%"),
                )
            )
        elif "@" in term:
            query = query.filter(User.email.ilike(f"%{term}%"))
        else:
            query = query.filter(
                or_(
                    PaymentOrder.order_code.ilike(f"%{term}%"),
                    PaymentOrder.product_code.ilike(f"%{term.upper()}%"),
                    User.email.ilike(f"%{term}%"),
                )
            )

    total = query.count()
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    rows = (
        query.order_by(desc(PaymentOrder.id))
        .offset(off)
        .limit(lim)
        .all()
    )
    codes = [o.order_code for o, _ in rows if o.order_code]
    sepay_map = _sepay_count_map(db, codes)
    items = [
        _order_row(db, order, user_email=email, sepay_count=sepay_map.get(order.order_code or "", 0))
        for order, email in rows
    ]
    return {"items": items, "total": total, "limit": lim, "offset": off}


def get_payment_order_admin(db: Session, order_id: int) -> dict[str, Any] | None:
    expire_stale_pending_orders(db)
    row = (
        db.query(PaymentOrder, User.email)
        .join(User, PaymentOrder.user_id == User.id)
        .filter(PaymentOrder.id == int(order_id))
        .one_or_none()
    )
    if row is None:
        return None
    order, email = row
    sepay_rows = (
        db.query(SepayPaymentTransaction)
        .filter(SepayPaymentTransaction.order_code == order.order_code)
        .order_by(desc(SepayPaymentTransaction.id))
        .all()
    )
    detail = _order_row(db, order, user_email=email, sepay_count=len(sepay_rows))
    detail.update(
        {
            "activation_result_json": order.activation_result_json,
            "activated_at": order.activated_at,
            "bank_code": order.bank_code,
            "bank_account": order.bank_account,
            "bank_holder": order.bank_holder,
            "sepay_transactions": [
                {
                    "id": tx.id,
                    "sepay_transaction_id": tx.sepay_transaction_id,
                    "order_code": tx.order_code,
                    "account_number": tx.account_number,
                    "transfer_amount": int(tx.transfer_amount or 0),
                    "transfer_type": tx.transfer_type,
                    "content": tx.content,
                    "raw_payload": _parse_raw_payload(tx.raw_payload),
                    "created_at": tx.created_at,
                }
                for tx in sepay_rows
            ],
        }
    )
    return detail


def _fulfill_paid_order(
    db: Session,
    order: PaymentOrder,
    *,
    provider: str,
    provider_transaction_id: str,
    paid_amount: int | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    amount = int(paid_amount if paid_amount is not None else order.amount)
    mark_payment_order_paid(db, order, at=now)

    activation: dict[str, Any] | None = None
    activation_error: str | None = None
    try:
        activation = activate_product(
            db,
            user_id=int(order.user_id),
            product_code=str(order.product_code),
            order_id=int(order.id),
        )
    except ProductActivationError as exc:
        activation_error = str(exc)
        logger.error(
            "admin_billing_activation_failed order_id=%s order_code=%s error=%s",
            order.id,
            order.order_code,
            exc,
        )

    subscription_id = activation.get("subscription_id") if activation else None
    plan_id = None
    if activation and activation.get("kind") == "subscription" and subscription_id:
        from app.services import plan_service

        bp = get_billing_product_by_code(order.product_code)
        if bp and bp.get("plan_slug"):
            pl = plan_service.get_plan_by_slug(db, str(bp["plan_slug"]))
            plan_id = pl.id if pl else None

    pay_tx = PaymentTransaction(
        user_id=int(order.user_id),
        subscription_id=int(subscription_id) if subscription_id else None,
        plan_id=int(plan_id) if plan_id else None,
        amount=amount,
        currency="VND",
        status="paid",
        provider=provider,
        provider_transaction_id=provider_transaction_id,
        provider_payload_json=json.dumps(
            {"order_code": order.order_code, "source": provider},
            ensure_ascii=False,
        ),
        paid_at=now,
    )
    db.add(pay_tx)
    db.flush()

    try:
        on_payment_completed(
            db,
            user_id=int(order.user_id),
            net_amount=amount,
            payment_transaction_id=int(pay_tx.id),
            subscription_id=int(subscription_id) if subscription_id else None,
            invoice_id=str(order.order_code),
        )
    except Exception:
        logger.exception(
            "admin_billing_affiliate_hook_failed order_id=%s payment_transaction_id=%s",
            order.id,
            pay_tx.id,
        )

    return {
        "activation": activation,
        "activation_error": activation_error,
        "payment_transaction_id": pay_tx.id,
        "status_payload": payment_order_status_payload(order),
    }


def admin_mark_order_paid(
    db: Session,
    *,
    order_id: int,
    admin: User,
    request: Request | None = None,
) -> dict[str, Any]:
    order = db.query(PaymentOrder).filter(PaymentOrder.id == int(order_id)).one_or_none()
    if order is None:
        raise AdminBillingError("Không tìm thấy đơn hàng.", code="not_found")
    if order.status == "paid":
        raise AdminBillingError("Đơn đã ở trạng thái paid.", code="already_paid")
    if order.status == "cancelled":
        raise AdminBillingError("Không thể mark paid đơn đã hủy.", code="cancelled")

    result = _fulfill_paid_order(
        db,
        order,
        provider="admin_manual",
        provider_transaction_id=f"admin:{admin.id}:{order.id}:{int(datetime.now(timezone.utc).timestamp())}",
    )
    log_admin_billing_action(
        "mark_paid",
        admin,
        order=order,
        detail={
            "payment_transaction_id": result.get("payment_transaction_id"),
            "activation_status": order.activation_status,
            "activation_error": result.get("activation_error"),
        },
        request=request,
    )
    db.refresh(order)
    return {
        "message": "Đã đánh dấu thanh toán thủ công.",
        "order": _order_row(db, order),
        "activation": result.get("activation"),
    }


def admin_retry_activation(
    db: Session,
    *,
    order_id: int,
    admin: User,
    request: Request | None = None,
) -> dict[str, Any]:
    order = db.query(PaymentOrder).filter(PaymentOrder.id == int(order_id)).one_or_none()
    if order is None:
        raise AdminBillingError("Không tìm thấy đơn hàng.", code="not_found")
    if order.status != "paid":
        raise AdminBillingError("Chỉ retry activation cho đơn đã paid.", code="not_paid")
    if order.activation_status == "activated":
        raise AdminBillingError("Đơn đã được kích hoạt.", code="already_activated")

    try:
        activation = activate_product(
            db,
            user_id=int(order.user_id),
            product_code=str(order.product_code),
            order_id=int(order.id),
        )
    except ProductActivationError as exc:
        log_admin_billing_action(
            "retry_activation_failed",
            admin,
            order=order,
            detail={"error": str(exc)},
            request=request,
        )
        raise AdminBillingError(str(exc), code="activation_failed") from exc

    log_admin_billing_action(
        "retry_activation",
        admin,
        order=order,
        detail={"activation_status": order.activation_status},
        request=request,
    )
    db.refresh(order)
    return {
        "message": "Kích hoạt lại thành công.",
        "order": _order_row(db, order),
        "activation": activation,
    }


def admin_cancel_order(
    db: Session,
    *,
    order_id: int,
    admin: User,
    request: Request | None = None,
) -> dict[str, Any]:
    order = db.query(PaymentOrder).filter(PaymentOrder.id == int(order_id)).one_or_none()
    if order is None:
        raise AdminBillingError("Không tìm thấy đơn hàng.", code="not_found")
    if order.status == "paid":
        raise AdminBillingError("Không thể hủy đơn đã thanh toán.", code="already_paid")
    if order.status == "cancelled":
        raise AdminBillingError("Đơn đã bị hủy.", code="already_cancelled")
    if order.status not in CANCELLABLE_STATUSES:
        raise AdminBillingError(
            f"Không thể hủy đơn ở trạng thái {order.status}.",
            code="invalid_state",
        )

    prev = order.status
    order.status = "cancelled"
    db.flush()
    log_admin_billing_action(
        "cancel_order",
        admin,
        order=order,
        detail={"previous_status": prev},
        request=request,
    )
    db.refresh(order)
    return {
        "message": "Đã hủy đơn hàng.",
        "order": _order_row(db, order),
    }


def admin_refund_paid_order(
    db: Session,
    *,
    order_id: int,
    admin: User,
    request: Request | None = None,
) -> dict[str, Any]:
    """Mark a paid order as refunded and run affiliate clawback/cancel hooks.

    Does not reverse subscription entitlement — only payment + affiliate side effects.
    """
    order = db.query(PaymentOrder).filter(PaymentOrder.id == int(order_id)).one_or_none()
    if order is None:
        raise AdminBillingError("Không tìm thấy đơn hàng.", code="not_found")
    if order.status == "refunded":
        raise AdminBillingError("Đơn đã được hoàn tiền.", code="already_refunded")
    if order.status != "paid":
        raise AdminBillingError("Chỉ hoàn tiền đơn đã thanh toán (paid).", code="not_paid")

    pay_tx = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.user_id == int(order.user_id),
            PaymentTransaction.status == "paid",
        )
        .order_by(desc(PaymentTransaction.id))
        .all()
    )
    matched: PaymentTransaction | None = None
    if order.order_code:
        for tx in pay_tx:
            if order.order_code in str(tx.provider_payload_json or ""):
                matched = tx
                break
    if matched is None and len(pay_tx) == 1 and int(pay_tx[0].amount or 0) == int(order.amount or 0):
        matched = pay_tx[0]

    cancelled = 0
    payment_transaction_id = int(matched.id) if matched is not None else None
    subscription_id = int(matched.subscription_id) if matched and matched.subscription_id else None
    try:
        cancelled = on_payment_refunded(
            db,
            payment_transaction_id=payment_transaction_id,
            subscription_id=subscription_id,
        )
    except Exception:
        logger.exception(
            "admin_billing_affiliate_refund_hook_failed order_id=%s payment_transaction_id=%s",
            order.id,
            payment_transaction_id,
        )
        raise AdminBillingError(
            "Không cập nhật được hoa hồng affiliate khi hoàn tiền.",
            code="affiliate_hook_failed",
        ) from None

    if matched is not None:
        matched.status = "refunded"
    order.status = "refunded"
    db.flush()
    log_admin_billing_action(
        "refund_order",
        admin,
        order=order,
        detail={
            "payment_transaction_id": payment_transaction_id,
            "affiliate_commissions_affected": cancelled,
        },
        request=request,
    )
    db.refresh(order)
    return {
        "message": "Đã hoàn tiền đơn hàng và cập nhật hoa hồng affiliate.",
        "order": _order_row(db, order),
        "affiliate_commissions_affected": cancelled,
        "payment_transaction_id": payment_transaction_id,
    }
