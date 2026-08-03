"""Activate purchased products after successful payment (idempotent per order_id)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.models.user_quota_addon import UserQuotaAddon
from app.services import plan_service, subscription_service
from app.services.credits import (
    grant_credits,
    purchased_expiry_months,
)
from app.services.monthly_bonus_credit_service import grant_plan_cycle_credits_for_order
from app.services.seoauto_pricing_catalog import get_billing_product_by_code
from app.services.software_access_service import maybe_auto_activate_trial_3d

logger = logging.getLogger(__name__)

from app.services.saas_hybrid_pricing import PLAN_MONTHLY_BONUS_CREDITS

ARTICLE_ADDON_FEATURE_KEY = "content_ai_article"
CREDIT_PACK_VALIDITY_DAYS = 365
ARTICLE_ADDON_VALIDITY_DAYS = 30


class ProductActivationError(Exception):
    """Raised when product fulfillment fails after payment."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_product_type(product: dict[str, Any]) -> str:
    raw = str(product.get("product_type") or "").strip().lower()
    if raw in ("saas_plan", "plan"):
        return "plan"
    if raw in ("credit_addon", "credit_pack"):
        return "credit_pack"
    if raw == "article_addon":
        return "article_addon"
    return raw


def _load_order(db: Session, order_id: int) -> PaymentOrder:
    order = db.query(PaymentOrder).filter(PaymentOrder.id == int(order_id)).one_or_none()
    if order is None:
        raise ProductActivationError(f"payment_order not found: {order_id}")
    return order


def _load_cached_activation(order: PaymentOrder) -> dict[str, Any] | None:
    if str(order.activation_status or "") != "activated":
        return None
    if not order.activation_result_json:
        return {"order_id": order.id, "status": "activated", "idempotent": True}
    try:
        data = json.loads(order.activation_result_json)
        if isinstance(data, dict):
            data["idempotent"] = True
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {"order_id": order.id, "status": "activated", "idempotent": True}


def _mark_activation_success(db: Session, order: PaymentOrder, result: dict[str, Any]) -> None:
    order.activation_status = "activated"
    order.activation_error = None
    order.activation_result_json = json.dumps(result, ensure_ascii=False)
    order.activated_at = _utc_now()
    db.flush()


def _mark_activation_failed(db: Session, order: PaymentOrder, error: Exception) -> None:
    try:
        order.activation_status = "activation_failed"
        order.activation_error = str(error)[:2000]
        db.flush()
    except Exception:
        # Recover session after a failed nested flush so admin can still see failure.
        try:
            db.rollback()
        except Exception:
            pass
        try:
            order = db.merge(order)
            order.activation_status = "activation_failed"
            order.activation_error = str(error)[:2000]
            db.flush()
        except Exception:
            logger.exception("mark_activation_failed_persist_error order_id=%s", getattr(order, "id", None))


