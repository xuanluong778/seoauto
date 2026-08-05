"""SePay webhook: store event → verify order → lock → fulfill once → same-txn commit."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction
from app.models.sepay_payment_transaction import SepayPaymentTransaction
from app.models.sepay_webhook_event import SepayWebhookEvent
from app.services.affiliate_payment_hooks import on_payment_completed
from app.services.payment_activation_service import ProductActivationError, activate_product
from app.services.payment_config import billing_bank_account
from app.services.payment_order_service import (
    get_payment_order_by_code_any_status,
    mark_payment_order_paid,
    mark_payment_order_partial_paid,
)

logger = logging.getLogger(__name__)

_ORDER_CODE_RE = re.compile(
    r"SEOA[\s\-_.]*(\d{4})[\s\-_.]*(\d{2})[\s\-_.]*(\d{2})[\s\-_.]*(\d+)",
    re.IGNORECASE,
)
_ORDER_CODE_COMPACT_RE = re.compile(r"(SEOA[0-9A-Z]+)", re.IGNORECASE)

TERMINAL_EVENT_STATUSES = frozenset({"processed", "skipped"})


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
            if isinstance(raw, str):
                cleaned = raw.replace(",", "").replace(" ", "").strip()
                return int(float(cleaned))
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return 0


def extract_order_code_from_content(content: str | None) -> str | None:
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
    claim_code = _normalize_order_code(
        _pick_str(payload, "order_code", "orderCode", "code", "payment_code", "paymentCode")
    )
    content_code = extract_order_code_from_content(content)
    # Explicit code field preferred; transfer content is fallback only.
    # If both differ, keep both for DB resolution — do not trust free-form text over claim alone.
    order_code = claim_code or content_code
    if claim_code and content_code and claim_code != content_code:
        logger.warning(
            "sepay_order_code_mismatch claim=%s content=%s — will prefer DB-matching code",
            claim_code,
            content_code,
        )

    return {
        "sepay_transaction_id": _normalize_tx_id(payload),
        "order_code": order_code,
        "claim_order_code": claim_code,
        "content_order_code": content_code,
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


def build_idempotency_key(payload: dict[str, Any], parsed: dict[str, Any] | None = None) -> str:
    parsed = parsed or parse_sepay_webhook_payload(payload)
    tx_id = parsed.get("sepay_transaction_id")
    if tx_id:
        return f"sepay:tx:{tx_id}"[:128]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]
    return f"sepay:body:{digest}"[:128]


def _expected_account_number() -> str:
    return billing_bank_account()


def _normalize_account_number(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _is_incoming_transfer(parsed: dict[str, Any]) -> bool:
    ttype = str(parsed.get("transfer_type") or "").strip().lower()
    if not ttype:
        return int(parsed.get("transfer_amount") or 0) > 0
    return ttype in ("in", "incoming", "credit", "deposit", "receive", "received")


def _account_matches(parsed: dict[str, Any]) -> bool:
    expected = _normalize_account_number(_expected_account_number())
    actual = _normalize_account_number(parsed.get("account_number"))
    if not expected:
        return False
    return actual == expected


def store_raw_webhook_event(
    db: Session,
    payload: dict[str, Any],
    *,
    raw_body: bytes | str | None = None,
) -> tuple[SepayWebhookEvent, bool]:
    """
    Persist raw webhook BEFORE business processing.
    Returns (event, is_new). Unique on idempotency_key.
    """
    parsed = parse_sepay_webhook_payload(payload)
    key = build_idempotency_key(payload, parsed)
    existing = (
        db.query(SepayWebhookEvent)
        .filter(SepayWebhookEvent.idempotency_key == key)
        .one_or_none()
    )
    if existing is not None:
        return existing, False

    if raw_body is not None:
        if isinstance(raw_body, bytes):
            raw_text = raw_body.decode("utf-8", errors="replace")
        else:
            raw_text = str(raw_body)
    else:
        raw_text = str(parsed.get("raw_payload") or json.dumps(payload, ensure_ascii=False))

    row = SepayWebhookEvent(
        idempotency_key=key,
        provider_transaction_id=(parsed.get("sepay_transaction_id") or None),
        order_code=parsed.get("order_code"),
        transfer_amount=int(parsed.get("transfer_amount") or 0),
        process_status="received",
        raw_payload=raw_text[:_MAX_RAW],
    )
    db.add(row)
    try:
        with db.begin_nested():
            db.flush()
        return row, True
    except IntegrityError:
        db.expire_all()
        existing = (
            db.query(SepayWebhookEvent)
            .filter(SepayWebhookEvent.idempotency_key == key)
            .one_or_none()
        )
        if existing is None:
            raise
        return existing, False


_MAX_RAW = 100_000


def _mark_event(
    event: SepayWebhookEvent,
    *,
    status: str,
    result_code: str | None = None,
    failure_reason: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    event.process_status = status
    event.result_code = (result_code or "")[:64] or None
    event.failure_reason = (failure_reason or "")[:512] or None
    if result is not None:
        event.result_json = json.dumps(result, ensure_ascii=False)[:8000]
    if status in ("processed", "failed", "skipped"):
        event.processed_at = datetime.now(timezone.utc)


def record_sepay_webhook(
    db: Session,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    process_status: str = "recorded",
    failure_reason: str | None = None,
) -> tuple[SepayPaymentTransaction | None, bool, str]:
    """Insert sepay_payment_transactions row (secondary ledger of provider txs)."""
    parsed = parse_sepay_webhook_payload(payload)
    tx_id = parsed.get("sepay_transaction_id")
    if not tx_id:
        return None, False, "missing_transaction_id"

    existing = (
        db.query(SepayPaymentTransaction)
        .filter(SepayPaymentTransaction.sepay_transaction_id == tx_id)
        .first()
    )
    if existing is not None:
        return existing, False, "duplicate"

    key = idempotency_key or build_idempotency_key(payload, parsed)
    row = SepayPaymentTransaction(
        sepay_transaction_id=tx_id,
        order_code=parsed.get("order_code"),
        account_number=parsed.get("account_number"),
        transfer_amount=int(parsed.get("transfer_amount") or 0),
        transfer_type=parsed.get("transfer_type"),
        content=parsed.get("content"),
        raw_payload=str(parsed.get("raw_payload") or "{}"),
        process_status=process_status,
        failure_reason=(failure_reason or None),
        idempotency_key=key[:128],
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
        return dup, False, "duplicate"
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
        "process_status": getattr(row, "process_status", None),
        "failure_reason": getattr(row, "failure_reason", None),
        "created_at": row.created_at,
    }


def process_sepay_webhook(
    db: Session,
    payload: dict[str, Any],
    *,
    raw_body: bytes | str | None = None,
) -> dict[str, Any]:
    """
    Full SePay webhook:
      1) store raw event (idempotent)
      2) if already terminal → success without re-run
      3) validate transfer / account
      4) lock order FOR UPDATE; verify amount against DB order
      5) payment + subscription/credits + ledger in same session (caller commits)
    """
    parsed = parse_sepay_webhook_payload(payload)
    tx_id = parsed.get("sepay_transaction_id")
    transfer_amount = int(parsed.get("transfer_amount") or 0)

    event, is_new = store_raw_webhook_event(db, payload, raw_body=raw_body)
    db.flush()

    if not is_new and str(event.process_status or "") in TERMINAL_EVENT_STATUSES:
        logger.info(
            "sepay_webhook_already_terminal event_id=%s status=%s key=%s",
            event.id,
            event.process_status,
            event.idempotency_key,
        )
        return {
            "handled": False,
            "reason": "already_processed",
            "event_id": event.id,
            "process_status": event.process_status,
            "result_code": event.result_code,
            "transaction_id": tx_id,
            "replay": True,
        }

    # Allow reprocess only for received/processing/failed (not processed/skipped)
    event.process_status = "processing"
    db.flush()

    if not tx_id:
        _mark_event(event, status="failed", result_code="missing_transaction_id", failure_reason="missing_transaction_id")
        return {"handled": False, "reason": "missing_transaction_id", "event_id": event.id}

    if not _is_incoming_transfer(parsed):
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="skipped", failure_reason="not_incoming")
        _mark_event(event, status="skipped", result_code="not_incoming")
        return {"handled": False, "reason": "not_incoming", "event_id": event.id, "transaction_id": tx_id}

    if not _account_matches(parsed):
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="skipped", failure_reason="wrong_account")
        _mark_event(event, status="skipped", result_code="wrong_account", failure_reason="wrong_account")
        return {"handled": False, "reason": "wrong_account", "event_id": event.id, "transaction_id": tx_id}

    order_code = parsed.get("order_code")
    if not order_code:
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="failed", failure_reason="missing_order_code")
        _mark_event(event, status="failed", result_code="missing_order_code", failure_reason="missing_order_code")
        return {"handled": False, "reason": "missing_order_code", "event_id": event.id}

    # Trust only order rows in DB — never activate from free-form amount/content alone
    candidates: list[str] = []
    for c in (parsed.get("claim_order_code"), parsed.get("content_order_code"), order_code):
        if c and str(c) not in candidates:
            candidates.append(str(c))
    order = None
    for code in candidates:
        order = get_payment_order_by_code_any_status(db, code, for_update=True)
        if order is not None:
            order_code = str(order.order_code or code)
            break
    if order is None:
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="failed", failure_reason="order_not_found")
        _mark_event(event, status="failed", result_code="order_not_found", failure_reason=f"order_not_found:{order_code}")
        return {"handled": False, "reason": "order_not_found", "order_code": order_code, "event_id": event.id}

    # Already paid + activated → no re-run of business
    if str(order.status) == "paid" and str(order.activation_status or "") == "activated":
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="skipped", failure_reason="order_already_paid")
        _mark_event(
            event,
            status="skipped",
            result_code="order_already_paid",
            result={"order_code": order.order_code, "status": "paid"},
        )
        return {
            "handled": False,
            "reason": "order_already_paid",
            "order_code": order.order_code,
            "event_id": event.id,
            "replay": True,
        }

    if str(order.status) not in ("pending", "partial_paid", "expired"):
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="skipped", failure_reason=f"order_status_{order.status}")
        _mark_event(event, status="skipped", result_code="order_not_fulfillable", failure_reason=str(order.status))
        return {
            "handled": False,
            "reason": "order_not_fulfillable",
            "order_status": order.status,
            "order_code": order.order_code,
            "event_id": event.id,
        }

    required = int(order.amount)
    # Do not trust webhook amount without order comparison
    if transfer_amount <= 0:
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="failed", failure_reason="invalid_amount")
        _mark_event(event, status="failed", result_code="invalid_amount", failure_reason="transfer_amount<=0")
        return {"handled": False, "reason": "invalid_amount", "event_id": event.id}

    if transfer_amount < required:
        mark_payment_order_partial_paid(db, order)
        record_sepay_webhook(db, payload, idempotency_key=event.idempotency_key, process_status="partial", failure_reason="partial_paid")
        _mark_event(
            event,
            status="processed",
            result_code="partial_paid",
            result={"transfer_amount": transfer_amount, "required_amount": required},
        )
        return {
            "handled": True,
            "reason": "partial_paid",
            "order_code": order.order_code,
            "transfer_amount": transfer_amount,
            "required_amount": required,
            "event_id": event.id,
        }

    # Full payment (≥ required) — record provider tx then fulfill in same transaction
    tx_row, created, status = record_sepay_webhook(
        db,
        payload,
        idempotency_key=event.idempotency_key,
        process_status="processing",
    )
    if status == "duplicate" and tx_row is not None and str(getattr(tx_row, "process_status", "") or "") == "processed":
        _mark_event(event, status="skipped", result_code="duplicate", failure_reason="duplicate_provider_tx")
        return {"handled": False, "reason": "duplicate", "transaction_id": tx_id, "event_id": event.id, "replay": True}

    now = datetime.now(timezone.utc)
    prev_status = str(order.status or "")
    mark_payment_order_paid(db, order, at=now)

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
    except ProductActivationError as exc:
        # Keep payment+activation bookkeeping in same txn; surface FAILED on event
        if tx_row is not None:
            tx_row.process_status = "failed"
            tx_row.failure_reason = (str(getattr(order, "activation_error", None) or exc) or "activation_failed")[:512]
        _mark_event(
            event,
            status="failed",
            result_code="activation_failed",
            failure_reason=str(getattr(order, "activation_error", None) or exc)[:512],
            result={"order_code": order.order_code, "status": "paid"},
        )
        logger.error(
            "sepay_activate_product_failed order_id=%s err=%s",
            order.id,
            order.activation_error,
        )
        return {
            "handled": True,
            "reason": "activation_failed",
            "order_code": order.order_code,
            "transaction_id": tx_id,
            "event_id": event.id,
            "status": "paid",
            "activation_status": order.activation_status,
            "activation_error": order.activation_error,
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

    # Record payment_transactions with unique (provider, provider_transaction_id)
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
        # Ledger amount must match order.amount (not free-form overpay trust for bookkeeping)
        pay_amount = int(order.amount)
        pay_tx = PaymentTransaction(
            user_id=int(order.user_id),
            subscription_id=int(subscription_id) if subscription_id else None,
            plan_id=int(plan_id) if plan_id else None,
            amount=pay_amount,
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

    if pay_tx is not None:
        try:
            on_payment_completed(
                db,
                user_id=int(order.user_id),
                net_amount=int(order.amount),
                payment_transaction_id=int(pay_tx.id),
                subscription_id=int(subscription_id) if subscription_id else None,
                invoice_id=str(order.order_code),
            )
        except Exception:
            logger.exception("sepay_affiliate_hook_failed order_code=%s", order.order_code)

    if tx_row is not None:
        tx_row.process_status = "processed"
        tx_row.failure_reason = None

    result = {
        "handled": True,
        "reason": "paid",
        "order_code": order.order_code,
        "transaction_id": tx_id,
        "sepay_row_id": tx_row.id if tx_row else None,
        "payment_transaction_id": pay_tx.id if pay_tx else None,
        "activation": activation,
        "status": "paid",
        "activation_status": order.activation_status,
        "event_id": event.id,
        "prev_status": prev_status,
    }
    _mark_event(event, status="processed", result_code="paid", result=result)
    logger.info(
        "sepay_webhook_paid order_code=%s transaction_id=%s user_id=%s product=%s",
        order.order_code,
        tx_id,
        order.user_id,
        order.product_code,
    )
    return result
