"""Persist SePay webhook payloads with duplicate protection."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction
from app.models.sepay_payment_transaction import SepayPaymentTransaction
from app.services.affiliate_payment_hooks import on_payment_completed
from app.services.payment_activation_service import ProductActivationError, activate_product
from app.services.payment_config import billing_bank_account
from app.services.payment_order_service import (
    get_fulfillable_payment_order_by_code,
    mark_payment_order_paid,
    mark_payment_order_partial_paid,
)

logger = logging.getLogger(__name__)

# Match SEOA… even when banks insert spaces/dashes (SEOA 2026-0708-39, SEOA2026070839...).
_ORDER_CODE_RE = re.compile(
    r"SEOA[\s\-_.]*(\d{4})[\s\-_.]*(\d{2})[\s\-_.]*(\d{2})[\s\-_.]*(\d+)",
    re.IGNORECASE,
)
_ORDER_CODE_COMPACT_RE = re.compile(r"(SEOA[0-9A-Z]+)", re.IGNORECASE)


def _normalize_tx_id(payload: dict[str, Any]) -> str | None:
    for key in (
        "id",
        "transaction_id",
        "transactionId",
        "sepay_transaction_id",
        "sepayTransactionId",
        "referenceCode",
        "reference_code",
        "refCode",
    ):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _pick_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = payload.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text and text.lower() not in {"null", "none"}:
            return text
    return None


def _pick_amount(payload: dict[str, Any]) -> int:
    for key in (
        "transferAmount",
        "transfer_amount",
        "amount",
        "money",
        "amount_in",
        "amountIn",
        "transaction_amount",
        "transactionAmount",
    ):
        if key not in payload:
            continue
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        try:
            # Banks occasionally send "110,000" or "110000.0"
            if isinstance(raw, str):
                cleaned = raw.replace(",", "").replace(" ", "").strip()
                return int(float(cleaned))
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return 0


def extract_order_code_from_content(content: str | None) -> str | None:
    """Extract SEOA{YYYYMMDD}{id} from transfer content despite separator junk."""
    if not content:
        return None
    text = str(content)
    m = _ORDER_CODE_RE.search(text)
    if m:
        return f"SEOA{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}".upper()
    m2 = _ORDER_CODE_COMPACT_RE.search(text)
    if not m2:
        return None
    compact = re.sub(r"[^0-9A-Za-z]", "", m2.group(1)).upper()
    if compact.startswith("SEOA") and len(compact) > 4:
        return compact
    return None


def _normalize_order_code(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    extracted = extract_order_code_from_content(raw)
    if extracted:
        return extracted
    compact = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    if compact.startswith("SEOA") and len(compact) > 4:
        return compact
    return raw.upper()


def parse_sepay_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize SePay webhook JSON into DB columns."""
    content = _pick_str(
        payload,
        "content",
        "description",
        "transfer_content",
        "transferContent",
        "message",
        "remark",
        "body",
    )
    order_code = _normalize_order_code(
        _pick_str(payload, "order_code", "orderCode", "code", "payment_code", "paymentCode")
    )
    if not order_code:
        order_code = extract_order_code_from_content(content)

    return {
        "sepay_transaction_id": _normalize_tx_id(payload),
        "order_code": order_code,
        "account_number": _pick_str(
            payload,
            "accountNumber",
            "account_number",
            "subAccount",
            "sub_account",
            "bank_account",
            "bankAccount",
            "account",
        ),
        "transfer_amount": _pick_amount(payload),
        "transfer_type": _pick_str(
            payload, "transferType", "transfer_type", "type", "transactionType", "transaction_type"
        ),
        "content": content,
        "raw_payload": json.dumps(payload, ensure_ascii=False),
    }


