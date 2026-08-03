"""User-facing billing overview — plan, credits, quotas, history (no admin economics)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CreditLedgerEntry
from app.models.user import User
from app.services.credit_cost_registry import DEFAULT_CREDIT_COSTS, list_credit_cost_catalog
from app.services.credits import get_available_balance, public_credit_transaction_note
from app.services.payment_order_service import list_payment_orders_for_user
from app.services.plan_quota_service import user_quota_snapshot
from app.services.free_usage_service import free_usage_plan_label
from app.services.saas_user_service import build_saas_me_response
from app.services.seoauto_pricing_catalog import billing_product_display_name, get_billing_product_by_code
from app.services.usage_tracking_service import current_usage_month

EXPIRING_SOON_DAYS = 30
LOW_CREDIT_THRESHOLD = 100
QUOTA_WARN_REMAINING_RATIO = 0.2

SOURCE_TYPE_LABELS_VI: dict[str, str] = {
    "monthly_bonus": "Credit gói (tháng)",
    "plan_monthly": "Credit gói (tháng)",
    "purchased": "Credit đã mua",
    "admin_adjustment": "Điều chỉnh",
    "refund": "Hoàn credit",
}

MODULE_LABELS_VI: dict[str, str] = {
    "content_ai": "Content AI",
    "cau": "Content Auto Update",
    "keyword": "Keyword Research",
    "audit": "Technical Audit",
    "seo_score": "SEO Score",
    "chatbot_cskh": "Chatbot CSKH",
    "chatbot": "Chatbot SEO",
    "lead_scanner": "Lead Scanner",
    "legacy": "Khác",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _month_start(usage_month: str) -> datetime:
    year, month = usage_month.split("-", 1)
    return datetime(int(year), int(month), 1, tzinfo=timezone.utc)


def _action_label_map(db: Session) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in list_credit_cost_catalog(db=db):
        mod = str(row.get("module") or "").strip().lower()
        act = str(row.get("action") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        if mod and act and label:
            out[(mod, act)] = label
    for row in DEFAULT_CREDIT_COSTS:
        mod = str(row.get("module") or "").strip().lower()
        act = str(row.get("action") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        if mod and act and label and (mod, act) not in out:
            out[(mod, act)] = label
    return out


def _module_label(module: str | None) -> str:
    mod = str(module or "").strip().lower()
    if not mod:
        return "Khác"
    return MODULE_LABELS_VI.get(mod, mod.replace("_", " ").title())


def _transaction_label(row: CreditLedger, labels: dict[tuple[str, str], str]) -> str:
    mod = str(getattr(row, "module", "") or "").strip().lower()
    act = str(getattr(row, "action", "") or "").strip().lower()
    if mod and act:
        hit = labels.get((mod, act))
        if hit:
            return hit
    if mod:
        return _module_label(mod)
    reason = str(getattr(row, "reason", "") or "").strip()
    return reason.replace("_", " ").title() if reason else "Trừ credit"


def _expiring_credit_buckets(db: Session, user_id: int) -> list[dict[str, Any]]:
    now = _utc_now()
    horizon = now + timedelta(days=EXPIRING_SOON_DAYS)
    rows = (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.remaining_amount > 0,
            CreditLedgerEntry.expired_at.isnot(None),
            CreditLedgerEntry.expired_at > now,
            CreditLedgerEntry.expired_at <= horizon,
        )
        .order_by(CreditLedgerEntry.expired_at.asc())
        .limit(20)
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        exp = row.expired_at
        if exp and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        days_left = max(0, (exp - now).days) if exp else None
        out.append(
            {
                "amount": int(row.remaining_amount or 0),
                "source_type": str(row.source_type or ""),
                "source_label": SOURCE_TYPE_LABELS_VI.get(
                    str(row.source_type or "").strip().lower(),
                    str(row.source_type or "credit"),
                ),
                "expired_at": exp,
                "days_left": days_left,
            }
        )
    return out


def _module_credit_usage_month(
    db: Session, user_id: int, usage_month: str
) -> list[dict[str, Any]]:
    start = _month_start(usage_month)
    rows = (
        db.query(
            CreditLedger.module,
            func.coalesce(func.sum(CreditLedger.credit_used), 0).label("total"),
        )
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.delta < 0,
            CreditLedger.created_at >= start,
        )
        .group_by(CreditLedger.module)
        .order_by(desc("total"))
        .all()
    )
    items: list[dict[str, Any]] = []
    for mod, total in rows:
        used = int(total or 0)
        if used <= 0:
            continue
        items.append(
            {
                "module": str(mod or "legacy"),
                "label": _module_label(str(mod or "")),
                "credits_used": used,
            }
        )
    return items


def _credit_deduction_history(
    db: Session, user_id: int, *, limit: int, labels: dict[tuple[str, str], str]
) -> list[dict[str, Any]]:
    rows = (
        db.query(CreditLedger)
        .filter(CreditLedger.user_id == int(user_id), CreditLedger.delta < 0)
        .order_by(desc(CreditLedger.id))
        .limit(max(1, min(limit, 100)))
        .all()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        note = public_credit_transaction_note(row)
        out.append(
            {
                "id": int(row.id),
                "delta": int(row.delta or 0),
                "credit_used": int(row.credit_used or abs(int(row.delta or 0))),
                "balance_after": int(row.balance_after or 0),
                "module": getattr(row, "module", None),
                "action": getattr(row, "action", None),
                "label": _transaction_label(row, labels),
                "note": note,
                "created_at": row.created_at,
            }
        )
    return out


def _quota_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q in snapshot.get("quotas") or []:
        limit = q.get("limit")
        used = int(q.get("used") or 0)
        remaining = q.get("remaining")
        if limit is None or int(limit) <= 0:
            continue
        lim = int(limit)
        rem = int(remaining) if remaining is not None else max(0, lim - used)
        pct_used = round(min(100.0, (used / lim) * 100.0), 1) if lim > 0 else 0.0
        warn = rem <= max(1, int(lim * QUOTA_WARN_REMAINING_RATIO))
        rows.append(
            {
                "key": q.get("key"),
                "feature_key": q.get("feature_key"),
                "label": q.get("label") or q.get("key"),
                "limit": lim,
                "used": used,
                "remaining": rem,
                "percent_used": pct_used,
                "warning": warn,
            }
        )
    return rows


def _build_alerts(
    *,
    credit_balance: int,
    expiring: list[dict[str, Any]],
    quotas: list[dict[str, Any]],
    top_module: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if credit_balance <= 0:
        alerts.append(
            {
                "level": "danger",
                "code": "credit_empty",
                "message": "Bạn đã hết credit. Mua thêm credit hoặc nâng cấp gói để tiếp tục dùng tính năng trả phí.",
            }
        )
    elif credit_balance < LOW_CREDIT_THRESHOLD:
        alerts.append(
            {
                "level": "warn",
                "code": "credit_low",
                "message": f"Credit còn {credit_balance:,} — sắp hết. Cân nhắc mua thêm credit.",
            }
        )
    urgent = [b for b in expiring if b.get("days_left") is not None and int(b["days_left"]) <= 7]
    if urgent:
        total = sum(int(b.get("amount") or 0) for b in urgent)
        alerts.append(
            {
                "level": "warn",
                "code": "credit_expiring",
                "message": f"Có {total:,} credit sẽ hết hạn trong 7 ngày tới.",
            }
        )
    for q in quotas:
        if q.get("warning"):
            label = q.get("label") or q.get("key")
            rem = q.get("remaining")
            alerts.append(
                {
                    "level": "warn",
                    "code": "quota_low",
                    "message": f"Quota «{label}» còn {rem} / {q.get('limit')} trong tháng này.",
                }
            )
    if top_module and int(top_module.get("credits_used") or 0) >= 50:
        alerts.append(
            {
                "level": "info",
                "code": "top_module",
                "message": f"Tháng này bạn dùng nhiều credit nhất cho «{top_module.get('label')}» ({int(top_module['credits_used']):,} credit).",
            }
        )
    return alerts


def _payment_history(db: Session, user_id: int, *, limit: int) -> list[dict[str, Any]]:
    orders = list_payment_orders_for_user(db, user_id=user_id, limit=limit)
    out: list[dict[str, Any]] = []
    for order in orders:
        product = get_billing_product_by_code(str(order.product_code or ""))
        product_name = billing_product_display_name(product) if product else str(order.product_code or "")
        out.append(
            {
                "order_code": order.order_code,
                "product_code": order.product_code,
                "product_name": product_name,
                "amount": int(order.amount or 0),
                "status": str(order.status or ""),
                "paid_at": order.paid_at,
                "created_at": order.created_at,
                "activation_status": order.activation_status,
            }
        )
    return out


def build_billing_overview(db: Session, user: User, *, history_limit: int = 50) -> dict[str, Any]:
    """Aggregate plan, credit, quota, and payment data for account billing UI."""
    from app.services.monthly_bonus_credit_service import credit_wallet_breakdown

    saas = build_saas_me_response(db, user)
    usage_month = current_usage_month()
    wallet = credit_wallet_breakdown(db, user.id, plan_slug=saas.plan_slug)
    balance = int(wallet.get("available_credit") or 0)
    labels = _action_label_map(db)
    expiring = wallet.get("credit_expiring_soon") or _expiring_credit_buckets(db, user.id)
    module_usage = _module_credit_usage_month(db, user.id, usage_month)
    top_module = module_usage[0] if module_usage else None
    quota_snapshot = user_quota_snapshot(db, user)
    quotas = _quota_rows(quota_snapshot)
    alerts = _build_alerts(
        credit_balance=balance,
        expiring=expiring,
        quotas=quotas,
        top_module=top_module,
    )
    if saas.free_usage_active:
        alerts.insert(
            0,
            {
                "level": "info",
                "code": "free_usage",
                "message": saas.free_usage_banner or free_usage_plan_label(saas.free_usage_days_remaining),
            },
        )
        if saas.needs_credit_for_features and saas.free_usage_need_credit_message:
            alerts.insert(
                1,
                {
                    "level": "warn",
                    "code": "free_usage_need_credit",
                    "message": saas.free_usage_need_credit_message,
                },
            )
    locked = int(wallet.get("locked_credit") or 0)
    if locked > 0 and wallet.get("locked_message"):
        alerts.insert(
            0,
            {
                "level": "warn",
                "code": "credit_locked",
                "message": str(wallet["locked_message"]),
            },
        )
    total_module_credits = sum(int(m.get("credits_used") or 0) for m in module_usage)
    if top_module and total_module_credits > 0:
        top_module = {
            **top_module,
            "share_percent": round(
                (int(top_module["credits_used"]) / total_module_credits) * 100.0, 1
            ),
        }

    return {
        "usage_month": usage_month,
        "plan_slug": saas.plan_slug,
        "plan_name": saas.plan_name,
        "subscription_status": saas.subscription_status,
        "trial_status": saas.trial_status,
        "trial_message": saas.trial_message,
        "current_period_start": saas.current_period_start,
        "current_period_end": saas.current_period_end,
        "byok_note": saas.byok_note,
        "credit_balance": balance,
        "available_credit": balance,
        "locked_credit": locked,
        "purchased_credit": int(wallet.get("purchased_credit") or 0),
        "renewal_grant_preview": wallet.get("renewal_grant_preview"),
        "locked_message": wallet.get("locked_message"),
        "has_active_subscription": wallet.get("has_active_subscription"),
        "credit_wallet": wallet,
        "credit_expiring_soon": expiring,
        "module_credit_usage": module_usage,
        "top_credit_module": top_module,
        "quotas": quotas,
        "credit_history": _credit_deduction_history(db, user.id, limit=history_limit, labels=labels),
        "payment_history": _payment_history(db, user.id, limit=30),
        "alerts": alerts,
        "low_credit_threshold": LOW_CREDIT_THRESHOLD,
        "free_usage_active": saas.free_usage_active,
        "free_usage_days_remaining": saas.free_usage_days_remaining,
        "free_usage_expires_at": saas.free_usage_expires_at,
        "free_usage_banner": saas.free_usage_banner,
        "needs_credit_for_features": saas.needs_credit_for_features,
        "free_usage_need_credit_message": saas.free_usage_need_credit_message,
    }
