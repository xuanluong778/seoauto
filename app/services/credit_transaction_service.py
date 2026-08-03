"""Estimate → precheck → charge on success → refund on AI/API failure."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.services.credit_cost_registry import new_request_id, resolve_credit_cost
from app.services.credits import (
    consume_credits,
    credits_enforced,
    ensure_sufficient_credits,
    get_available_balance,
    grant_credits,
)

CREDIT_STATUS_SUCCESS = "success"
CREDIT_STATUS_FAILED_REFUND = "failed_refund"


def estimate_module_credit(
    module: str,
    action: str,
    *,
    db: Session | None = None,
    from_cache: bool = False,
) -> int:
    return max(0, int(resolve_credit_cost(module, action, db=db, from_cache=from_cache)))


def precheck_credit_balance(db: Session, user_id: int, amount: int) -> dict[str, Any]:
    """Raise 402 if credits enforced and balance insufficient."""
    need = max(0, int(amount))
    balance = get_available_balance(db, int(user_id))
    if not credits_enforced() or need <= 0:
        return {"required": need, "balance": balance, "sufficient": True}
    _, sufficient = ensure_sufficient_credits(db, int(user_id), need)
    if sufficient:
        return {"required": need, "balance": balance, "sufficient": True}
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "insufficient_credits",
            "message": f"Bạn cần {need} credit, tài khoản hiện có {balance} credit.",
            "required": need,
            "balance": balance,
        },
    )


def charge_on_success(
    db: Session,
    *,
    user_id: int,
    amount: int,
    module: str,
    action: str,
    request_id: str | None = None,
    source: str = "system_api",
    reason: str | None = None,
) -> int:
    """Trừ credit sau khi tác vụ thành công. Caller phải commit."""
    need = max(0, int(amount))
    if need <= 0 or not credits_enforced():
        return get_available_balance(db, int(user_id))
    rid = (request_id or new_request_id())[:64]
    charge_reason = (reason or f"{module}_{action}")[:64]
    return consume_credits(
        db,
        user_id=int(user_id),
        amount=need,
        reason=charge_reason,
        module=module,
        action=action,
        request_id=rid,
        source=source,
    )


def refund_on_failure(
    db: Session,
    *,
    user_id: int,
    amount: int,
    module: str,
    action: str,
    request_id: str | None = None,
    note: str = "",
) -> int:
    """Hoàn credit khi AI/API lỗi sau khi đã trừ. Caller phải commit."""
    amt = max(0, int(amount))
    if amt <= 0 or not credits_enforced():
        return get_available_balance(db, int(user_id))
    rid = (request_id or "")[:64]
    refund_note = f"status={CREDIT_STATUS_FAILED_REFUND};module={module};action={action}"
    if rid:
        refund_note += f";request_id={rid}"
    if note:
        refund_note += f";{note[:1500]}"
    return grant_credits(
        db,
        user_id=int(user_id),
        amount=amt,
        reason="failed_refund",
        source_type="refund",
        note=refund_note[:2000],
    )
