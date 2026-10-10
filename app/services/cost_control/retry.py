import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.services.cost_control.settings import external_api_retry_max

_LOG = logging.getLogger("cost_control.retry")

T = TypeVar("T")


def retry_external_call(
  fn: Callable[[], T],
  *,
  is_retryable: Callable[[BaseException], bool] | None = None,
  delays: tuple[float, ...] = (3.0, 10.0),
) -> T:
  max_retries = external_api_retry_max()
  last_exc: BaseException | None = None
  for attempt in range(max_retries + 1):
    try:
      return fn()
    except BaseException as exc:
      last_exc = exc
      retryable = is_retryable(exc) if is_retryable else False
      if not retryable or attempt >= max_retries:
        raise
      base = delays[min(attempt, len(delays) - 1)]
      # exponential-ish backoff with jitter (bounded)
      delay = min(30.0, base * (1.5 ** attempt) + random.uniform(0.0, 0.75))
      _LOG.info("external_api_retry attempt=%s delay=%.1fs err=%s", attempt + 1, delay, type(exc).__name__)
      time.sleep(delay)
  if last_exc:
    raise last_exc
  raise RuntimeError("external_api_retry exhausted")