def record_sepay_webhook(
    db: Session, payload: dict[str, Any]
) -> tuple[SepayPaymentTransaction | None, bool, str]:
    """
    Insert webhook row idempotently.

    Returns (row, created, status):
    - created=True  → new row inserted
    - created=False → duplicate sepay_transaction_id (row is existing)
    - row=None      → validation error (missing transaction id)
    """
    parsed = parse_sepay_webhook_payload(payload)
    tx_id = parsed.get("sepay_transaction_id")
    if not tx_id:
        logger.warning("sepay_webhook_missing_transaction_id payload_keys=%s", list(payload.keys()))
        return None, False, "missing_transaction_id"

    existing = (
        db.query(SepayPaymentTransaction)
        .filter(SepayPaymentTransaction.sepay_transaction_id == tx_id)
        .first()
    )
    if existing is not None:
        logger.info("sepay_webhook_duplicate transaction_id=%s", tx_id)
        return existing, False, "duplicate"

    row = SepayPaymentTransaction(
        sepay_transaction_id=tx_id,
        order_code=parsed.get("order_code"),
        account_number=parsed.get("account_number"),
        transfer_amount=int(parsed.get("transfer_amount") or 0),
        transfer_type=parsed.get("transfer_type"),
        content=parsed.get("content"),
        raw_payload=str(parsed.get("raw_payload") or "{}"),
    )
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        dup = (
            db.query(SepayPaymentTransaction)
            .filter(SepayPaymentTransaction.sepay_transaction_id == tx_id)
            .first()
        )
        logger.info("sepay_webhook_duplicate_race transaction_id=%s", tx_id)
        return dup, False, "duplicate"

    logger.info(
        "sepay_webhook_recorded transaction_id=%s order_code=%s amount=%s",
        tx_id,
        row.order_code,
        row.transfer_amount,
    )
    return row, True, "created"


def sepay_transaction_to_dict(row: SepayPaymentTransaction) -> dict[str, Any]:
    return {
        "id": row.id,
        "sepay_transaction_id": row.sepay_transaction_id,
        "order_code": row.order_code,
        "account_number": row.account_number,
        "transfer_amount": row.transfer_amount,
        "transfer_type": row.transfer_type,
        "content": row.content,
        "raw_payload": row.raw_payload,
        "created_at": row.created_at,
    }


def _expected_account_number() -> str:
    return billing_bank_account()


