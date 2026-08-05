"""Payment / SePay reconciliation — detect unpaid fulfillment gaps and webhook anomalies."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.payment_order import PaymentOrder
from app.models.sepay_webhook_event import SepayWebhookEvent
from app.services.payment_activation_service import activate_product, ProductActivationError

_LOG = logging.getLogger(__name__)


def _credit_ledger_for_order(db: Session, order_id: int) -> bool:
    """True if a credit ledger/entry mentions this order_id (plan cycle or pack)."""
    try:
        from app.models.credit_ledger_entry import CreditLedgerEntry

        note_pat = f"%order_id={int(order_id)}%"
        row = (
            db.query(CreditLedgerEntry.id)
            .filter(CreditLedgerEntry.note.ilike(note_pat))
            .first()
        )
        if row:
            return True
    except Exception:
        pass
    try:
        from app.models.credit_ledger import CreditLedger

        note_pat = f"%order_id={int(order_id)}%"
        row = (
            db.query(CreditLedger.id)
            .filter(CreditLedger.note.ilike(note_pat))
            .first()
        )
        if row:
            return True
    except Exception:
        pass
    return False


def find_paid_without_plan(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    """Orders marked paid whose plan products are not activated."""
    rows = (
        db.query(PaymentOrder)
        .filter(
            PaymentOrder.status == "paid",
            or_(
                PaymentOrder.activation_status.is_(None),
                PaymentOrder.activation_status != "activated",
            ),
        )
        .order_by(PaymentOrder.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for o in rows:
        out.append(
            {
                "order_id": o.id,
                "order_code": o.order_code,
                "user_id": o.user_id,
                "product_code": o.product_code,
                "activation_status": o.activation_status,
                "activation_error": o.activation_error,
                "issue": "paid_without_plan_activation",
            }
        )
    return out


def find_activated_without_ledger(db: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    """Plan/credit products activated but missing credit ledger marker for order."""
    from app.services.seoauto_pricing_catalog import get_billing_product_by_code

    rows = (
        db.query(PaymentOrder)
        .filter(
            PaymentOrder.status == "paid",
            PaymentOrder.activation_status == "activated",
        )
        .order_by(PaymentOrder.id.desc())
        .limit(limit * 3)
        .all()
    )
    out = []
    for o in rows:
        bp = get_billing_product_by_code(str(o.product_code or ""))
        if not bp:
            continue
        kind = str(bp.get("kind") or bp.get("type") or "")
        # Only products that should create credit ledger
        needs_credit = kind in ("plan", "subscription", "credit_pack", "credits") or str(
            o.product_code or ""
        ).upper().startswith(("STARTER", "PRO", "AGENCY", "BUSINESS", "CREDIT_"))
        if not needs_credit:
            continue
        if _credit_ledger_for_order(db, int(o.id)):
            continue
        out.append(
            {
                "order_id": o.id,
                "order_code": o.order_code,
                "user_id": o.user_id,
                "product_code": o.product_code,
                "issue": "activated_without_credit_ledger",
            }
        )
        if len(out) >= limit:
            break
    return out


def find_webhook_errors_and_duplicates(db: Session, *, hours: int = 72, limit: int = 200) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    failed = (
        db.query(SepayWebhookEvent)
        .filter(
            SepayWebhookEvent.process_status == "failed",
            SepayWebhookEvent.received_at >= since,
        )
        .order_by(SepayWebhookEvent.id.desc())
        .limit(limit)
        .all()
    )
    out = [
        {
            "event_id": e.id,
            "idempotency_key": e.idempotency_key,
            "provider_transaction_id": e.provider_transaction_id,
            "order_code": e.order_code,
            "process_status": e.process_status,
            "failure_reason": e.failure_reason,
            "issue": "webhook_failed",
        }
        for e in failed
    ]

    # Duplicate-ish: same provider_transaction_id with multiple events (should not happen if unique key)
    dup_q = (
        db.query(
            SepayWebhookEvent.provider_transaction_id,
            func.count(SepayWebhookEvent.id),
        )
        .filter(
            SepayWebhookEvent.provider_transaction_id.isnot(None),
            SepayWebhookEvent.received_at >= since,
        )
        .group_by(SepayWebhookEvent.provider_transaction_id)
        .having(func.count(SepayWebhookEvent.id) > 1)
        .limit(limit)
        .all()
    )
    for tx_id, cnt in dup_q:
        out.append(
            {
                "provider_transaction_id": tx_id,
                "event_count": int(cnt),
                "issue": "webhook_duplicate_events",
            }
        )
    return out


def reconcile_payments(
    db: Session,
    *,
    try_repair: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Scan for payment inconsistencies. Optionally re-run activation for paid+not-activated.
    """
    paid_no_plan = find_paid_without_plan(db, limit=limit)
    activated_no_ledger = find_activated_without_ledger(db, limit=limit)
    webhook_issues = find_webhook_errors_and_duplicates(db, limit=limit)

    repaired: list[dict[str, Any]] = []
    if try_repair:
        for item in paid_no_plan[:limit]:
            order = db.get(PaymentOrder, int(item["order_id"]))
            if order is None:
                continue
            try:
                activate_product(
                    db,
                    user_id=int(order.user_id),
                    product_code=str(order.product_code),
                    order_id=int(order.id),
                )
                repaired.append({"order_id": order.id, "result": "reactivated"})
            except ProductActivationError as exc:
                repaired.append({"order_id": order.id, "result": "failed", "error": str(exc)[:200]})
            except Exception as exc:  # noqa: BLE001
                _LOG.exception("reconcile repair failed order_id=%s", order.id)
                repaired.append({"order_id": order.id, "result": "error", "error": type(exc).__name__})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paid_without_plan": paid_no_plan,
        "activated_without_ledger": activated_no_ledger,
        "webhook_issues": webhook_issues,
        "counts": {
            "paid_without_plan": len(paid_no_plan),
            "activated_without_ledger": len(activated_no_ledger),
            "webhook_issues": len(webhook_issues),
        },
        "repaired": repaired,
        "ok": not paid_no_plan and not activated_no_ledger and not any(
            i.get("issue") == "webhook_failed" for i in webhook_issues
        ),
    }
    _LOG.info(
        "payment_reconcile counts=%s ok=%s",
        report["counts"],
        report["ok"],
    )
    return report


def run_payment_reconciliation_job(*, try_repair: bool = False) -> dict[str, Any]:
    # Register relationship targets so mapper configure succeeds outside FastAPI
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.payment_order  # noqa: F401
    import app.models.sepay_webhook_event  # noqa: F401
    import app.models.credit_ledger  # noqa: F401
    import app.models.credit_ledger_entry  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.affiliate  # noqa: F401
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        report = reconcile_payments(db, try_repair=try_repair)
        if try_repair:
            db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
