"""Cost-control configuration (env)."""

from __future__ import annotations

import os


def cost_control_enforced() -> bool:
  return os.getenv("COST_CONTROL_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def external_api_retry_max() -> int:
  try:
    return max(0, min(2, int(os.getenv("EXTERNAL_API_RETRY_MAX", "2").strip())))
  except (TypeError, ValueError):
    return 2


def default_user_rate_per_min(provider: str) -> int:
  key = f"COST_CONTROL_{provider.upper()}_RATE_PER_MIN"
  try:
    return max(1, int(os.getenv(key, os.getenv("COST_CONTROL_USER_RATE_PER_MIN", "30")).strip()))
  except (TypeError, ValueError):
    return 30
