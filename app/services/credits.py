"""
Per-user credits: optional enforcement via CREDITS_ENABLED=1.

Grant buckets live in credit_ledger_entries (remaining_amount, expired_at, source_type).
user.credit_balance is a denormalized cache of available credits.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.models.credit_ledger import CreditLedger
from app.models.credit_ledger_entry import CREDIT_SOURCE_TYPES, CreditLedgerEntry
from app.models.user import User

logger = logging.getLogger(__name__)

from app.services.saas_hybrid_pricing import PLAN_MONTHLY_BONUS_CREDITS

REASON_TO_SOURCE_TYPE: dict[str, str] = {
    "signup_bonus": "trial",
    "admin_grant": "admin_grant",
    "plan_activation_bonus": "monthly_bonus",
    "monthly_bonus_grant": "monthly_bonus",
    "plan_monthly_refresh": "monthly_bonus",
    "credit_pack_purchase": "purchased",
    "refund": "refund",
    "failed_refund": "refund",
    "legacy_balance_migration": "admin_grant",
}

_LEGACY_SOURCE_ALIASES: dict[str, str] = {
    "plan_monthly": "monthly_bonus",
    "admin_adjustment": "admin_grant",
}


def credits_enforced() -> bool:
    return os.getenv("CREDITS_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


_DEFAULT_CREDIT_PACKAGES: list[dict[str, str | int | None]] = [
    {
        "id": "trial",
        "name": "Dùng thử",
        "credits": 200,
        "description": "Mức gần với credit đăng ký (SIGNUP_CREDIT_BONUS). Thử keyword research & clustering.",
        "price_hint": "Theo tài khoản mới",
    },
    {
        "id": "lite",
        "name": "Lite",
        "credits": 2000,
        "description": "Ví dụ ~400 lần research nếu CREDIT_COST_RESEARCH_RUN=5.",
        "price_hint": "Liên hệ admin",
    },
    {
        "id": "pro",
        "name": "Pro",
        "credits": 10000,
        "description": "Phù hợp agency / volume cao.",
        "price_hint": "Liên hệ admin",
    },
]


def public_credit_packages() -> list[dict[str, str | int | None]]:
    raw = (os.getenv("CREDIT_PACKAGES_JSON") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list) and data:
            out: list[dict[str, str | int | None]] = []
            for i, row in enumerate(data):
                if not isinstance(row, dict):
                    continue
                pid = str(row.get("id") or f"pkg{i}").strip()[:64]
                name = str(row.get("name") or pid).strip()[:120]
                if not pid or not name:
                    continue
                try:
                    cred = int(row.get("credits", 0))
                except (TypeError, ValueError):
                    cred = 0
                cred = max(0, cred)
                desc = str(row.get("description") or "").strip()[:2000]
                ph = row.get("price_hint")
                hint = str(ph).strip()[:200] if ph is not None and str(ph).strip() else None
                out.append({"id": pid, "name": name, "credits": cred, "description": desc, "price_hint": hint})
            if out:
                return out
    return [dict(x) for x in _DEFAULT_CREDIT_PACKAGES]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _registry_cost(module: str, action: str, *, db: Session | None = None, from_cache: bool = False) -> int:
    from app.services.credit_cost_registry import resolve_credit_cost

    return resolve_credit_cost(module, action, db=db, from_cache=from_cache)


def cost_research_run(*, db: Session | None = None, from_cache: bool = False) -> int:
    if from_cache:
        return _registry_cost("keyword", "research_cache", db=db, from_cache=False)
    return _registry_cost("keyword", "research_run", db=db, from_cache=False)


def cost_volume_per_keyword() -> int:
    return max(0, _int_env("CREDIT_COST_VOLUME_PER_KEYWORD", 0))


def volume_batch_charge(keyword_count: int, *, db: Session | None = None, from_cache: bool = False) -> int:
    from app.services.credit_cost_registry import volume_batch_charge_from_registry

    return volume_batch_charge_from_registry(keyword_count, db=db, from_cache=from_cache)


def cost_cluster_sync(*, db: Session | None = None) -> int:
    return _registry_cost("keyword", "cluster_sync", db=db)


def cost_cluster_async(*, db: Session | None = None) -> int:
    return _registry_cost("keyword", "cluster_async", db=db)


def cost_cluster_save(*, db: Session | None = None) -> int:
    return _registry_cost("keyword", "cluster_save", db=db)


def cost_content_ai_article(*, word_count: int | None = None, db: Session | None = None) -> int:
    from app.services.credit_cost_registry import content_ai_action_for_word_count, resolve_credit_cost

    act = content_ai_action_for_word_count(word_count)
    return resolve_credit_cost("content_ai", act, db=db)


def cost_chatbot_internal_links(*, db: Session | None = None) -> int:
    return _registry_cost("chatbot", "internal_links", db=db)


def cost_chatbot_images(*, db: Session | None = None) -> int:
    return _registry_cost("chatbot", "images_bundle", db=db)


def cost_chatbot_google_image(*, db: Session | None = None) -> int:
    return _registry_cost("content_ai", "google_image", db=db)


def cost_chatbot_ai_image(*, db: Session | None = None) -> int:
    return _registry_cost("content_ai", "ai_image", db=db)


def cost_chatbot_cskh_reply(*, db: Session | None = None) -> int:
    return _registry_cost("chatbot_cskh", "reply_overage", db=db)


def estimate_chatbot_workflow_credits(
    *,
    include_internal_links: bool = False,
    include_images: bool = False,
    image_source: str | None = None,
    word_count: int | None = None,
) -> dict[str, int]:
    """Ước tính credit cho workflow chatbot keyword_cluster_to_article."""
    from app.services.content_ai_image_rules import image_credit_slots, normalize_image_source

    research = cost_research_run()
    clustering = cost_cluster_sync()
    content_ai = cost_content_ai_article()
    internal_links = cost_chatbot_internal_links() if include_internal_links else 0

    src = normalize_image_source(image_source, include_images=include_images)
    slots = image_credit_slots(word_count) if src in ("google", "ai") else 0
    if src == "google":
        images_google = slots * cost_chatbot_google_image()
        images_ai = 0
    elif src == "ai":
        images_google = 0
        images_ai = slots * cost_chatbot_ai_image()
    else:
        images_google = 0
        images_ai = 0

    images = images_google + images_ai
    if images <= 0 and include_images and not image_source:
        images = cost_chatbot_images()

    return {
        "research": research,
        "clustering": clustering,
        "content_ai": content_ai,
        "internal_links": internal_links,
        "images": images,
        "images_google": images_google,
        "images_ai": images_ai,
        "image_slots": slots,
        "total": research + clustering + content_ai + internal_links + images,
    }


def estimate_quick_write_credits(
    *,
    include_images: bool = False,
    image_source: str | None = None,
    word_count: int | None = None,
) -> dict[str, int]:
    """Ước tính credit viết nhanh (không research / gom cụm)."""
    from app.services.content_ai_image_rules import image_credit_slots, normalize_image_source

    content_ai = cost_content_ai_article()
    src = normalize_image_source(image_source, include_images=include_images)
    slots = image_credit_slots(word_count) if src in ("google", "ai") else 0
    if src == "google":
        images_google = slots * cost_chatbot_google_image()
        images_ai = 0
    elif src == "ai":
        images_google = 0
        images_ai = slots * cost_chatbot_ai_image()
    else:
        images_google = 0
        images_ai = 0
    images = images_google + images_ai
    return {
        "research": 0,
        "clustering": 0,
        "content_ai": content_ai,
        "internal_links": 0,
        "images": images,
        "images_google": images_google,
        "images_ai": images_ai,
        "image_slots": slots,
        "total": content_ai + images,
    }


def consume_quick_write_credits(
    db: Session,
    *,
    user_id: int,
    primary_keyword: str,
    workflow_id: str,
    include_images: bool = False,
    image_source: str | None = None,
    word_count: int | None = None,
) -> dict[str, int]:
    """Trừ credit viết nhanh. Caller phải commit."""
    est = estimate_quick_write_credits(
        include_images=include_images,
        image_source=image_source,
        word_count=word_count,
    )
    if not credits_enforced():
        return {**est, "charged": False}

    note_base = f"wf={workflow_id[:32]};kw={primary_keyword[:120]};mode=quick"
    if est["content_ai"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["content_ai"],
            reason="chatbot_quick_write_content_ai",
            note=note_base,
        )
    if est.get("images_google", 0) > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["images_google"],
            reason="chatbot_quick_write_images_google",
            note=note_base,
        )
    if est.get("images_ai", 0) > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["images_ai"],
            reason="chatbot_quick_write_images_ai",
            note=note_base,
        )
    return {**est, "charged": True}


def consume_chatbot_workflow_credits(
    db: Session,
    *,
    user_id: int,
    primary_keyword: str,
    workflow_id: str,
    include_internal_links: bool = False,
    include_images: bool = False,
    image_source: str | None = None,
    word_count: int | None = None,
) -> dict[str, int]:
    """Trừ credit theo từng hạng mục workflow. Caller phải commit."""
    est = estimate_chatbot_workflow_credits(
        include_internal_links=include_internal_links,
        include_images=include_images,
        image_source=image_source,
        word_count=word_count,
    )
    if not credits_enforced():
        return {**est, "charged": False}

    note_base = f"wf={workflow_id[:32]};kw={primary_keyword[:120]}"
    if est["research"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["research"],
            reason="chatbot_workflow_research",
            note=note_base,
        )
    if est["clustering"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["clustering"],
            reason="chatbot_workflow_cluster",
            note=note_base,
        )
    if est["content_ai"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["content_ai"],
            reason="chatbot_workflow_content_ai",
            note=note_base,
        )
    if include_internal_links and est["internal_links"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["internal_links"],
            reason="chatbot_workflow_internal_links",
            note=note_base,
        )
    if est["images"] > 0:
        consume_credits(
            db,
            user_id=user_id,
            amount=est["images"],
            reason="chatbot_workflow_images",
            note=note_base,
        )
    return {**est, "charged": True}


def ensure_sufficient_credits(db: Session, user_id: int, required: int) -> tuple[int, bool]:
    """Trả (balance khả dụng, sufficient). Chỉ tính credit active — không gồm locked."""
    if not credits_enforced() or required <= 0:
        balance = get_available_balance(db, user_id)
        return balance, True
    from app.services.monthly_bonus_credit_service import sync_subscription_credit_locks

    sync_subscription_credit_locks(db, user_id)
    balance = get_available_balance(db, user_id)
    return balance, balance >= required


def cost_import_excel(*, db: Session | None = None) -> int:
    return _registry_cost("keyword", "import_excel", db=db)


def cost_analyze_project(*, db: Session | None = None) -> int:
    return _registry_cost("audit", "analyze_project", db=db)


def cost_technical_analyze(*, db: Session | None = None) -> int:
    return _registry_cost("audit", "technical_deep", db=db)


def cost_technical_quick_audit(*, db: Session | None = None) -> int:
    return _registry_cost("audit", "technical_quick", db=db)


def cost_technical_deep_audit(*, db: Session | None = None) -> int:
    return _registry_cost("audit", "technical_deep", db=db)


def cost_technical_single_url(*, db: Session | None = None) -> int:
    return _registry_cost("audit", "technical_single_url", db=db)


def cost_url_seo_scoreboard(*, db: Session | None = None) -> int:
    return _registry_cost("seo_score", "url_scoreboard", db=db)


def cost_seo_score_ai_fix(*, db: Session | None = None) -> int:
    return _registry_cost("seo_score", "ai_fix", db=db)


def cost_schema_generate(*, db: Session | None = None) -> int:
    return _registry_cost("schema", "generate", db=db)


def cost_content_seo_score(*, db: Session | None = None) -> int:
    return _registry_cost("seo_score", "content_score", db=db)


def cost_cau_seo_ai_fix(*, db: Session | None = None, from_cache: bool = False) -> int:
    return _registry_cost("cau", "seo_ai_fix", db=db, from_cache=from_cache)


def cost_content_ai_brief_suggest(*, db: Session | None = None) -> int:
    return _registry_cost("content_ai", "brief_suggest", db=db)


def cost_lead_scan_search(*, db: Session | None = None, from_cache: bool = False) -> int:
    return _registry_cost("lead_scanner", "basic_scan", db=db, from_cache=from_cache)


def cost_lead_place_detail(*, db: Session | None = None) -> int:
    return _registry_cost("lead_scanner", "place_detail", db=db)


def cost_lead_geocode(*, db: Session | None = None) -> int:
    return _registry_cost("lead_scanner", "geocode", db=db)


def cost_lead_export(*, db: Session | None = None) -> int:
    return _registry_cost("lead_scanner", "export", db=db)


def quote_lead_basic_scan(*, mode: str, limit: int, from_cache: bool = False, db: Session | None = None) -> dict[str, int]:
    """Ước tính credit quét cơ bản (không gồm Place Details)."""
    if from_cache:
        scan_cost = cost_lead_scan_search(db=db, from_cache=True)
        return {
            "credit_required": scan_cost,
            "from_cache": 1,
            "geocode_calls": 0,
            "search_pages": 0,
            "detail_calls": 0,
            "geocode_cost": 0,
            "search_cost": scan_cost,
            "detail_cost": 0,
        }
    lim = max(20, min(100, int(limit or 20)))
    if lim not in (20, 50, 100):
        lim = 20 if lim <= 30 else (50 if lim <= 75 else 100)
    search_pages = (lim + 19) // 20
    geocode = cost_lead_geocode(db=db) if str(mode or "").strip().lower() == "category" else 0
    per_page = cost_lead_scan_search(db=db, from_cache=False)
    search_cost = search_pages * per_page
    total = geocode + search_cost
    return {
        "credit_required": total,
        "from_cache": 0,
        "geocode_calls": 1 if geocode else 0,
        "search_pages": search_pages,
        "detail_calls": 0,
        "geocode_cost": geocode,
        "search_cost": search_cost,
        "detail_cost": 0,
    }


def quote_lead_detail(count: int = 1, *, db: Session | None = None) -> dict[str, int]:
    n = max(1, min(100, int(count or 1)))
    per = cost_lead_place_detail(db=db)
    return {
        "credit_required": n * per,
        "detail_calls": n,
        "detail_cost": n * per,
    }


def quote_lead_scan_credits(*, mode: str, limit: int) -> dict[str, int]:
    """Backward-compatible alias — chỉ quét cơ bản."""
    return quote_lead_basic_scan(mode=mode, limit=limit, from_cache=False)


def signup_bonus() -> int:
    return max(0, _int_env("SIGNUP_CREDIT_BONUS", 0))


def admin_grant_secret() -> str:
    return (os.getenv("CREDITS_ADMIN_SECRET") or "").strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _end_of_month(dt: datetime | None = None) -> datetime:
    now = _aware(dt) or _utc_now()
    last_day = calendar.monthrange(now.year, now.month)[1]
    return now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)


def _current_period_key(dt: datetime | None = None) -> str:
    now = _aware(dt) or _utc_now()
    return f"{now.year:04d}-{now.month:02d}"


def _user_query_for_update(db: Session, user_id: int):
    q = db.query(User).filter(User.id == user_id)
    if db.bind is not None and db.bind.dialect.name != "sqlite":
        q = q.with_for_update()
    return q


def _normalize_source_type(source_type: str | None, reason: str | None = None) -> str:
    st = str(source_type or "").strip().lower()
    if st in _LEGACY_SOURCE_ALIASES:
        st = _LEGACY_SOURCE_ALIASES[st]
    if st in CREDIT_SOURCE_TYPES:
        return st
    mapped = REASON_TO_SOURCE_TYPE.get(str(reason or "").strip().lower())
    if mapped:
        return mapped
    return "admin_grant"


def _active_buckets_query(db: Session, user_id: int):
    now = _utc_now()
    return (
        db.query(CreditLedgerEntry)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.remaining_amount > 0,
            CreditLedgerEntry.status == "active",
        )
        .filter(
            (CreditLedgerEntry.expired_at.is_(None))
            | (CreditLedgerEntry.expired_at > now)
        )
        .order_by(
            case((CreditLedgerEntry.expired_at.is_(None), 1), else_=0),
            CreditLedgerEntry.expired_at.asc(),
            CreditLedgerEntry.id.asc(),
        )
    )


def get_available_balance(db: Session, user_id: int, *, sync: bool = True) -> int:
    """Sum remaining_amount from non-expired buckets."""
    rows = _active_buckets_query(db, user_id).all()
    total = sum(int(r.remaining_amount or 0) for r in rows)
    if sync:
        user = db.query(User).filter(User.id == int(user_id)).one_or_none()
        if user is not None and int(user.credit_balance or 0) != total:
            user.credit_balance = total
            db.flush()
    return total


def _sync_user_balance(db: Session, user: User) -> int:
    total = get_available_balance(db, user.id, sync=False)
    user.credit_balance = total
    db.flush()
    return total


def _append_consumption_log(
    db: Session,
    *,
    user_id: int,
    amount: int,
    balance_after: int,
    reason: str,
    note: str | None,
    module: str | None = None,
    action: str | None = None,
    request_id: str | None = None,
    source: str | None = None,
) -> None:
    from app.services.credit_cost_registry import REASON_TO_MODULE_ACTION

    mod = (module or "").strip().lower() or None
    act = (action or "").strip().lower() or None
    if not mod or not act:
        mapped = REASON_TO_MODULE_ACTION.get(str(reason or "").strip().lower())
        if mapped:
            mod, act = mapped
    db.add(
        CreditLedger(
            user_id=user_id,
            delta=-int(amount),
            balance_after=int(balance_after),
            reason=reason[:64],
            note=(note or "")[:2000] or None,
            module=mod,
            action=act,
            credit_used=max(0, int(amount)),
            request_id=(request_id or "")[:64] or None,
            source=(source or "")[:32] or None,
        )
    )


def grant_credits(
    db: Session,
    *,
    user_id: int,
    amount: int,
    reason: str,
    note: str | None = None,
    grant_reason: str | None = None,
    internal_note: str | None = None,
    admin_id: int | None = None,
    expires_at: datetime | None = None,
    expired_at: datetime | None = None,
    source_type: str | None = None,
) -> int:
    """
    Add a grant bucket. Caller must commit.
    expires_at is accepted as alias for expired_at (backward compat).
    For admin grants: grant_reason = lý do tặng (user-visible), internal_note = ghi chú nội bộ.
    """
    expiry = expired_at if expired_at is not None else expires_at
    st = _normalize_source_type(source_type, reason)

    if amount <= 0:
        return get_available_balance(db, user_id)

    if expiry is None and st == "purchased":
        from app.services.credit_policy_service import purchased_validity_months as policy_purchased_months

        expiry = purchased_expiry_months(policy_purchased_months())

    user = _user_query_for_update(db, user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    bucket_note = (grant_reason or note or reason or "")[:2000] or None
    ledger_internal = (internal_note if internal_note is not None else note)
    if grant_reason is not None or internal_note is not None:
        ledger_internal = internal_note

    entry = CreditLedgerEntry(
        user_id=int(user_id),
        source_type=st,
        amount=int(amount),
        remaining_amount=int(amount),
        status="active",
        expired_at=_aware(expiry),
        note=bucket_note,
    )
    db.add(entry)
    db.flush()
    balance = _sync_user_balance(db, user)

    db.add(
        CreditLedger(
            user_id=user_id,
            delta=int(amount),
            balance_after=balance,
            reason=reason[:64],
            note=(ledger_internal or "")[:2000] or None,
            expires_at=entry.expired_at,
            admin_id=int(admin_id) if admin_id is not None else None,
            credit_type=st,
            grant_reason=(grant_reason or "")[:512] or None,
        )
    )
    return balance


def public_credit_transaction_note(row: CreditLedger) -> str | None:
    """Hide internal admin notes from end-user transaction views."""
    grant_reason = getattr(row, "grant_reason", None)
    if grant_reason:
        return str(grant_reason)
    if str(getattr(row, "reason", "") or "").strip().lower() == "admin_grant":
        return None
    return row.note


def consume_credits(
    db: Session,
    *,
    user_id: int,
    amount: int,
    reason: str,
    note: str | None = None,
    module: str | None = None,
    action: str | None = None,
    request_id: str | None = None,
    source: str | None = None,
) -> int:
    """
    Subtract credits FIFO (soonest expiry first). Caller must commit.
    Returns new balance.
    Admin / super_admin: no deduction (unlimited access).
    """
    if amount <= 0:
        return get_available_balance(db, user_id)

    user = _user_query_for_update(db, user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    from app.services.rbac import is_admin

    if is_admin(user):
        return get_available_balance(db, user_id)

    from app.services.saas_trial_service import assert_trial_credit_cap, add_trial_credit_used

    assert_trial_credit_cap(db, user_id, amount)

    ensure_plan_monthly_credits(db, user_id)

    need = int(amount)
    buckets = _active_buckets_query(db, user_id).all()
    available = sum(int(b.remaining_amount or 0) for b in buckets)
    if available < need:
        from app.services.monthly_bonus_credit_service import sum_locked_monthly_bonus

        locked = sum_locked_monthly_bonus(db, user_id)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": "Không đủ credit."
                + (f" ({locked:,} credit gói đang bị khóa — gia hạn để dùng tiếp.)".replace(",", ".")
                if locked > 0
                else ""),
                "balance": available,
                "locked_credit": locked,
                "required": need,
                "reason": reason,
            },
        )

    remaining = need
    for bucket in buckets:
        if remaining <= 0:
            break
        take = min(int(bucket.remaining_amount or 0), remaining)
        if take <= 0:
            continue
        bucket.remaining_amount = int(bucket.remaining_amount or 0) - take
        remaining -= take
        if int(bucket.remaining_amount or 0) <= 0:
            bucket.status = "consumed"

    balance = _sync_user_balance(db, user)
    _append_consumption_log(
        db,
        user_id=user_id,
        amount=need,
        balance_after=balance,
        reason=reason,
        note=note,
        module=module,
        action=action,
        request_id=request_id,
        source=source,
    )
    try:
        from app.services.saas_economics_guard import check_economics_after_burn

        check_economics_after_burn(db, trigger="credit_burn")
    except Exception:
        pass
    add_trial_credit_used(db, user_id, need)
    return balance


def ensure_plan_monthly_credits(db: Session, user_id: int) -> int | None:
    """
    Deprecated: monthly bonus granted on SePay/subscription renewal only.
    Keeps sync lock state and returns None.
    """
    from app.services.monthly_bonus_credit_service import sync_subscription_credit_locks

    sync_subscription_credit_locks(db, user_id)
    return None


def _has_plan_monthly_for_period(db: Session, user_id: int, period: str) -> bool:
    marker = f"period={period}"
    return (
        db.query(CreditLedgerEntry.id)
        .filter(
            CreditLedgerEntry.user_id == int(user_id),
            CreditLedgerEntry.source_type.in_(("monthly_bonus", "plan_monthly")),
            CreditLedgerEntry.note.contains(marker),
        )
        .first()
        is not None
    )


def reconcile_stale_credit_balances(db: Session, *, user_ids: list[int] | None = None) -> int:
    """Fix users.credit_balance when it diverges from active ledger buckets."""
    q = db.query(User.id, User.credit_balance)
    if user_ids:
        q = q.filter(User.id.in_([int(x) for x in user_ids]))
    fixed = 0
    for user_id, cached in q.all():
        actual = get_available_balance(db, int(user_id), sync=False)
        if int(cached or 0) != actual:
            user = db.get(User, int(user_id))
            if user is not None:
                user.credit_balance = actual
                fixed += 1
    if fixed:
        db.flush()
    return fixed


def apply_signup_bonus_if_configured(db: Session, user: User) -> bool:
    """Grant SIGNUP_CREDIT_BONUS once per user (account activation / registration)."""
    b = signup_bonus()
    if b <= 0:
        return False
    if _has_signup_bonus(db, int(user.id)):
        return False
    grant_credits(
        db,
        user_id=user.id,
        amount=b,
        reason="signup_bonus",
        source_type="trial",
        note="signup_bonus",
        expired_at=None,
    )
    return True


def _has_signup_bonus(db: Session, user_id: int) -> bool:
    marker = (
        db.query(CreditLedger.id)
        .filter(
            CreditLedger.user_id == int(user_id),
            CreditLedger.reason == "signup_bonus",
        )
        .first()
    )
    return marker is not None


def backfill_activation_credits(db: Session) -> int:
    """
    Grant signup bonus to activated users who never received it
    (e.g. credits were disabled at registration time).
    """
    if signup_bonus() <= 0:
        return 0
    users = db.query(User).filter(User.has_password.is_(True)).all()
    granted = 0
    for user in users:
        if _has_signup_bonus(db, int(user.id)):
            continue
        grant_credits(
            db,
            user_id=user.id,
            amount=signup_bonus(),
            reason="signup_bonus",
            source_type="trial",
            note="signup_bonus_backfill",
            expired_at=None,
        )
        granted += 1
    if granted:
        db.commit()
        logger.info("backfill_activation_credits granted %s users", granted)
    return granted


def plan_monthly_expiry_for_activation() -> datetime | None:
    """Monthly bonus no longer expires at calendar month end — accumulates with cap."""
    return None


def purchased_expiry_months(months: int = 12) -> datetime:
    """Purchased credit packs expire after N months (default 12)."""
    return _utc_now() + timedelta(days=max(1, int(months)) * 30)
