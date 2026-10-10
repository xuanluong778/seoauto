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
  from app.services.circuit_breaker import CircuitOpenError, call_with_circuit

  _assert_gate(provider, action)
  circuit_name = f"{provider.value}:{action}"
  try:
    result = call_with_circuit(
      circuit_name,
      lambda: retry_external_call(fn, is_retryable=is_retryable),
    )
  except CircuitOpenError as exc:
    _LOG.warning("circuit_open provider=%s action=%s retry_after=%.1f", provider.value, action, exc.retry_after_sec)
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail={
        "code": "provider_circuit_open",
        "message": "Dịch vụ bên thứ ba tạm quá tải — thử lại sau.",
        "retry_after_sec": round(exc.retry_after_sec, 1),
        "provider": provider.value,
      },
    ) from exc
  except Exception as exc:
    if provider in (ExternalApiProvider.OPENAI, ExternalApiProvider.ANTHROPIC):
      from app.services.llm_ops_metrics import record_llm_call

      timeout = isinstance(exc, requests.Timeout)
      record_llm_call(ok=False, timeout=timeout, server_error=not timeout)
    raise
  if provider in (ExternalApiProvider.OPENAI, ExternalApiProvider.ANTHROPIC):
    from app.services.llm_ops_metrics import record_llm_call

    if isinstance(result, requests.Response):
      code = int(getattr(result, "status_code", 0) or 0)
      record_llm_call(
        ok=code < 400,
        rate_limited=code == 429,
        server_error=code >= 500,
      )
    else:
      record_llm_call(ok=True)
  return result


def guarded_requests_get(
  provider: ExternalApiProvider,
  action: str,
  url: str,
  *,
  is_retryable: Callable[[BaseException], bool] | None = None,
  **kwargs: Any,
) -> requests.Response:
  def _call() -> requests.Response:
    from app.services.url_safety import safe_requests_get, validate_public_http_url

    u = str(url or "")
    if u.startswith(("http://", "https://")):
      blocked = validate_public_http_url(u)
      if blocked:
        raise ValueError(blocked)
      headers = kwargs.get("headers")
      timeout = kwargs.get("timeout", 30)
      params = kwargs.get("params")
      try:
        t = float(timeout) if timeout is not None else 30.0
      except (TypeError, ValueError):
        t = 30.0
      return safe_requests_get(u, timeout=t, headers=headers, params=params)
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
    from app.services.url_safety import validate_public_http_url

    u = str(url or "")
    if u.startswith(("http://", "https://")):
      blocked = validate_public_http_url(u)
      if blocked:
        raise ValueError(blocked)
      # Do not follow redirects to private networks.
      kwargs = {**kwargs, "allow_redirects": False}
    return requests.post(url, **kwargs)

  return execute_guarded_external(provider, action, _call, is_retryable=is_retryable)


def http_error_retryable(exc: BaseException) -> bool:
  if isinstance(exc, requests.RequestException):
    resp = getattr(exc, "response", None)
    if resp is not None and int(getattr(resp, "status_code", 0) or 0) >= 500:
      return True
  return False