def _activate_plan(
    db: Session,
    *,
    user_id: int,
    order_id: int,
    product: dict[str, Any],
    product_code: str,
) -> dict[str, Any]:
    slug = str(product.get("plan_slug") or "").strip().lower()
    if slug not in PLAN_MONTHLY_BONUS_CREDITS:
        raise ProductActivationError(f"Unsupported plan slug: {slug}")

    plan = plan_service.get_plan_by_slug(db, slug)
    if plan is None:
        raise ProductActivationError(f"Plan not found: {slug}")

    cycle = str(product.get("billing_cycle") or "monthly").strip().lower()
    duration_months = product.get("duration_months")
    period_days = product.get("period_days")
    if duration_months is not None:
        duration_months = int(duration_months)
    elif period_days is not None:
        period_days = int(period_days)
    else:
        period_days = 365 if cycle == "yearly" else (183 if cycle == "semi_annual" else 30)
        if cycle == "semi_annual":
            duration_months = 6
        elif cycle == "yearly":
            duration_months = 14
    note = f"order_id={order_id} product_code={product_code}"

    sub, action = subscription_service.extend_or_create_subscription(
        db,
        int(user_id),
        int(plan.id),
        period_days=period_days,
        duration_months=duration_months,
        status="active",
        source="sepay",
        notes=note,
        billing_cycle=cycle,
    )

    from app.services.saas_trial_service import end_saas_trial_state, log_trial_audit

    end_saas_trial_state(db, int(user_id), reason="trial_to_paid")
    try:
        log_trial_audit(
            db,
            action="trial_to_paid",
            user_id=int(user_id),
            detail={"plan_slug": slug, "order_id": int(order_id)},
        )
    except Exception:
        # Audit must never block paid fulfillment after money is received.
        logger.exception(
            "trial_audit_log_failed user_id=%s order_id=%s plan_slug=%s",
            user_id,
            order_id,
            slug,
        )

    bonus_result = grant_plan_cycle_credits_for_order(
        db,
        user_id=int(user_id),
        plan_slug=slug,
        order_id=int(order_id),
        billing_cycle=cycle,
    )
    bonus_credits = int(bonus_result.get("granted") or 0)
    credit_balance = int(bonus_result.get("credit_balance") or 0)
    if not bonus_result.get("credit_balance") and bonus_credits:
        from app.services.credits import get_available_balance

        credit_balance = get_available_balance(db, user_id)

    limits = plan_service.get_limits_for_plan(db, plan.id)
    quota_snapshot = {
        ul.feature_key: int(ul.limit_value)
        for ul in limits
        if ul.period == "monthly"
    }

    return {
        "product_type": "plan",
        "kind": "subscription",
        "subscription_id": int(sub.id),
        "subscription_action": action,
        "plan_slug": slug,
        "billing_cycle": cycle,
        "period_days": period_days,
        "duration_months": duration_months,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "bonus_credits_granted": bonus_credits,
        "plan_credit_grant": bonus_result,
        "base_credit": bonus_result.get("base_credit"),
        "bonus_credit": bonus_result.get("bonus_credit"),
        "total_credit": bonus_result.get("total_credit"),
        "monthly_bonus_grant": bonus_result,
        "credit_balance": credit_balance,
        "quota_limits": quota_snapshot,
        "order_id": int(order_id),
        "product_code": product_code,
    }


def _activate_credit_pack(
    db: Session,
    *,
    user_id: int,
    order_id: int,
    product: dict[str, Any],
    product_code: str,
) -> dict[str, Any]:
    credits = int(product.get("credits") or 0)
    if credits <= 0:
        raise ProductActivationError(f"Invalid credits for {product_code}")

    # Idempotent: credit pack grant is keyed by order_id in ledger note.
    marker = f"order_id={int(order_id)}"
    from app.models.credit_ledger import CreditLedger
    from app.services.credits import get_available_balance

    existing_grant = (
        db.query(CreditLedger)
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.reason == "credit_pack_purchase",
            CreditLedger.note.contains(marker),
            CreditLedger.delta > 0,
        )
        .order_by(CreditLedger.id.desc())
        .first()
    )
    if existing_grant is not None:
        return {
            "product_type": "credit_pack",
            "kind": "credit",
            "credits": int(existing_grant.delta),
            "credit_balance": get_available_balance(db, user_id),
            "expires_at": existing_grant.expires_at.isoformat() if existing_grant.expires_at else None,
            "order_id": int(order_id),
            "product_code": product_code,
            "idempotent": True,
        }

    validity_months = int(product.get("validity_months") or 12)
    expires_at = purchased_expiry_months(validity_months)
    note = f"order_id={order_id} product_code={product_code} expires={expires_at.date().isoformat()}"

    user = db.get(User, int(user_id))
    if user is None:
        raise ProductActivationError(f"User not found: {user_id}")

    balance = grant_credits(
        db,
        user_id=int(user_id),
        amount=credits,
        reason="credit_pack_purchase",
        source_type="purchased",
        note=note,
        expired_at=expires_at,
    )

    trial_auto = maybe_auto_activate_trial_3d(
        db,
        user,
        source="payment_credit_pack_auto_trial_activated",
        extra={"order_id": int(order_id), "product_code": product_code, "credits": credits},
    )

    return {
        "product_type": "credit_pack",
        "kind": "credit",
        "credits": credits,
        "credit_balance": balance,
        "expires_at": expires_at.isoformat(),
        "validity_months": validity_months,
        "trial_auto_activated": trial_auto,
        "order_id": int(order_id),
        "product_code": product_code,
    }