def _normalize_account_number(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _is_incoming_transfer(parsed: dict[str, Any]) -> bool:
    ttype = str(parsed.get("transfer_type") or "").strip().lower()
    # SePay official: transferType = "in" | "out". Also accept common aliases.
    if not ttype:
        # Some test / gateway mocks omit type — treat as incoming when amount > 0.
        return int(parsed.get("transfer_amount") or 0) > 0
    return ttype in ("in", "incoming", "credit", "deposit", "receive", "received")


def _account_matches(parsed: dict[str, Any]) -> bool:
    expected = _normalize_account_number(_expected_account_number())
    actual = _normalize_account_number(parsed.get("account_number"))
    if not expected:
        return False
    return actual == expected


def process_sepay_webhook(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Full SePay webhook business logic.
    Always returns a result dict; caller should respond {"success": true} after auth.
    """
    parsed = parse_sepay_webhook_payload(payload)
    tx_id = parsed.get("sepay_transaction_id")
    transfer_amount = int(parsed.get("transfer_amount") or 0)

    if not tx_id:
        logger.warning("sepay_webhook_skip missing_transaction_id payload=%s", json.dumps(payload)[:500])
        return {"handled": False, "reason": "missing_transaction_id"}

    existing = (
        db.query(SepayPaymentTransaction)
        .filter(SepayPaymentTransaction.sepay_transaction_id == tx_id)
        .first()
    )
    if existing is not None:
        logger.info("sepay_webhook_skip_duplicate transaction_id=%s", tx_id)
        return {"handled": False, "reason": "duplicate", "transaction_id": tx_id}

    if not _is_incoming_transfer(parsed):
        logger.info(
            "sepay_webhook_skip_transfer_type transaction_id=%s transfer_type=%s",
            tx_id,
            parsed.get("transfer_type"),
        )
        record_sepay_webhook(db, payload)
        db.flush()
        return {"handled": False, "reason": "not_incoming"}

    if not _account_matches(parsed):
        logger.warning(
            "sepay_webhook_skip_wrong_account transaction_id=%s account_number=%s expected=%s",
            tx_id,
            parsed.get("account_number"),
            _expected_account_number(),
        )
        record_sepay_webhook(db, payload)
        db.flush()
        return {"handled": False, "reason": "wrong_account"}

    order_code = parsed.get("order_code")
    order = get_fulfillable_payment_order_by_code(db, order_code) if order_code else None
    if order is None:
        logger.warning(
            "sepay_webhook_no_pending_order transaction_id=%s order_code=%s amount=%s",
            tx_id,
            order_code,
            transfer_amount,
        )
        record_sepay_webhook(db, payload)
        db.flush()
        return {"handled": False, "reason": "order_not_found", "order_code": order_code}

    prev_status = str(order.status or "")
    order_code_val = str(order.order_code or "")

    if transfer_amount < int(order.amount):
        logger.warning(
            "sepay_webhook_partial_payment transaction_id=%s order_code=%s transfer=%s required=%s",
            tx_id,
            order.order_code,
            transfer_amount,
            order.amount,
        )
        mark_payment_order_partial_paid(db, order)
        record_sepay_webhook(db, payload)
        db.flush()
        return {
            "handled": True,
            "reason": "partial_paid",
            "order_code": order.order_code,
            "transfer_amount": transfer_amount,
            "required_amount": int(order.amount),
        }

    # Full payment — record first for idempotency before activation side effects.
    tx_row, created, status = record_sepay_webhook(db, payload)
    if status == "duplicate":
        return {"handled": False, "reason": "duplicate", "transaction_id": tx_id}

    now = datetime.now(timezone.utc)
    mark_payment_order_paid(db, order, at=now)
    logger.info(
        "sepay_webhook_order_status_change order_code=%s transaction_id=%s reference=%s "
        "amount=%s prev_status=%s new_status=paid product_code=%s user_id=%s",
        order_code_val,
        tx_id,
        parsed.get("content") or "",
        transfer_amount,
        prev_status,
        order.product_code,
        order.user_id,
    )

    activation: dict[str, Any] | None = None
    subscription_id: int | None = None
    try:
        activation = activate_product(
            db,
            user_id=int(order.user_id),
            product_code=str(order.product_code),
            order_id=int(order.id),
        )
        subscription_id = activation.get("subscription_id")
    except ProductActivationError:
        logger.error(
            "sepay_activate_product_failed order_id=%s user_id=%s product_code=%s activation_status=%s err=%s",
            order.id,
            order.user_id,
            order.product_code,
            order.activation_status,
            order.activation_error,
        )
        db.flush()
        return {
            "handled": True,
            "reason": "activation_failed",
            "order_code": order.order_code,
            "transaction_id": tx_id,
            "activation_error": order.activation_error,
            "status": "paid",
            "activation_status": order.activation_status,
        }

    plan_id = None
    product = activation or {}
    if product.get("kind") == "subscription" and subscription_id:
        from app.services import plan_service
        from app.services.seoauto_pricing_catalog import get_billing_product_by_code

        bp = get_billing_product_by_code(order.product_code)
        if bp and bp.get("plan_slug"):
            pl = plan_service.get_plan_by_slug(db, str(bp["plan_slug"]))
            plan_id = pl.id if pl else None

    existing_pay_tx = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.provider == "sepay",
            PaymentTransaction.provider_transaction_id == str(tx_id),
        )
        .first()
    )
    if existing_pay_tx is not None:
        pay_tx = existing_pay_tx
    else:
        pay_tx = PaymentTransaction(
            user_id=int(order.user_id),
            subscription_id=int(subscription_id) if subscription_id else None,
            plan_id=int(plan_id) if plan_id else None,
            amount=transfer_amount,
            currency="VND",
            status="paid",
            provider="sepay",
            provider_transaction_id=str(tx_id),
            provider_payload_json=json.dumps(payload, ensure_ascii=False),
            paid_at=now,
        )
        db.add(pay_tx)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            pay_tx = (
                db.query(PaymentTransaction)
                .filter(
                    PaymentTransaction.provider == "sepay",
                    PaymentTransaction.provider_transaction_id == str(tx_id),
                )
                .first()
            )
            if pay_tx is None:
                logger.exception(
                    "sepay_payment_transaction_insert_failed transaction_id=%s order_code=%s",
                    tx_id,
                    order.order_code,
                )

    if pay_tx is not None:
        try:
            on_payment_completed(
                db,
                user_id=int(order.user_id),
                net_amount=transfer_amount,
                payment_transaction_id=int(pay_tx.id),
                subscription_id=int(subscription_id) if subscription_id else None,
                invoice_id=str(order.order_code),
            )
        except Exception:
            logger.exception(
                "sepay_affiliate_hook_failed order_code=%s payment_transaction_id=%s",
                order.order_code,
                pay_tx.id,
            )

    logger.info(
        "sepay_webhook_paid order_code=%s transaction_id=%s user_id=%s product_code=%s",
        order.order_code,
        tx_id,
        order.user_id,
        order.product_code,
    )
    return {
        "handled": True,
        "reason": "paid",
        "order_code": order.order_code,
        "transaction_id": tx_id,
        "sepay_row_id": tx_row.id if tx_row else None,
        "payment_transaction_id": pay_tx.id if pay_tx else None,
        "activation": activation,
        "status": "paid",
        "activation_status": order.activation_status,
    }
