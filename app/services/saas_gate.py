"""Central SaaS gate: auth → access → feature → quota → reserve credit → job → commit/release."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import entitlement_service
from app.services import credits as credits_svc
from app.services import usage_tracking_service
from app.services.rbac import can_write, is_admin
from app.services.software_access_service import user_has_software_access
from app.services.saas_ui_messages import resolve_ai_access_state

_LOG = logging.getLogger("saas_gate")

ChargeMode = Literal["none", "reserve", "precheck"]


@dataclass
class SaaSGateContext:
    db: Session
    user: User
    feature_code: str
    job_id: str
    idempotency_key: str
    organization_id: int | None = None
    credit_cost: int = 0
    quota_units: int = 1
    plan_slug: str | None = None
    reservation_id: int | None = None
    reserved_amount: int = 0
    credit_balance: int | None = None
    quota_remaining: int | None = None
    committed: bool = False
    released: bool = False
    _skip_credit: bool = field(default=False, repr=False)

    def commit(self) -> None:
        """Confirm reservation (no second debit)."""
        if self.committed or self.released:
            return
        if self.reservation_id and self.reserved_amount > 0:
            credits_svc.commit_reservation(
                self.db,
                reservation_id=self.reservation_id,
                user_id=int(self.user.id),
            )
        self.committed = True

    def release(self, *, reason: str = "job_failed") -> None:
        """Release/refund reserved credits on failure/timeout/cancel."""
        if self.committed or self.released:
            return
        if self.reservation_id and self.reserved_amount > 0:
            credits_svc.release_reservation(
                self.db,
                reservation_id=self.reservation_id,
                user_id=int(self.user.id),
                reason=reason,
            )
        self.released = True

    def record_usage(self, *, metadata: dict[str, Any] | None = None) -> None:
        usage_tracking_service.record_successful_usage(
            self.db,
            int(self.user.id),
            self.feature_code,
            quantity=max(1, int(self.quota_units)),
            credits_used=int(self.reserved_amount or self.credit_cost or 0),
            metadata=metadata,
            idempotency_key=self.idempotency_key,
        )


def _raise_entitlement(result) -> None:
    code = str(getattr(result, "reason_code", None) or "denied")
    message = str(getattr(result, "message", None) or "Không được phép.")
    if code in {
        "insufficient_credits",
        "trial_need_credit",
        "trial_credit_cap",
        "need_credit",
    }:
        status_code = status.HTTP_402_PAYMENT_REQUIRED
    elif code in {"quota_exceeded", "trial_daily_limit"}:
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        status_code = status.HTTP_403_FORBIDDEN
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "feature_key": getattr(result, "feature_key", None),
            "upgrade_url": "/pricing" if status_code == 403 else "/account/billing",
        },
    )


def _check_software_access(db: Session, user: User) -> None:
    if is_admin(user):
        return
    if user_has_software_access(db, user.id):
        return
    ui = resolve_ai_access_state(db, user)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": str(ui.get("state") or "plan_required"),
            "message": str(ui.get("message") or "Cần gói hoặc trial active."),
            "upgrade_url": "/pricing",
        },
    )


def _check_quota(db: Session, user: User, *, feature_code: str, units: int) -> int | None:
    if is_admin(user):
        return None
    remaining = usage_tracking_service.get_quota_remaining(db, user.id, feature_code)
    if remaining is None:
        return None
    if int(remaining) < max(1, int(units)):
        from app.services.plan_quota_service import quota_exceeded_detail
        from app.services.entitlement_service import resolve_effective_plan

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=quota_exceeded_detail(
                feature_key=feature_code,
                plan_slug=resolve_effective_plan(db, user),
                remaining=int(remaining),
            ),
        )
    return int(remaining)


def enforce_saas_access(
    db: Session,
    user: User,
    *,
    feature_code: str,
    quantity: int = 1,
    require_feature: bool = True,
) -> str | None:
    """
    Auth-level SaaS checks without credit reservation.
    Always runs even on cache-hit paths (caller must invoke before returning cache).
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "auth_required", "message": "Đăng nhập để tiếp tục."},
        )
    if not can_write(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "read_only", "message": "Tài khoản chỉ xem — không có quyền."},
        )

    _check_software_access(db, user)

    plan_slug = entitlement_service.resolve_effective_plan(db, user)
    if require_feature and feature_code:
        # When SAAS_ENFORCEMENT=0, check_feature allows; production has it on.
        result = entitlement_service.check_feature(db, user, feature_code, quantity=quantity)
        if not result.allowed:
            _raise_entitlement(result)
        if result.plan_slug:
            plan_slug = result.plan_slug
    return plan_slug


