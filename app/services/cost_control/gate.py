"""Pre-flight checks: plan, credit, quota, cache, rate limit, single-flight."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Iterator

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import usage_tracking_service
from app.services.cau_ai_fix_entitlement import resolve_cau_ai_plan_slug
from app.services.cost_control.context import (
  ActiveCostGate,
  get_active_cost_gate,
  reset_active_cost_gate,
  set_active_cost_gate,
)
from app.services.cost_control.runtime import (
  SingleFlightGuard,
  check_user_concurrency,
  check_user_rate_limit,
  ensure_not_cooldown,
  release_user_concurrency,
)
from app.services.cost_control.settings import (
  cost_control_enforced,
  default_user_concurrency,
  default_user_rate_per_min,
)
from app.services.cost_control.types import ExternalApiProvider
from app.services.credits import credits_enforced, ensure_sufficient_credits
from app.services.rbac import is_admin
from app.services.software_access_service import user_has_software_access

_LOG = logging.getLogger("cost_control.gate")


@dataclass
class CostGateRequest:
  db: Session
  user: User
  provider: ExternalApiProvider
  action: str
  credit_cost: int = 0
  feature_key: str | None = None
  quota_units: int = 1
  require_paid_plan: bool = False
  cache_lookup: Callable[[], Any | None] | None = None
  single_flight_key: str | None = None
  cooldown_key: str | None = None
  cooldown_message: str | None = None
  rate_limit_per_min: int | None = None
  client_ip: str | None = None
  skip_credit_check: bool = False


@dataclass
class CostGateSession:
  request: CostGateRequest
  plan_slug: str | None = None
  cache_hit: bool = False
  cached_value: Any = None
  credit_required: int = 0
  credit_balance: int | None = None
  quota_remaining: int | None = None
  _gate_token: object | None = field(default=None, repr=False)
  _flight: SingleFlightGuard | None = field(default=None, repr=False)

  def assert_external_call_allowed(self, *, provider: ExternalApiProvider, action: str) -> None:
    if not cost_control_enforced():
      return
    if self.cache_hit:
      raise RuntimeError("cost_gate: external API call blocked — cache hit")
    gate = get_active_cost_gate()
    if gate is None or gate.token is None:
      raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
          "code": "cost_gate_missing",
          "message": "Yêu cầu chưa qua kiểm soát chi phí. Vui lòng thử lại.",
        },
      )
    if gate.provider != provider:
      raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
          "code": "cost_gate_provider_mismatch",
          "message": "Kiểm soát chi phí không khớp nhà cung cấp API.",
        },
      )


def _check_plan(db: Session, user: User, *, require_paid_plan: bool) -> str | None:
  if is_admin(user):
    return "admin"
  from app.services.saas_ui_messages import resolve_ai_access_state

  if require_paid_plan and not user_has_software_access(db, user.id):
    ui = resolve_ai_access_state(db, user)
    code = str(ui.get("state") or "plan_required")
    raise HTTPException(
      status_code=status.HTTP_403_FORBIDDEN,
      detail={
        "code": code,
        "message": str(ui.get("message") or ""),
        "upgrade_url": "/pricing",
      },
    )
  return resolve_cau_ai_plan_slug(db, user)


def _check_quota(db: Session, user: User, *, feature_key: str, units: int) -> int | None:
  from app.services.plan_quota_service import quota_exceeded_detail
  from app.services.entitlement_service import resolve_effective_plan

  remaining = usage_tracking_service.get_quota_remaining(db, user.id, feature_key)
  if remaining is None:
    return None
  if int(remaining) < max(1, int(units)):
    plan_slug = resolve_effective_plan(db, user) or resolve_cau_ai_plan_slug(db, user)
    raise HTTPException(
      status_code=status.HTTP_429_TOO_MANY_REQUESTS,
      detail=quota_exceeded_detail(
        feature_key=feature_key,
        plan_slug=plan_slug,
        remaining=int(remaining),
      ),
    )
  return int(remaining)


def _check_credits(db: Session, user: User, *, credit_cost: int) -> tuple[int, bool]:
  if credit_cost <= 0 or not credits_enforced():
    balance = 0
    try:
      from app.services.credits import get_available_balance

      balance = get_available_balance(db, user.id)
    except Exception:
      balance = 0
    return balance, True
  return ensure_sufficient_credits(db, user.id, credit_cost)


@contextmanager
def cost_gate_session(req: CostGateRequest) -> Iterator[CostGateSession]:
  """
  Run pre-flight cost checks before any billable external API call.

  Order: SaaS feature/access (always, including cache) → cache → single-flight
  → rate limit → cooldown → plan → quota → credit precheck.
  Guest callers are rejected when SAAS_ENFORCEMENT requires a user.
  """
  session = CostGateSession(request=req, credit_required=max(0, int(req.credit_cost)))

  # Central SaaS access + feature (trial blocks) BEFORE cache short-circuit
  if req.user is None:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail={"code": "auth_required", "message": "Đăng nhập để tiếp tục."},
    )
  try:
    from app.services.saas_gate import enforce_saas_access

    if req.feature_key:
      session.plan_slug = enforce_saas_access(
        req.db,
        req.user,
        feature_code=str(req.feature_key),
        quantity=max(1, int(req.quota_units or 1)),
        require_feature=True,
      )
    elif req.require_paid_plan:
      session.plan_slug = _check_plan(req.db, req.user, require_paid_plan=True)
    else:
      # Soft software access for other billable external calls
      session.plan_slug = _check_plan(req.db, req.user, require_paid_plan=True)
  except HTTPException:
    raise
  except Exception:
    _LOG.exception("cost_gate saas access failed user_id=%s", getattr(req.user, "id", None))
    raise

  if req.cache_lookup is not None:
    try:
      cached = req.cache_lookup()
    except Exception:
      _LOG.exception("cost_gate cache_lookup failed user_id=%s action=%s", req.user.id, req.action)
      cached = None
    if cached is not None:
      session.cache_hit = True
      session.cached_value = cached
      gate = ActiveCostGate(
        user_id=req.user.id,
        provider=req.provider,
        action=req.action,
        cache_hit=True,
        cached_value=cached,
      )
      token = set_active_cost_gate(gate)
      session._gate_token = token
      try:
        yield session
      finally:
        reset_active_cost_gate(token)
      return

  flight_key = req.single_flight_key or f"{req.user.id}:{req.provider.value}:{req.action}"
  flight = SingleFlightGuard(flight_key)
  flight.__enter__()
  session._flight = flight
  conc_held = False

  gate_token: object | None = None
  try:
    if cost_control_enforced() and not is_admin(req.user):
      rate = req.rate_limit_per_min
      if rate is None:
        rate = default_user_rate_per_min(req.provider.value)
      check_user_rate_limit(
        scope=req.provider.value,
        user_id=req.user.id,
        limit_per_min=int(rate),
      )
      check_user_concurrency(
        scope=req.provider.value,
        user_id=req.user.id,
        limit=default_user_concurrency(req.provider.value),
      )
      conc_held = True
      if req.cooldown_key:
        ensure_not_cooldown(req.cooldown_key, message=req.cooldown_message)

    if not session.plan_slug:
      session.plan_slug = _check_plan(req.db, req.user, require_paid_plan=req.require_paid_plan)

    if req.feature_key and cost_control_enforced() and not is_admin(req.user):
      session.quota_remaining = _check_quota(
        req.db,
        req.user,
        feature_key=req.feature_key,
        units=req.quota_units,
      )

    if cost_control_enforced() and not is_admin(req.user):
      from app.services.cost_control.caps import assert_provider_daily_caps, assert_user_credit_caps
      from app.services.saas_economics_guard import assert_expensive_api_allowed

      # Product SSOT: wallet + entitlement. No per-category premium_llm hard cap.
      # Keep anti-abuse daily/monthly burn caps + emergency platform economics guard.
      assert_user_credit_caps(req.db, req.user, extra_credits=session.credit_required)
      assert_provider_daily_caps(req.db, req.user, provider=req.provider.value)
      assert_expensive_api_allowed(req.db, user=req.user, provider=req.provider)

    from app.services.rbac import admin_skips_credit_deduction

    if (
        not req.skip_credit_check
        and cost_control_enforced()
        and not admin_skips_credit_deduction(req.user)
    ):
      balance, sufficient = _check_credits(req.db, req.user, credit_cost=session.credit_required)
      session.credit_balance = balance
      if not sufficient:
        from app.services.saas_ui_messages import MSG_NEED_CREDIT

        msg = MSG_NEED_CREDIT if balance <= 0 else f"Không đủ credit. Cần {session.credit_required}, còn {balance}."
        raise HTTPException(
          status_code=status.HTTP_402_PAYMENT_REQUIRED,
          detail={
            "code": "insufficient_credits",
            "message": msg,
            "balance": balance,
            "credit_required": session.credit_required,
            "upgrade_url": "/account/billing",
          },
        )

    gate = ActiveCostGate(user_id=req.user.id, provider=req.provider, action=req.action)
    gate_token = set_active_cost_gate(gate)
    session._gate_token = gate_token
    yield session
  finally:
    if conc_held:
      try:
        release_user_concurrency(scope=req.provider.value, user_id=req.user.id)
      except Exception:
        _LOG.exception("cost_gate concurrency release failed")
    if gate_token is not None:
      reset_active_cost_gate(gate_token)
    if session._flight is not None and session._flight.acquired:
      session._flight.__exit__(None, None, None)

