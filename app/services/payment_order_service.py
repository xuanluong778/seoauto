"""Payment order lifecycle: create from billing catalog, expire pending orders."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment_order import PAYMENT_ORDER_STATUSES, PaymentOrder
from app.services.payment_qr import build_vietqr_url
from app.services.seoauto_pricing_catalog import (
    billing_product_display_name,
    get_billing_product_by_code,
    is_billing_product_active,
)

from app.services.billing_vat import billing_vat_percent, payment_amount_breakdown, price_with_vat
from app.services.payment_config import payment_bank_details, payment_order_expire_minutes

CONTACT_SALES_PRODUCT_CODE = "ARTICLE_ADDON_1000"

logger = logging.getLogger(__name__)


class PaymentCheckoutError(Exception):
    """Controlled checkout validation error (mapped to HTTP 400)."""

    def __init__(self, message: str, *, code: str = "invalid_product") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_product_amount(product_code: str, db: Session | None = None) -> dict[str, Any]:
    """
    Resolve price from billing catalog on the server.
    Raises PaymentCheckoutError when product is unknown, inactive, or not purchasable online.
    """
    code = str(product_code or "").strip().upper()
    if not code:
        raise PaymentCheckoutError("product_code là bắt buộc.", code="missing_product_code")

    product = get_billing_product_by_code(code)
    if not product:
        logger.warning("checkout_unknown_product_code user_product_code=%r", product_code)
        raise PaymentCheckoutError(f"product_code không hợp lệ: {code}", code="unknown_product")

    if db is not None and not is_billing_product_active(db, product):
        raise PaymentCheckoutError(f"Sản phẩm {code} không còn khả dụng.", code="inactive_product")

    if product.get("contact_sales") or code == CONTACT_SALES_PRODUCT_CODE:
        raise PaymentCheckoutError(
            f"Sản phẩm {code} cần liên hệ hỗ trợ.",
            code="contact_sales",
        )

    price = product.get("price")
    if price is None:
        raise PaymentCheckoutError(
            f"Sản phẩm {code} không có giá thanh toán trực tuyến.",
            code="no_price",
        )
    try:
        amount = int(price)
    except (TypeError, ValueError) as exc:
        logger.error("checkout_invalid_price product_code=%s price=%r", code, price)
        raise PaymentCheckoutError(f"Sản phẩm {code} có giá không hợp lệ.", code="invalid_price") from exc
    if amount <= 0:
        raise PaymentCheckoutError(f"Sản phẩm {code} có giá không hợp lệ.", code="invalid_price")

    amount_with_vat = price_with_vat(amount)
    if amount_with_vat is None or amount_with_vat <= 0:
        raise PaymentCheckoutError(f"Sản phẩm {code} có giá không hợp lệ.", code="invalid_price")

    breakdown = payment_amount_breakdown(amount)
    return {
        "product_code": code,
        "amount": breakdown["amount"],
        "base_amount": breakdown["base_amount"],
        "vat_amount": breakdown["vat_amount"],
        "vat_percent": breakdown["vat_percent"],
        "product": product,
        "product_name": billing_product_display_name(product),
    }


def evaluate_checkout_product(db: Session, product_code: str) -> dict[str, Any]:
    """
    Validate product for checkout without creating an order.
    Returns contact_sales payload or resolved product info.
    """
    code = str(product_code or "").strip().upper()
    if not code:
        raise PaymentCheckoutError("product_code là bắt buộc.", code="missing_product_code")

    product = get_billing_product_by_code(code)
    if not product:
        logger.warning("checkout_unknown_product_code product_code=%r", product_code)
        raise PaymentCheckoutError(f"product_code không hợp lệ: {code}", code="unknown_product")

    product_name = billing_product_display_name(product)

    if product.get("contact_sales") or code == CONTACT_SALES_PRODUCT_CODE:
        return {
            "contact_sales": True,
            "product_code": code,
            "product_name": product_name,
            "message": "Gói +1.000 bài/tháng cần liên hệ hỗ trợ, không thanh toán tự động.",
        }

    if not is_billing_product_active(db, product):
        raise PaymentCheckoutError(f"Sản phẩm {code} không còn khả dụng.", code="inactive_product")

    resolved = resolve_product_amount(code, db)
    return {
        "contact_sales": False,
        "product_code": code,
        "product_name": resolved["product_name"],
        "amount": resolved["amount"],
        "product": resolved["product"],
    }


def build_order_code(order_id: int, at: datetime | None = None) -> str:
    """Format: SEOA{YYYYMMDD}{order_id}"""
    ts = at or datetime.now(timezone.utc)
    return f"SEOA{ts.strftime('%Y%m%d')}{int(order_id)}"


def expire_stale_pending_orders(db: Session, *, user_id: int | None = None) -> int:
    now = datetime.now(timezone.utc)
    q = db.query(PaymentOrder).filter(
        PaymentOrder.status == "pending",
        PaymentOrder.expired_at < now,
    )
    if user_id is not None:
        q = q.filter(PaymentOrder.user_id == user_id)
    changed = 0
    for order in q.all():
        order.status = "expired"
        changed += 1
    if changed:
        db.flush()
    return changed


def create_payment_order(db: Session, *, user_id: int, product_code: str) -> PaymentOrder:
    resolved = resolve_product_amount(product_code, db)
    bank = payment_bank_details()
    now = datetime.now(timezone.utc)
    expire_mins = payment_order_expire_minutes()

    order = PaymentOrder(
        user_id=int(user_id),
        order_code=None,
        product_code=resolved["product_code"],
        amount=int(resolved["amount"]),
        status="pending",
        bank_code=bank["bank_code"],
        bank_account=bank["bank_account"],
        bank_holder=bank["bank_holder"],
        expired_at=now + timedelta(minutes=expire_mins),
    )
    db.add(order)
    db.flush()
    order.order_code = build_order_code(order.id, now)
    db.flush()
    return order


def pricing_breakdown_for_order(
    order: PaymentOrder, pricing: dict[str, Any] | None = None
) -> dict[str, int]:
    """Resolve subtotal / VAT / total for checkout UI and status poll."""
    if pricing:
        return {
            "base_amount": int(pricing.get("base_amount") or 0),
            "vat_amount": int(pricing.get("vat_amount") or 0),
            "vat_percent": int(pricing.get("vat_percent") or 0),
            "amount": int(pricing.get("amount") or order.amount or 0),
        }

    product = get_billing_product_by_code(str(order.product_code or ""))
    price = product.get("price") if product else None
    if price is not None:
        breakdown = payment_amount_breakdown(int(price))
        breakdown["amount"] = int(order.amount or breakdown["amount"])
        return breakdown

    total = int(order.amount or 0)
    pct = billing_vat_percent()
    if pct <= 0 or total <= 0:
        return {
            "base_amount": total,
            "vat_amount": 0,
            "vat_percent": pct,
            "amount": total,
        }
    base = int(round(total / (1 + pct / 100.0)))
    return {
        "base_amount": base,
        "vat_amount": max(0, total - base),
        "vat_percent": pct,
        "amount": total,
    }


def build_payment_checkout_response(
    order: PaymentOrder, *, product_name: str, pricing: dict[str, Any] | None = None
) -> dict[str, Any]:
    transfer_content = str(order.order_code or "")
    breakdown = pricing_breakdown_for_order(order, pricing)
    total = int(breakdown["amount"])
    qr_url = build_vietqr_url(
        bank_code=order.bank_code,
        bank_account=order.bank_account,
        amount=total,
        transfer_content=transfer_content,
        account_name=order.bank_holder,
    )
    return {
        "success": True,
        "contact_sales": False,
        "order_code": order.order_code,
        "product_code": order.product_code,
        "product_name": product_name,
        "base_amount": breakdown["base_amount"],
        "vat_amount": breakdown["vat_amount"],
        "vat_percent": breakdown["vat_percent"],
        "amount": total,
        "bank_code": order.bank_code,
        "bank_account": order.bank_account,
        "bank_holder": order.bank_holder,
        "transfer_content": transfer_content,
        "expired_at": order.expired_at,
        "qr_url": qr_url,
        "status": order.status,
    }


def create_payment_order_checkout(
    db: Session, *, user_id: int, product_code: str
) -> dict[str, Any]:
    """
    Full checkout flow for POST /api/saas/create-payment-order.
    Amount is always resolved server-side from billing catalog.
    """
    evaluated = evaluate_checkout_product(db, product_code)
    if evaluated.get("contact_sales"):
        logger.info(
            "checkout_contact_sales user_id=%s product_code=%s",
            user_id,
            evaluated.get("product_code"),
        )
        return {
            "success": False,
            "contact_sales": True,
            "product_code": evaluated["product_code"],
            "product_name": evaluated.get("product_name"),
            "message": evaluated.get("message"),
        }

    order = create_payment_order(db, user_id=user_id, product_code=evaluated["product_code"])
    resolved = resolve_product_amount(evaluated["product_code"], db)
    logger.info(
        "payment_order_created user_id=%s order_code=%s product_code=%s amount=%s",
        user_id,
        order.order_code,
        order.product_code,
        order.amount,
    )
    return build_payment_checkout_response(
        order, product_name=evaluated["product_name"], pricing=resolved
    )


def get_payment_order_by_code(db: Session, order_code: str) -> PaymentOrder | None:
    """Lookup order by code; expires stale pending orders first."""
    expire_stale_pending_orders(db)
    code = str(order_code or "").strip()
    if not code:
        return None
    return db.query(PaymentOrder).filter(PaymentOrder.order_code == code).first()


def payment_order_status_payload(order: PaymentOrder) -> dict[str, Any]:
    product = get_billing_product_by_code(str(order.product_code or ""))
    product_name = billing_product_display_name(product) if product else str(order.product_code or "")
    breakdown = pricing_breakdown_for_order(order)
    status = str(order.status or "").strip().lower()
    activation_status = str(order.activation_status or "").strip().lower() if order.activation_status else None

    # poll_status: pending | success | failed — drives frontend auto-redirect
    poll_status = "pending"
    if status == "paid":
        if activation_status == "activated":
            poll_status = "success"
        elif activation_status == "activation_failed":
            poll_status = "failed"
        else:
            poll_status = "pending"
    elif status in ("expired", "cancelled"):
        poll_status = "failed"
    elif status == "partial_paid":
        poll_status = "pending"

    payload: dict[str, Any] = {
        "order_code": str(order.order_code or ""),
        "product_code": str(order.product_code or ""),
        "product_name": product_name,
        "base_amount": breakdown["base_amount"],
        "vat_amount": breakdown["vat_amount"],
        "vat_percent": breakdown["vat_percent"],
        "amount": breakdown["amount"],
        "status": status,
        "poll_status": poll_status,
        "paid_at": order.paid_at,
        "expired_at": order.expired_at,
    }
    if order.activation_status:
        payload["activation_status"] = str(order.activation_status)
    if order.activation_error:
        payload["activation_error"] = str(order.activation_error)[:500]
    return payload


def get_payment_order_for_user(
    db: Session, *, user_id: int, order_code: str
) -> PaymentOrder | None:
    expire_stale_pending_orders(db, user_id=user_id)
    code = str(order_code or "").strip()
    if not code:
        return None
    return (
        db.query(PaymentOrder)
        .filter(PaymentOrder.user_id == user_id, PaymentOrder.order_code == code)
        .first()
    )


def list_payment_orders_for_user(
    db: Session, *, user_id: int, limit: int = 50
) -> list[PaymentOrder]:
    expire_stale_pending_orders(db, user_id=user_id)
    lim = max(1, min(int(limit), 100))
    return (
        db.query(PaymentOrder)
        .filter(PaymentOrder.user_id == user_id)
        .order_by(PaymentOrder.id.desc())
        .limit(lim)
        .all()
    )


def get_pending_payment_order_by_code(db: Session, order_code: str) -> PaymentOrder | None:
    """Find a non-expired pending order by order_code."""
    expire_stale_pending_orders(db)
    code = str(order_code or "").strip().upper()
    if not code:
        return None
    now = datetime.now(timezone.utc)
    return (
        db.query(PaymentOrder)
        .filter(
            PaymentOrder.order_code == code,
            PaymentOrder.status == "pending",
            PaymentOrder.expired_at >= now,
        )
        .first()
    )


def get_fulfillable_payment_order_by_code(db: Session, order_code: str) -> PaymentOrder | None:
    """
    Find an order that can still be fulfilled from a SePay webhook.
    Accepts pending, partial_paid, or expired (customer paid after countdown).
    """
    code = str(order_code or "").strip().upper()
    if not code:
        return None
    compact = "".join(ch for ch in code if ch.isalnum()).upper()
    candidates = [code]
    if compact and compact != code:
        candidates.append(compact)

    order = (
        db.query(PaymentOrder)
        .filter(
            PaymentOrder.order_code.in_(candidates),
            PaymentOrder.status.in_(("pending", "partial_paid", "expired")),
        )
        .order_by(PaymentOrder.id.desc())
        .first()
    )
    return order


def mark_payment_order_paid(db: Session, order: PaymentOrder, *, at: datetime | None = None) -> None:
    ts = at or datetime.now(timezone.utc)
    order.status = "paid"
    order.paid_at = ts


def mark_payment_order_partial_paid(db: Session, order: PaymentOrder) -> None:
    order.status = "partial_paid"


def payment_order_to_dict(order: PaymentOrder) -> dict[str, Any]:
    return {
        "id": order.id,
        "user_id": order.user_id,
        "order_code": order.order_code,
        "product_code": order.product_code,
        "amount": order.amount,
        "status": order.status,
        "bank_code": order.bank_code,
        "bank_account": order.bank_account,
        "bank_holder": order.bank_holder,
        "expired_at": order.expired_at,
        "paid_at": order.paid_at,
        "activation_status": order.activation_status,
        "activation_error": order.activation_error,
        "activated_at": order.activated_at,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def is_valid_payment_order_status(status: str) -> bool:
    return str(status or "").strip().lower() in PAYMENT_ORDER_STATUSES
