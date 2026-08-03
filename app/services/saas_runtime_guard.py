"""Production guards for SaaS enforcement flags."""

from __future__ import annotations

import logging
import os

from app.core.runtime import is_production

_LOG = logging.getLogger(__name__)

_REQUIRED_PROD_FLAGS: tuple[tuple[str, str], ...] = (
    ("SAAS_ENFORCEMENT", "1"),
    ("CREDITS_ENABLED", "1"),
    ("COST_CONTROL_ENABLED", "1"),
)


def _env_on(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes", "on")


def log_saas_runtime_guard() -> None:
    """Warn/error when production is missing required SaaS enforcement flags."""
    if not is_production():
        return

    missing: list[str] = []
    for name, expected in _REQUIRED_PROD_FLAGS:
        if not _env_on(name):
            missing.append(f"{name}={expected}")

    if not missing:
        _LOG.info(
            "saas_runtime_guard ok: SAAS_ENFORCEMENT=1 CREDITS_ENABLED=1 COST_CONTROL_ENABLED=1"
        )
        return

    msg = (
        "PRODUCTION MISCONFIG: bắt buộc bật "
        + ", ".join(missing)
        + " — quota/credit enforcement có thể không hoạt động đúng."
    )
    _LOG.error(msg)
