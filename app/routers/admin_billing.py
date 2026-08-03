"""Admin billing APIs — payment orders and manual actions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.admin_billing import (
    AdminBillingActionResponse,
    AdminPaymentOrderDetail,
    AdminPaymentOrderListResponse,
    AdminPaymentOrderRow,
)
from app.services.admin_billing_service import (
    AdminBillingError,
    admin_cancel_order,
    admin_mark_order_paid,
    admin_refund_paid_order,
    admin_retry_activation,
    get_payment_order_admin,
    list_payment_orders_admin,
    log_admin_billing_action,
)
from app.services.rbac import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["admin-billing"])


def _billing_error(exc: AdminBillingError) -> HTTPException:
    code = 404 if exc.code == "not_found" else 400
    return HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("/payment-orders", response_model=AdminPaymentOrderListResponse)
def admin_list_payment_orders(
    request: Request,
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPaymentOrderListResponse:
    data = list_payment_orders_admin(db, status=status, q=q, limit=limit, offset=offset)
    log_admin_billing_action("list", admin, detail={"status": status, "q": q, "total": data["total"]}, request=request)
    db.commit()
    return AdminPaymentOrderListResponse(
        items=[AdminPaymentOrderRow.model_validate(x) for x in data["items"]],
        total=data["total"],
        limit=data["limit"],
        offset=data["offset"],
    )


@router.get("/payment-orders/{order_id}", response_model=AdminPaymentOrderDetail)
def admin_get_payment_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminPaymentOrderDetail:
    row = get_payment_order_admin(db, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng.")
    log_admin_billing_action("view", admin, detail={"order_id": order_id}, request=request)
    db.commit()
    return AdminPaymentOrderDetail.model_validate(row)


@router.post("/payment-orders/{order_id}/retry-activation", response_model=AdminBillingActionResponse)
def admin_retry_payment_activation(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBillingActionResponse:
    try:
        result = admin_retry_activation(db, order_id=order_id, admin=admin, request=request)
        db.commit()
        return AdminBillingActionResponse(
            message=result["message"],
            order=AdminPaymentOrderRow.model_validate(result["order"]),
            activation=result.get("activation"),
        )
    except AdminBillingError as exc:
        db.rollback()
        raise _billing_error(exc) from exc


@router.post("/payment-orders/{order_id}/mark-paid", response_model=AdminBillingActionResponse)
def admin_mark_payment_order_paid(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBillingActionResponse:
    try:
        result = admin_mark_order_paid(db, order_id=order_id, admin=admin, request=request)
        db.commit()
        return AdminBillingActionResponse(
            message=result["message"],
            order=AdminPaymentOrderRow.model_validate(result["order"]),
            activation=result.get("activation"),
        )
    except AdminBillingError as exc:
        db.rollback()
        raise _billing_error(exc) from exc


@router.post("/payment-orders/{order_id}/cancel", response_model=AdminBillingActionResponse)
def admin_cancel_payment_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBillingActionResponse:
    try:
        result = admin_cancel_order(db, order_id=order_id, admin=admin, request=request)
        db.commit()
        return AdminBillingActionResponse(
            message=result["message"],
            order=AdminPaymentOrderRow.model_validate(result["order"]),
        )
    except AdminBillingError as exc:
        db.rollback()
        raise _billing_error(exc) from exc


@router.post("/payment-orders/{order_id}/refund", response_model=AdminBillingActionResponse)
def admin_refund_payment_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_user),
) -> AdminBillingActionResponse:
    try:
        result = admin_refund_paid_order(db, order_id=order_id, admin=admin, request=request)
        db.commit()
        return AdminBillingActionResponse(
            message=result["message"],
            order=AdminPaymentOrderRow.model_validate(result["order"]),
        )
    except AdminBillingError as exc:
        db.rollback()
        raise _billing_error(exc) from exc