def _activate_article_addon(
    db: Session,
    *,
    user_id: int,
    order_id: int,
    product: dict[str, Any],
    product_code: str,
) -> dict[str, Any]:
    articles = int(product.get("articles") or 0)
    if articles <= 0:
        raise ProductActivationError(f"Invalid article quota for {product_code}")

    existing_addon = (
        db.query(UserQuotaAddon)
        .filter(UserQuotaAddon.payment_order_id == int(order_id))
        .one_or_none()
    )
    if existing_addon is not None:
        return {
            "product_type": "article_addon",
            "kind": "article_addon",
            "articles": int(existing_addon.bonus_limit),
            "feature_key": existing_addon.feature_key,
            "expires_at": existing_addon.expires_at.isoformat(),
            "order_id": int(order_id),
            "product_code": product_code,
            "idempotent": True,
        }

    expires_at = _utc_now() + timedelta(days=ARTICLE_ADDON_VALIDITY_DAYS)
    addon = UserQuotaAddon(
        user_id=int(user_id),
        payment_order_id=int(order_id),
        feature_key=ARTICLE_ADDON_FEATURE_KEY,
        bonus_limit=articles,
        product_code=product_code,
        expires_at=expires_at,
    )
    db.add(addon)
    db.flush()

    return {
        "product_type": "article_addon",
        "kind": "article_addon",
        "articles": articles,
        "feature_key": ARTICLE_ADDON_FEATURE_KEY,
        "expires_at": expires_at.isoformat(),
        "order_id": int(order_id),
        "product_code": product_code,
    }


def _activate_product_inner(
    db: Session,
    *,
    user_id: int,
    product_code: str,
    order_id: int,
) -> dict[str, Any]:
    code = str(product_code or "").strip().upper()
    product = get_billing_product_by_code(code)
    if not product:
        raise ProductActivationError(f"Unknown product_code: {code}")

    ptype = normalize_product_type(product)
    if ptype == "plan":
        return _activate_plan(db, user_id=user_id, order_id=order_id, product=product, product_code=code)
    if ptype == "credit_pack":
        return _activate_credit_pack(
            db, user_id=user_id, order_id=order_id, product=product, product_code=code
        )
    if ptype == "article_addon":
        return _activate_article_addon(
            db, user_id=user_id, order_id=order_id, product=product, product_code=code
        )
    raise ProductActivationError(f"Unsupported product_type: {ptype}")


def activate_product(
    db: Session,
    *,
    user_id: int,
    product_code: str,
    order_id: int,
) -> dict[str, Any]:
    """
    Fulfill a paid order idempotently.
    - Already activated → return cached result
    - On failure → order stays paid, activation_status=activation_failed
    """
    order = _load_order(db, order_id)
    if int(order.user_id) != int(user_id):
        raise ProductActivationError(
            f"order {order_id} does not belong to user {user_id}"
        )

    cached = _load_cached_activation(order)
    if cached is not None:
        logger.info(
            "activate_product_skip_duplicate order_id=%s user_id=%s product_code=%s",
            order_id,
            user_id,
            product_code,
        )
        return cached

    try:
        result = _activate_product_inner(
            db,
            user_id=user_id,
            product_code=product_code,
            order_id=order_id,
        )
        _mark_activation_success(db, order, result)
        logger.info(
            "activate_product_success order_id=%s user_id=%s product_code=%s kind=%s",
            order_id,
            user_id,
            product_code,
            result.get("kind"),
        )
        return result
    except Exception as exc:
        _mark_activation_failed(db, order, exc)
        logger.exception(
            "activate_product_failed order_id=%s user_id=%s product_code=%s error=%s",
            order_id,
            user_id,
            product_code,
            exc,
        )
        raise ProductActivationError(str(exc)) from exc
