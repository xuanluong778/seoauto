"""Entitlement + credit billing cho «Sửa bằng AI» popup Auto Update SEO."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cau_seo_fix_credit_log import CauSeoFixCreditLog
from app.models.user import User
from app.services.credits import (
    consume_credits,
    cost_cau_seo_ai_fix,
    credits_enforced,
    get_available_balance,
    grant_credits,
)
from app.services.rbac import is_admin
from app.services.seoauto_pricing_catalog import SEOAUTO_PLAN_SLUG_ORDER
from app.services.user_api_access import resolve_effective_ai_plan_slug

_LOG = logging.getLogger(__name__)

PAID_CAU_AI_PLAN_SLUGS = frozenset(SEOAUTO_PLAN_SLUG_ORDER)

CREDIT_STATUS_PENDING = "pending"
CREDIT_STATUS_CHARGED = "charged"
CREDIT_STATUS_FAILED = "failed"
CREDIT_STATUS_RULE_FREE = "rule_no_charge"
CREDIT_STATUS_CACHED = "cached_no_charge"
CREDIT_STATUS_REFUNDED = "refunded"

FREE_PLAN_MESSAGE = "Tính năng AI Fix SEO chỉ dành cho gói Basic trở lên."


def resolve_cau_ai_plan_slug(db: Session, user: User) -> str | None:
    slug = resolve_effective_ai_plan_slug(db, user)
    if slug == "admin":
        return "admin"
    if slug in PAID_CAU_AI_PLAN_SLUGS or slug in {"trial_3d", "free_usage"}:
        return slug
    return None


FREE_PLAN_MESSAGE = "Tính năng AI Fix SEO chỉ dành cho gói Basic trở lên."
PAID_LLM_FREE_MESSAGE = "Gợi ý AI qua LLM hệ thống chỉ dành cho gói Basic trở lên. Nâng cấp gói hoặc liên hệ admin."


def build_paid_llm_snapshot(
    db: Session,
    user: User,
    *,
    unit_cost: int,
    quantity: int = 1,
    denied_message: str | None = None,
) -> dict[str, Any]:
    """Trạng thái quyền + credit cho LLM hệ thống (không trừ credit)."""
    from app.services.user_api_access import build_system_ai_snapshot

    return build_system_ai_snapshot(
        db, user, unit_cost=unit_cost, quantity=quantity, denied_message=denied_message,
    )


def assert_paid_llm_entitlement(
    db: Session,
    user: User,
    *,
    unit_cost: int,
    quantity: int = 1,
    denied_message: str | None = None,
) -> dict[str, Any]:
    snap = build_paid_llm_snapshot(
        db, user, unit_cost=unit_cost, quantity=quantity, denied_message=denied_message,
    )
    if snap.get("allowed"):
        return snap
    code = str(snap.get("code") or "denied")
    http_status = status.HTTP_402_PAYMENT_REQUIRED if code == "insufficient_credits" else status.HTTP_403_FORBIDDEN
    raise HTTPException(status_code=http_status, detail=snap)


def charge_paid_llm_usage(
    db: Session,
    user: User,
    *,
    reason: str,
    unit_cost: int,
    note: str = "",
    use_system_llm: bool = True,
) -> bool:
    """Trừ credit sau khi LLM hệ thống trả kết quả thành công. Trả True nếu đã trừ."""
    if is_admin(user) or not use_system_llm:
        return False
    if not resolve_cau_ai_plan_slug(db, user):
        return False
    cost = max(0, int(unit_cost))
    if not credits_enforced() or cost <= 0:
        return False
    consume_credits(
        db,
        user_id=user.id,
        amount=cost,
        reason=str(reason or "paid_llm")[:64],
        note=str(note or "")[:500] or None,
    )
    return True


def build_cau_ai_fix_snapshot(
    db: Session,
    user: User,
    *,
    quantity: int = 1,
) -> dict[str, Any]:
    """Trạng thái quyền + credit cho UI (không trừ credit)."""
    return build_paid_llm_snapshot(
        db, user, unit_cost=cost_cau_seo_ai_fix(), quantity=quantity, denied_message=FREE_PLAN_MESSAGE,
    )


def assert_cau_ai_fix_entitlement(
    db: Session,
    user: User,
    *,
    quantity: int = 1,
) -> dict[str, Any]:
    return assert_paid_llm_entitlement(
        db, user, unit_cost=cost_cau_seo_ai_fix(), quantity=quantity, denied_message=FREE_PLAN_MESSAGE,
    )


def should_charge_cau_ai_fix(result: dict[str, Any]) -> bool:
    if result.get("from_cache"):
        return False
    if str(result.get("source") or "") != "llm":
        return False
    if not result.get("success"):
        return False
    patch = result.get("patch") or {}
    if not patch:
        return False
    return True


def _credit_log_status(result: dict[str, Any], *, charged: bool) -> str:
    if charged:
        return CREDIT_STATUS_CHARGED
    if result.get("from_cache"):
        return CREDIT_STATUS_CACHED
    if str(result.get("source") or "") == "rule" and result.get("success"):
        return CREDIT_STATUS_RULE_FREE
    return CREDIT_STATUS_FAILED


def create_cau_fix_credit_log(
    db: Session,
    *,
    user_id: int,
    issue_key: str,
    plan: str,
    credit_cost: int,
    status: str,
    post_id: int | None = None,
    post_url: str = "",
    error_reason: str | None = None,
) -> CauSeoFixCreditLog:
    row = CauSeoFixCreditLog(
        user_id=int(user_id),
        post_id=int(post_id) if post_id else None,
        issue_key=str(issue_key or "")[:64],
        plan=str(plan or "")[:32],
        credit_cost=max(0, int(credit_cost)),
        status=str(status or CREDIT_STATUS_PENDING)[:32],
        post_url=(post_url or "")[:2000] or None,
        error_reason=(error_reason or "")[:2000] or None,
    )
    db.add(row)
    db.flush()
    return row


def finalize_cau_ai_fix_credit(
    db: Session,
    user: User,
    *,
    issue_key: str,
    plan_slug: str,
    result: dict[str, Any],
    post_id: int | None = None,
    post_url: str = "",
) -> dict[str, Any]:
    """
    Ghi log credit; chỉ trừ credit khi LLM sửa thành công (không cache).
    Caller phải commit session.
    """
    unit_cost = cost_cau_seo_ai_fix(db=db, from_cache=bool(result.get("from_cache")))
    charged = False
    error_reason = str(result.get("error") or "")[:2000] or None

    if should_charge_cau_ai_fix(result) and not is_admin(user):
        if credits_enforced() and unit_cost > 0:
            try:
                consume_credits(
                    db,
                    user_id=user.id,
                    amount=unit_cost,
                    reason="cau_seo_ai_fix",
                    note=f"issue={issue_key};post={post_id or ''};url={(post_url or '')[:120]}",
                    module="cau",
                    action="seo_ai_fix",
                    source="cache" if result.get("from_cache") else "live",
                )
                charged = True
            except HTTPException as exc:
                error_reason = str((exc.detail or {}).get("message") if isinstance(exc.detail, dict) else exc.detail)[:2000]
                _LOG.warning("cau ai fix charge failed user=%s issue=%s", user.id, issue_key)
        else:
            charged = False

    log_status = _credit_log_status(result, charged=charged)
    row = create_cau_fix_credit_log(
        db,
        user_id=user.id,
        issue_key=issue_key,
        plan=plan_slug,
        credit_cost=unit_cost if charged else 0,
        status=log_status,
        post_id=post_id,
        post_url=post_url,
        error_reason=error_reason if log_status == CREDIT_STATUS_FAILED else None,
    )

    return {
        "credit_charged": charged,
        "credit_cost": unit_cost if charged else 0,
        "credit_balance": get_available_balance(db, user.id),
        "credit_log_id": row.id,
        "credit_status": log_status,
    }


def refund_cau_ai_fix_credit(
    db: Session,
    *,
    user_id: int,
    amount: int,
    issue_key: str,
    post_id: int | None = None,
    note: str = "",
) -> None:
    """Hoàn credit khi đã trừ nhưng xử lý thất bại (phòng hờ)."""
    if amount <= 0 or not credits_enforced():
        return
    grant_credits(
        db,
        user_id=int(user_id),
        amount=int(amount),
        reason="cau_seo_ai_fix_refund",
        source_type="refund",
        note=note or f"refund issue={issue_key};post={post_id or ''}",
    )
