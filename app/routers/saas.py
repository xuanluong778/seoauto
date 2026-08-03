"""User-facing SaaS read APIs (Phase 1c/1d — no enforcement)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.schemas.saas import (
    BillingCatalogResponse,
    BillingOverviewResponse,
    CreatePaymentOrderResponse,
    PaymentOrderCreateRequest,
    PaymentOrderListResponse,
    PaymentOrderResponse,
    PaymentOrderStatusResponse,
    PlanListResponse,
    PlanResponse,
    SaasMeResponse,
    UsageLimitResponse,
)
from app.services.account_billing_overview_service import build_billing_overview
from app.services.auth import get_current_user
from app.services import plan_service
from app.services.payment_order_service import (
    PaymentCheckoutError,
    create_payment_order,
    create_payment_order_checkout,
    get_payment_order_by_code,
    get_payment_order_for_user,
    list_payment_orders_for_user,
    payment_order_status_payload,
    payment_order_to_dict,
)
from app.services.rbac import is_admin
from app.services.saas_pricing_service import PUBLIC_PRICING_SLUGS
from app.services.saas_user_service import build_saas_me_response
from app.services.seoauto_pricing_catalog import get_billing_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/saas", tags=["saas"])


def _plan_to_public_response(plan) -> PlanResponse:
    limits = getattr(plan, "usage_limits", None) or []
    return PlanResponse(
        id=plan.id,
        slug=plan.slug,
        name=plan.name,
        description=plan.description,
        price_amount=plan.price_amount,
        currency=plan.currency,
        billing_cycle=plan.billing_cycle,
        is_active=plan.is_active,
        is_public=plan.is_public,
        sort_order=plan.sort_order,
        usage_limits=[UsageLimitResponse.model_validate(ul) for ul in limits],
    )


@router.get("/plans", response_model=PlanListResponse)
def list_public_plans(db: Session = Depends(get_db)) -> PlanListResponse:
    """Public pricing catalog (no auth)."""
    items = []
    for plan in plan_service.list_active_plans(db, public_only=True):
        if plan.slug not in PUBLIC_PRICING_SLUGS:
            continue
        full = plan_service.get_plan_with_limits(db, plan.id) or plan
        items.append(_plan_to_public_response(full))
    return PlanListResponse(items=items, total=len(items))


@router.get("/me", response_model=SaasMeResponse)
def saas_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SaasMeResponse:
    """Current user's plan, subscription period, and monthly quotas (read-only)."""
    resp = build_saas_me_response(db, current_user)
    try:
        from app.services.plan_quota_service import user_quota_snapshot

        data = resp.model_dump()
        data["standardized_quotas"] = user_quota_snapshot(db, current_user)
        return SaasMeResponse.model_validate(data)
    except Exception:
        return resp


@router.get("/plan-quota-catalog")
def saas_plan_quota_catalog() -> dict:
    """Public catalog: quota limits per paid plan (Basic / Pro / Agency / Business)."""
    from app.services.plan_quota_registry import catalog_for_api

    return {"items": catalog_for_api()}


@router.get("/billing-overview", response_model=BillingOverviewResponse)
def billing_overview(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    history_limit: int = Query(50, ge=1, le=100),
) -> BillingOverviewResponse:
    """Plan, credit, quota usage, deduction history, and SePay orders for account billing UI."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    payload = build_billing_overview(db, current_user, history_limit=history_limit)
    return BillingOverviewResponse.model_validate(payload)


@router.get("/billing-catalog", response_model=BillingCatalogResponse)
def billing_catalog(
    response: Response,
    db: Session = Depends(get_db),
) -> BillingCatalogResponse:
    """Pricing plans and add-on packs for account billing UI."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return BillingCatalogResponse.model_validate(get_billing_catalog(db))


def _payment_order_response(order) -> PaymentOrderResponse:
    return PaymentOrderResponse.model_validate(payment_order_to_dict(order))


def _checkout_http_error(exc: PaymentCheckoutError) -> HTTPException:
    logger.warning("payment_checkout_rejected code=%s message=%s", exc.code, exc.message)
    return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})


@router.post("/create-payment-order", response_model=CreatePaymentOrderResponse)
def create_payment_order_checkout_api(
    body: PaymentOrderCreateRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreatePaymentOrderResponse:
    """
    Tạo đơn chuyển khoản từ product_code.
    Giá luôn lấy từ billing catalog — không nhận amount từ client.
    """
    try:
        payload = create_payment_order_checkout(
            db,
            user_id=current_user.id,
            product_code=body.product_code,
        )
        db.commit()
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return CreatePaymentOrderResponse.model_validate(payload)
    except PaymentCheckoutError as exc:
        db.rollback()
        raise _checkout_http_error(exc) from exc
    except Exception as exc:
        db.rollback()
        logger.exception(
            "create_payment_order_failed user_id=%s product_code=%s",
            current_user.id,
            body.product_code,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "server_error", "message": "Không thể tạo đơn thanh toán. Vui lòng thử lại."},
        ) from exc


@router.post("/payment-orders", response_model=PaymentOrderResponse)
def create_payment_order_api(
    body: PaymentOrderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderResponse:
    """Create a bank-transfer payment order. Amount is resolved server-side from billing catalog."""
    try:
        order = create_payment_order(db, user_id=current_user.id, product_code=body.product_code)
        db.commit()
        db.refresh(order)
        return _payment_order_response(order)
    except PaymentCheckoutError as exc:
        db.rollback()
        raise _checkout_http_error(exc) from exc


@router.get("/payment-orders", response_model=PaymentOrderListResponse)
def list_payment_orders_api(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderListResponse:
    items = list_payment_orders_for_user(db, user_id=current_user.id, limit=limit)
    return PaymentOrderListResponse(
        items=[_payment_order_response(o) for o in items],
        total=len(items),
    )


@router.get("/payment-orders/{order_code}/status", response_model=PaymentOrderStatusResponse)
def get_payment_order_status_api(
    order_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderStatusResponse:
    """
    Poll payment order status (owner or admin only).
    Auto-expires pending orders past expired_at before returning.
    """
    order = get_payment_order_by_code(db, order_code=order_code)
    if order is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng.")
    if int(order.user_id) != int(current_user.id) and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Không có quyền xem đơn hàng này.")
    db.commit()
    payload = payment_order_status_payload(order)
    if payload.get("poll_status") == "success":
        logger.info(
            "payment_order_poll_success order_code=%s user_id=%s amount=%s product_code=%s",
            payload.get("order_code"),
            current_user.id,
            payload.get("amount"),
            payload.get("product_code"),
        )
    return PaymentOrderStatusResponse.model_validate(payload)


@router.get("/payment-orders/{order_code}", response_model=PaymentOrderResponse)
def get_payment_order_api(
    order_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderResponse:
    order = get_payment_order_for_user(db, user_id=current_user.id, order_code=order_code)
    if order is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng.")
    return _payment_order_response(order)
