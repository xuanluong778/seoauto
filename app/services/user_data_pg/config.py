"""Feature flags for JSON → PostgreSQL user data migration (all OFF by default)."""

from __future__ import annotations

import os

DOMAINS = (
    "content_ai_projects",
    "publishing_sites",
    "ai_knowledge_bases",
    "rank_tracking",
    "social_facebook",
    "user_system_settings",
)


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def pg_read_enabled(domain: str) -> bool:
    """Read PostgreSQL first when enabled AND global read flag is on."""
    if not _truthy("USER_DATA_PG_READ"):
        return False
    key = f"USER_DATA_PG_READ_{domain.upper()}"
    specific = os.getenv(key, "").strip()
    if specific:
        return specific.lower() in {"1", "true", "yes", "on"}
    return _truthy(f"USER_DATA_PG_READ_{domain}")


def pg_dual_write_enabled(domain: str) -> bool:
    """Mirror writes to PostgreSQL during transition (JSON remains written)."""
    if not _truthy("USER_DATA_PG_DUAL_WRITE"):
        return False
    key = f"USER_DATA_PG_DUAL_WRITE_{domain.upper()}"
    specific = os.getenv(key, "").strip()
    if specific:
        return specific.lower() in {"1", "true", "yes", "on"}
    return _truthy(f"USER_DATA_PG_DUAL_WRITE_{domain}")


def pg_fallback_json_enabled() -> bool:
    """Allow JSON fallback when PG read is enabled but PG empty or errors."""
    return not _truthy("USER_DATA_PG_NO_JSON_FALLBACK")