@contextmanager
def saas_action_gate(
    db: Session,
    user: User,
    *,
    feature_code: str,
    credit_cost: int = 0,
    quota_units: int = 1,
    job_id: str | None = None,
    idempotency_key: str | None = None,
    organization_id: int | None = None,
    charge_mode: ChargeMode = "reserve",
    require_feature: bool = True,
    auto_commit_on_success: bool = False,
) -> Iterator[SaaSGateContext]:
    """
    Central billable action gate.

    Order: write role → software access → feature (trial blocks) → monthly quota
    → reserve credits (if mode=reserve) → yield → caller commit() or release() on error.
    """
    feature_code = str(feature_code or "").strip()
    if not feature_code:
        raise HTTPException(status_code=400, detail={"code": "missing_feature", "message": "Thiếu feature_code."})

    jid = (job_id or str(uuid.uuid4()))[:128]
    idem = (idempotency_key or f"{feature_code}:{user.id}:{jid}")[:128]

    plan_slug = enforce_saas_access(
        db,
        user,
        feature_code=feature_code,
        quantity=quota_units,
        require_feature=require_feature,
    )

    quota_remaining = None
    if not is_admin(user):
        from app.services.cost_control.settings import cost_control_enforced

        if cost_control_enforced():
            quota_remaining = _check_quota(db, user, feature_code=feature_code, units=quota_units)

    cost = max(0, int(credit_cost or 0))
    ctx = SaaSGateContext(
        db=db,
        user=user,
        feature_code=feature_code,
        job_id=jid,
        idempotency_key=idem,
        organization_id=organization_id,
        credit_cost=cost,
        quota_units=max(1, int(quota_units)),
        plan_slug=plan_slug,
        quota_remaining=quota_remaining,
    )

    if is_admin(user) or not credits_svc.credits_enforced() or cost <= 0 or charge_mode == "none":
        ctx._skip_credit = True
        try:
            yield ctx
            if auto_commit_on_success:
                ctx.committed = True
        except Exception:
            ctx.released = True
            raise
        return

    if charge_mode == "precheck":
        balance, ok = credits_svc.ensure_sufficient_credits(db, user.id, cost)
        ctx.credit_balance = balance
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "code": "insufficient_credits",
                    "message": f"Không đủ credit (cần {cost}, còn {balance}).",
                    "balance": balance,
                    "required": cost,
                    "upgrade_url": "/account/billing",
                },
            )
        try:
            yield ctx
        except Exception:
            raise
        return

    # reserve mode
    res = credits_svc.reserve_credits(
        db,
        user_id=int(user.id),
        amount=cost,
        feature_code=feature_code,
        job_id=jid,
        idempotency_key=idem,
        organization_id=organization_id,
        reason=f"reserve:{feature_code}"[:64],
    )
    ctx.reservation_id = int(res["reservation_id"])
    ctx.reserved_amount = int(res["amount"])
    ctx.credit_balance = int(res.get("balance_after") or 0)
    if res.get("already_committed"):
        ctx.committed = True

    try:
        yield ctx
        if auto_commit_on_success and not ctx.released and not ctx.committed:
            ctx.commit()
    except Exception:
        if not ctx.committed:
            try:
                ctx.release(reason="job_failed")
            except Exception:
                _LOG.exception("saas_gate release failed user_id=%s job_id=%s", user.id, jid)
        raise


def build_job_id(*parts: Any) -> str:
    raw = ":".join(str(p) for p in parts if p is not None)
    return (raw or str(uuid.uuid4()))[:128]
