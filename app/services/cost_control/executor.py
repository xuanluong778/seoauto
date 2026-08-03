"""Execute external HTTP/API calls only when an active cost gate allows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

import requests
from fastapi import HTTPException, status

from app.services.cost_control.context import get_active_cost_gate
from app.services.cost_control.retry import retry_external_call
from app.services.cost_control.settings import cost_control_enforced
from app.services.cost_control.types import ExternalApiProvider

_LOG = logging.getLogger("cost_control.executor")

T = TypeVar("T")


class CostControlBypassError(RuntimeError):
  pass


def _assert_gate(provider: ExternalApiProvider, action: str) -> None:
  if not cost_control_enforced():
    return
  gate = get_active_cost_gate()
  if gate is None:
    _LOG.error(
      "cost_control bypass blocked provider=%s action=%s user_gate=missing",
      provider.value,
      action,
    )
    raise CostControlBypassError(
      f"External API call blocked: missing cost gate for {provider.value}/{action}"
    )
  if gate.cache_hit:
    raise CostControlBypassError(
      f"External API call blocked: cache hit for {provider.value}/{action}"
    )
  if gate.provider != provider:
    _LOG.error(
      "cost_control provider mismatch expected=%s got=%s action=%s user_id=%s",
      provider.value,
      gate.provider.value,
      action,
      gate.user_id,
    )
    raise CostControlBypassError(
      f"External API call blocked: provider mismatch ({gate.provider.value} != {provider.value})"
    )


def execute_guarded_external(
  provider: ExternalApiProvider,
  action: str,
  fn: Callable[[], T],
  *,
  is_retryable: Callable[[BaseException], bool] | None = None,
) -> T:
  _assert_gate(provider, action)
  return retry_external_call(fn, is_retryable=is_retryable)


def guarded_requests_get(
  provider: ExternalApiProvider,
  action: str,
  url: str,
  *,
  is_retryable: Callable[[BaseException], bool] | None = None,
  **kwargs: Any,
) -> requests.Response:
  def _call() -> requests.Response:
    return requests.get(url, **kwargs)

  return execute_guarded_external(provider, action, _call, is_retryable=is_retryable)


def guarded_requests_post(
  provider: ExternalApiProvider,
  action: str,
  url: str,
  *,
  is_retryable: Callable[[BaseException], bool] | None = None,
  **kwargs: Any,
) -> requests.Response:
  def _call() -> requests.Response:
    return requests.post(url, **kwargs)

  return execute_guarded_external(provider, action, _call, is_retryable=is_retryable)


def http_error_retryable(exc: BaseException) -> bool:
  if isinstance(exc, requests.RequestException):
    resp = getattr(exc, "response", None)
    if resp is not None and int(getattr(resp, "status_code", 0) or 0) >= 500:
      return True
  return False
