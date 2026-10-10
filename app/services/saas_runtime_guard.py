"""Production hard-fail guards for secrets and SaaS enforcement flags."""

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

_DEFAULT_JWT_SECRETS = frozenset(
    {
        "",
        "change-this-in-production",
        "secret",
        "changeme",
        "dev",
        "development",
        "your-secret-key",
        "jwt-secret",
    }
)


def _env_on(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes", "on")


def jwt_secret_raw() -> str:
    return (os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "").strip()


def jwt_secret_is_insecure(secret: str | None = None) -> bool:
    s = (secret if secret is not None else jwt_secret_raw()).strip()
    if not s:
        return True
    if s.lower() in {x.lower() for x in _DEFAULT_JWT_SECRETS}:
        return True
    if len(s) < 32:
        return True
    return False


class ProductionSecurityError(RuntimeError):
    """Raised when production would boot insecurely."""


def assert_production_security() -> None:
    """Hard-fail production if JWT secret or SaaS flags are misconfigured."""
    if not is_production():
        return

    problems: list[str] = []
    secret = jwt_secret_raw()
    if jwt_secret_is_insecure(secret):
        problems.append(
            "JWT_SECRET/SECRET_KEY missing, too short (<32), or equals a known insecure default"
        )

    for name, expected in _REQUIRED_PROD_FLAGS:
        if not _env_on(name):
            problems.append(f"{name} must be {expected}")

    if not problems:
        _LOG.info(
            "production_security_ok: JWT secret set; SAAS_ENFORCEMENT=1 "
            "CREDITS_ENABLED=1 COST_CONTROL_ENABLED=1"
        )
        return

    msg = "PRODUCTION HARD-FAIL: " + "; ".join(problems)
    _LOG.critical(msg)
    raise ProductionSecurityError(msg)


def log_saas_runtime_guard() -> None:
    """Back-compat name: enforces hard-fail in production."""
    assert_production_security()
