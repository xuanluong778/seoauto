"""Payment gateway hooks for affiliate commission lifecycle."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.affiliate_service import (
    cancel_commission_for_refund,
    record_commission_for_payment,
)


def on_payment_completed(
    db: Session,
    *,
    user_id: int,
    net_amount: int,
    payment_transaction_id: int | None = None,
    subscription_id: int | None = None,
    invoice_id: str | None = None,
):
    """Call when payment is confirmed. *net_amount* = doanh thu thực nhận sau giảm giá (VND)."""
    return record_commission_for_payment(
        db,
        user_id=user_id,
        order_amount=int(net_amount),
        payment_transaction_id=payment_transaction_id,
        subscription_id=subscription_id,
        invoice_id=invoice_id,
    )


def on_payment_refunded(
    db: Session,
    *,
    payment_transaction_id: int | None = None,
    subscription_id: int | None = None,
) -> int:
    """Call when payment is refunded/cancelled — returns number of commissions cancelled."""
    return cancel_commission_for_refund(
        db,
        payment_transaction_id=payment_transaction_id,
        subscription_id=subscription_id,
    )
