"""SaaS economics — credit burn, ước tính chi phí provider, doanh thu & lợi nhuận."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.payment_order import PaymentOrder
from app.models.saas_economics import SaasEconomicsConfig, SaasEconomicsState
from app.models.user import User
from app.services.billing_vat import billing_vat_percent
from app.services.credit_cost_registry import REASON_TO_MODULE_ACTION

_LOG = logging.getLogger("saas_economics")

DEFAULT_ECONOMICS_SETTINGS: dict[str, Any] = {
    "daily_cost_threshold_vnd": 5_000_000,
    "monthly_cost_threshold_vnd": 80_000_000,
    "usd_to_vnd": 25_000,
    "vnd_per_credit": {
        "openai": 250,
        "anthropic": 300,
        "dataforseo": 180,
        "google_places": 200,
        "google_cse": 150,
        "crawl": 50,
        "other": 100,
    },
    "auto_block_expensive_api": True,
    "alert_cooldown_hours": 6,
    "at_risk_burn_credits": 800,
    "at_risk_cost_revenue_ratio": 1.5,
}

EXPENSIVE_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "dataforseo",
        "google_places",
        "google_cse",
    }
)

_PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "dataforseo": "DataForSEO",
    "google_places": "Google Places",
    "google_cse": "Google CSE / Image",
    "crawl": "Crawl / Technical",
    "other": "Khác",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day_start(dt: datetime | None = None) -> datetime:
    ref = dt or _utc_now()
    return ref.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(dt: datetime | None = None) -> datetime:
    ref = dt or _utc_now()
    return ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def load_economics_settings(db: Session) -> dict[str, Any]:
    row = db.get(SaasEconomicsConfig, "settings")
    if row is None or not row.value_json:
        return dict(DEFAULT_ECONOMICS_SETTINGS)
    try:
        data = json.loads(row.value_json)
    except (TypeError, json.JSONDecodeError):
        data = {}
    merged = dict(DEFAULT_ECONOMICS_SETTINGS)
    merged.update({k: v for k, v in data.items() if v is not None})
    vpc = dict(DEFAULT_ECONOMICS_SETTINGS["vnd_per_credit"])
    vpc.update((data.get("vnd_per_credit") or {}))
    merged["vnd_per_credit"] = vpc
    return merged


def save_economics_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = load_economics_settings(db)
    for key, val in patch.items():
        if key == "vnd_per_credit" and isinstance(val, dict):
            merged_vpc = dict(current.get("vnd_per_credit") or {})
            merged_vpc.update(val)
            current["vnd_per_credit"] = merged_vpc
        elif val is not None:
            current[key] = val
    row = db.get(SaasEconomicsConfig, "settings")
    payload = json.dumps(current, ensure_ascii=False)
    if row is None:
        db.add(SaasEconomicsConfig(key="settings", value_json=payload))
    else:
        row.value_json = payload
    db.flush()
    return current


def get_economics_state(db: Session) -> SaasEconomicsState:
    state = db.get(SaasEconomicsState, 1)
    if state is None:
        state = SaasEconomicsState(id=1, expensive_api_blocked=False)
        db.add(state)
        db.flush()
    return state


def provider_for_ledger(*, module: str | None, action: str | None, reason: str | None) -> str:
    mod = (module or "").strip().lower()
    act = (action or "").strip().lower()
    if not mod and reason:
        mod, act = REASON_TO_MODULE_ACTION.get(str(reason), ("legacy", str(reason)[:64]))
        mod = mod.lower()
        act = act.lower()
    if mod in ("keyword",):
        return "dataforseo"
    if mod in ("lead_scanner",):
        return "google_places"
    if mod == "content_ai" and act in ("google_image",):
        return "google_cse"
    if mod == "content_ai" and act in ("ai_image",):
        return "openai"
    if mod in ("wordpress",):
        return "other"
    if mod in ("index",):
        return "other"
    if mod in ("embedding",):
        return "openai"
    if mod in ("audit", "seo_score", "crawl"):
        return "crawl"
    if mod in ("content_ai", "cau", "chatbot", "chatbot_cskh"):
        if "anthropic" in act or "claude" in act:
            return "anthropic"
        return "openai"
    return "other"


def _ledger_credit_used(row: CreditLedger) -> int:
    if row.credit_used is not None and int(row.credit_used) > 0:
        return int(row.credit_used)
    if int(row.delta) < 0:
        return abs(int(row.delta))
    return 0


def _burn_query(db: Session, *, since: datetime):
    return (
        db.query(CreditLedger)
        .filter(CreditLedger.created_at >= since, CreditLedger.delta < 0)
        .yield_per(500)
    )


def _sum_burn_credits(rows: list[CreditLedger]) -> int:
    return sum(_ledger_credit_used(r) for r in rows)


def _estimate_cost_vnd(credits: int, provider: str, settings: dict[str, Any]) -> int:
    vpc = settings.get("vnd_per_credit") or {}
    rate = int(vpc.get(provider) or vpc.get("other") or 100)
    return int(credits) * max(0, rate)


def _aggregate_burn(
    db: Session,
    *,
    since: datetime,
    settings: dict[str, Any],
) -> dict[str, Any]:
    rows = list(_burn_query(db, since=since))
    total_credits = _sum_burn_credits(rows)

    by_provider: dict[str, int] = {}
    by_module: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_user: dict[int, int] = {}

    for row in rows:
        used = _ledger_credit_used(row)
        if used <= 0:
            continue
        prov = provider_for_ledger(module=row.module, action=row.action, reason=row.reason)
        mod = (row.module or "").strip() or provider_for_ledger(
            module=None, action=None, reason=row.reason
        ).split("_")[0]
        if row.module:
            mod = row.module
        elif row.reason:
            mod = REASON_TO_MODULE_ACTION.get(row.reason, ("legacy", row.reason))[0]
        act = (row.action or row.reason or "unknown").strip()
        by_provider[prov] = by_provider.get(prov, 0) + used
        by_module[mod] = by_module.get(mod, 0) + used
        key_ma = f"{mod}:{act}"
        by_action[key_ma] = by_action.get(key_ma, 0) + used
        by_user[int(row.user_id)] = by_user.get(int(row.user_id), 0) + used

    by_org: dict[int, int] = {}
    for row in rows:
        used = _ledger_credit_used(row)
        if used <= 0:
            continue
        oid = getattr(row, "organization_id", None)
        if oid:
            by_org[int(oid)] = by_org.get(int(oid), 0) + used

    provider_rows = []
    total_cost = 0
    for prov, cred in sorted(by_provider.items(), key=lambda x: -x[1]):
        cost = _estimate_cost_vnd(cred, prov, settings)
        total_cost += cost
        provider_rows.append(
            {
                "provider": prov,
                "label": _PROVIDER_LABELS.get(prov, prov),
                "credits": cred,
                "estimated_cost_vnd": cost,
            }
        )

    module_rows = [
        {"module": k, "credits": v}
        for k, v in sorted(by_module.items(), key=lambda x: -x[1])[:30]
    ]
    action_rows = []
    for key_ma, cred in sorted(by_action.items(), key=lambda x: -x[1])[:40]:
        mod, _, act = key_ma.partition(":")
        action_rows.append({"module": mod, "action": act, "credits": cred})

    return {
        "credits": total_credits,
        "estimated_cost_vnd": total_cost,
        "by_provider": provider_rows,
        "by_module": module_rows,
        "by_action": action_rows,
        "by_user_raw": by_user,
        "by_org_raw": by_org,
    }


def _is_credit_pack_product(code: str) -> bool:
    c = str(code or "").strip().upper()
    return c.startswith("CREDIT_") or c.startswith("ARTICLE_ADDON_")


def _is_subscription_product(code: str) -> bool:
    c = str(code or "").strip().upper()
    if _is_credit_pack_product(c):
        return False
    return c.endswith("_M") or c.endswith("_Y")


def _revenue_base_from_amount(amount: int) -> int:
    pct = billing_vat_percent()
    if pct <= 0:
        return int(amount)
    return int(round(int(amount) / (1 + pct / 100.0)))


def _aggregate_revenue(db: Session, *, since: datetime) -> dict[str, int]:
    q = (
        db.query(PaymentOrder.product_code, func.coalesce(func.sum(PaymentOrder.amount), 0))
        .filter(
            PaymentOrder.status == "paid",
            PaymentOrder.paid_at.isnot(None),
            PaymentOrder.paid_at >= since,
        )
        .group_by(PaymentOrder.product_code)
    )
    sub_gross = sub_base = pack_gross = pack_base = 0
    for code, gross in q.all():
        gross_i = int(gross or 0)
        base = _revenue_base_from_amount(gross_i)
        if _is_credit_pack_product(str(code)):
            pack_gross += gross_i
            pack_base += base
        elif _is_subscription_product(str(code)):
            sub_gross += gross_i
            sub_base += base
    return {
        "subscription_gross_vnd": sub_gross,
        "subscription_base_vnd": sub_base,
        "credit_pack_gross_vnd": pack_gross,
        "credit_pack_base_vnd": pack_base,
        "total_gross_vnd": sub_gross + pack_gross,
        "total_base_vnd": sub_base + pack_base,
    }


def _user_revenue_map(db: Session, *, since: datetime) -> dict[int, int]:
    q = (
        db.query(PaymentOrder.user_id, func.coalesce(func.sum(PaymentOrder.amount), 0))
        .filter(
            PaymentOrder.status == "paid",
            PaymentOrder.paid_at.isnot(None),
            PaymentOrder.paid_at >= since,
        )
        .group_by(PaymentOrder.user_id)
    )
    return {int(uid): _revenue_base_from_amount(int(gross or 0)) for uid, gross in q.all()}


def _build_at_risk_users(
    db: Session,
    *,
    burn_by_user: dict[int, int],
    settings: dict[str, Any],
    since: datetime,
) -> list[dict[str, Any]]:
    min_burn = int(settings.get("at_risk_burn_credits") or 800)
    ratio = float(settings.get("at_risk_cost_revenue_ratio") or 1.5)
    revenue_map = _user_revenue_map(db, since=since)
    risky: list[dict[str, Any]] = []
    if not burn_by_user:
        return risky

    user_ids = list(burn_by_user.keys())
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    for uid, credits in sorted(burn_by_user.items(), key=lambda x: -x[1]):
        if credits < min_burn:
            continue
        prov_cost = 0
        user_rows = (
            db.query(CreditLedger)
            .filter(
                CreditLedger.user_id == uid,
                CreditLedger.created_at >= since,
                CreditLedger.delta < 0,
            )
            .all()
        )
        for row in user_rows:
            used = _ledger_credit_used(row)
            if used <= 0:
                continue
            prov = provider_for_ledger(module=row.module, action=row.action, reason=row.reason)
            prov_cost += _estimate_cost_vnd(used, prov, settings)
        revenue = int(revenue_map.get(uid, 0))
        if revenue <= 0 or prov_cost >= revenue * ratio:
            user = users.get(uid)
            risky.append(
                {
                    "user_id": uid,
                    "email": user.email if user else f"user#{uid}",
                    "credits_burned": credits,
                    "estimated_cost_vnd": prov_cost,
                    "revenue_base_vnd": revenue,
                    "risk_score": round(prov_cost / max(revenue, 1), 2),
                }
            )
    risky.sort(key=lambda x: (-x["estimated_cost_vnd"], -x["credits_burned"]))
    return risky[:25]


def _build_alerts(
    *,
    settings: dict[str, Any],
    daily_cost: int,
    monthly_cost: int,
    state: SaasEconomicsState,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    daily_th = int(settings.get("daily_cost_threshold_vnd") or 0)
    monthly_th = int(settings.get("monthly_cost_threshold_vnd") or 0)
    if daily_th > 0 and daily_cost >= daily_th:
        alerts.append(
            {
                "level": "critical" if daily_cost >= daily_th * 1.2 else "warning",
                "period": "daily",
                "message": f"Chi phí ước tính hôm nay {daily_cost:,} VND vượt ngưỡng {daily_th:,} VND.",
                "estimated_cost_vnd": daily_cost,
                "threshold_vnd": daily_th,
            }
        )
    if monthly_th > 0 and monthly_cost >= monthly_th:
        alerts.append(
            {
                "level": "critical" if monthly_cost >= monthly_th * 1.1 else "warning",
                "period": "monthly",
                "message": f"Chi phí ước tính tháng này {monthly_cost:,} VND vượt ngưỡng {monthly_th:,} VND.",
                "estimated_cost_vnd": monthly_cost,
                "threshold_vnd": monthly_th,
            }
        )
    if state.expensive_api_blocked:
        alerts.append(
            {
                "level": "critical",
                "period": "system",
                "message": state.block_reason or "API đắt đang bị chặn toàn hệ thống.",
                "blocked_at": state.blocked_at.isoformat() if state.blocked_at else None,
            }
        )
    return alerts


def build_economics_dashboard(db: Session) -> dict[str, Any]:
    settings = load_economics_settings(db)
    state = get_economics_state(db)
    now = _utc_now()
    day_from = _day_start(now)
    month_from = _month_start(now)

    daily = _aggregate_burn(db, since=day_from, settings=settings)
    monthly = _aggregate_burn(db, since=month_from, settings=settings)
    rev_day = _aggregate_revenue(db, since=day_from)
    rev_month = _aggregate_revenue(db, since=month_from)

    profit_day = rev_day["total_base_vnd"] - daily["estimated_cost_vnd"]
    profit_month = rev_month["total_base_vnd"] - monthly["estimated_cost_vnd"]

    def _gm(rev: int, cost: int) -> float | None:
        if int(rev) <= 0:
            return None
        return round((int(rev) - int(cost)) / float(rev), 4)

    top_orgs: list[dict[str, Any]] = []
    org_raw = monthly.get("by_org_raw") or {}
    for oid in sorted(org_raw, key=lambda k: org_raw[k], reverse=True)[:10]:
        top_orgs.append({"organization_id": int(oid), "credits": int(org_raw[oid])})

    at_risk = _build_at_risk_users(
        db,
        burn_by_user=monthly["by_user_raw"],
        settings=settings,
        since=month_from,
    )

    top_users: list[dict[str, Any]] = []
    if monthly["by_user_raw"]:
        uids = sorted(monthly["by_user_raw"], key=lambda k: monthly["by_user_raw"][k], reverse=True)[:15]
        users = {u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()}
        for uid in uids:
            cred = monthly["by_user_raw"][uid]
            user = users.get(uid)
            top_users.append(
                {
                    "user_id": uid,
                    "email": user.email if user else f"user#{uid}",
                    "credits": cred,
                }
            )

    alerts = _build_alerts(
        settings=settings,
        daily_cost=daily["estimated_cost_vnd"],
        monthly_cost=monthly["estimated_cost_vnd"],
        state=state,
    )

    return {
        "generated_at": now.isoformat(),
        "period": {
            "day_start": day_from.isoformat(),
            "month_start": month_from.isoformat(),
        },
        "settings": settings,
        "expensive_api_blocked": bool(state.expensive_api_blocked),
        "block_reason": state.block_reason,
        "blocked_at": state.blocked_at.isoformat() if state.blocked_at else None,
        "credit_burn": {
            "today": daily["credits"],
            "month": monthly["credits"],
        },
        "estimated_cost_vnd": {
            "today": daily["estimated_cost_vnd"],
            "month": monthly["estimated_cost_vnd"],
        },
        "by_provider": {
            "today": daily["by_provider"],
            "month": monthly["by_provider"],
        },
        "by_module": {
            "today": daily["by_module"],
            "month": monthly["by_module"],
        },
        "by_action": {
            "today": daily["by_action"],
            "month": monthly["by_action"],
        },
        "by_user": {
            "today": top_users[:10],
            "month": top_users,
        },
        "revenue": {
            "today": rev_day,
            "month": rev_month,
        },
        "profit_vnd": {
            "today": profit_day,
            "month": profit_month,
        },
        "gross_margin_pct": {
            "today": _gm(rev_day["total_base_vnd"], daily["estimated_cost_vnd"]),
            "month": _gm(rev_month["total_base_vnd"], monthly["estimated_cost_vnd"]),
            "target": 0.70,
        },
        "by_org": {
            "month": top_orgs,
        },
        "at_risk_users": at_risk,
        "alerts": alerts,
        "dataforseo_usage": _safe_dataforseo_usage(db),
    }


def _safe_dataforseo_usage(db: Session) -> dict[str, Any]:
    try:
        from app.services.dataforseo_billing_service import admin_dataforseo_cost_summary

        return admin_dataforseo_cost_summary(db)
    except Exception:
        return {"today": {}, "month": {}, "by_action_month": []}


def evaluate_thresholds_and_block(db: Session, *, trigger: str = "periodic") -> dict[str, Any]:
    """Kiểm tra ngưỡng; bật chặn API đắt nếu cấu hình cho phép."""
    settings = load_economics_settings(db)
    state = get_economics_state(db)
    now = _utc_now()
    day_from = _day_start(now)
    month_from = _month_start(now)

    daily = _aggregate_burn(db, since=day_from, settings=settings)
    monthly = _aggregate_burn(db, since=month_from, settings=settings)
    daily_cost = int(daily["estimated_cost_vnd"])
    monthly_cost = int(monthly["estimated_cost_vnd"])
    daily_th = int(settings.get("daily_cost_threshold_vnd") or 0)
    monthly_th = int(settings.get("monthly_cost_threshold_vnd") or 0)
    auto_block = bool(settings.get("auto_block_expensive_api", True))

    exceeded_daily = daily_th > 0 and daily_cost >= daily_th
    exceeded_monthly = monthly_th > 0 and monthly_cost >= monthly_th
    should_block = auto_block and (exceeded_daily or exceeded_monthly)

    changed = False
    if should_block and not state.expensive_api_blocked:
        reason_parts = []
        if exceeded_daily:
            reason_parts.append(f"ngày {daily_cost:,}/{daily_th:,} VND")
        if exceeded_monthly:
            reason_parts.append(f"tháng {monthly_cost:,}/{monthly_th:,} VND")
        state.expensive_api_blocked = True
        state.block_reason = "Vượt ngưỡng chi phí: " + ", ".join(reason_parts)
        state.blocked_at = now
        changed = True
        _LOG.warning(
            "saas_economics_auto_block trigger=%s daily_cost_vnd=%s monthly_cost_vnd=%s",
            trigger,
            daily_cost,
            monthly_cost,
        )
    elif not should_block and state.expensive_api_blocked and auto_block:
        state.expensive_api_blocked = False
        state.block_reason = None
        state.blocked_at = None
        changed = True
        _LOG.info("saas_economics_auto_unblock trigger=%s", trigger)

    cooldown_h = int(settings.get("alert_cooldown_hours") or 6)
    cooldown = timedelta(hours=max(1, cooldown_h))
    if exceeded_daily:
        last = _as_utc_aware(state.last_alert_daily_at)
        if last is None or (now - last) >= cooldown:
            state.last_alert_daily_at = now
            _LOG.warning(
                "saas_economics_daily_threshold_exceeded cost_vnd=%s threshold_vnd=%s",
                daily_cost,
                daily_th,
            )
    if exceeded_monthly:
        last = _as_utc_aware(state.last_alert_monthly_at)
        if last is None or (now - last) >= cooldown:
            state.last_alert_monthly_at = now
            _LOG.warning(
                "saas_economics_monthly_threshold_exceeded cost_vnd=%s threshold_vnd=%s",
                monthly_cost,
                monthly_th,
            )

    if changed:
        db.flush()

    return {
        "blocked": bool(state.expensive_api_blocked),
        "changed": changed,
        "daily_cost_vnd": daily_cost,
        "monthly_cost_vnd": monthly_cost,
        "exceeded_daily": exceeded_daily,
        "exceeded_monthly": exceeded_monthly,
    }


def clear_expensive_api_block(db: Session, *, admin_note: str | None = None) -> SaasEconomicsState:
    state = get_economics_state(db)
    state.expensive_api_blocked = False
    state.block_reason = admin_note or None
    state.blocked_at = None
    db.flush()
    _LOG.info("saas_economics_manual_unblock note=%s", (admin_note or "")[:120])
    return state


def is_expensive_provider(provider: str | object) -> bool:
    val = getattr(provider, "value", provider)
    return str(val or "").lower() in EXPENSIVE_PROVIDERS
