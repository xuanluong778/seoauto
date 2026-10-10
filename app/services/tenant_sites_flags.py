"""Feature flags for credentials / publishing sites JSON → PostgreSQL migration."""

from __future__ import annotations

import os


def _truthy(name: str, default: str = "") -> bool:
    raw = os.getenv(name, default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def tenant_sites_pg_enabled() -> bool:
    """PostgreSQL is primary read/write for publishing sites + WP links (default on)."""
    return _truthy("TENANT_CRED_SITES_PG", "1")


def tenant_sites_dual_read() -> bool:
    """If PG miss/error, temporarily fall back to JSON (rollback path). Default on until cutover."""
    return _truthy("TENANT_CRED_SITES_DUAL_READ", "1")


def tenant_sites_json_write() -> bool:
    """When dual-write legacy mirror needed. Default off — PG is write authority."""
    return _truthy("TENANT_CRED_SITES_JSON_WRITE", "0")


def tenant_api_keys_require_org() -> bool:
    return _truthy("TENANT_API_KEYS_REQUIRE_ORG", "1")
