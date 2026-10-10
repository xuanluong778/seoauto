"""Deploy-time: user_sessions table (WAVE 8 server-side auth)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)

_REQUIRED_COLUMNS = (
    "id",
    "user_id",
    "family_id",
    "refresh_token_hash",
    "jti",
    "expires_at",
    "revoked_at",
    "revoke_reason",
    "user_agent",
    "ip_address",
    "role_snapshot",
    "created_at",
    "last_used_at",
)


def _has_table(name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in inspect(engine).get_columns(table))


def schema_status() -> dict[str, Any]:
    missing: list[str] = []
    if not _has_table("user_sessions"):
        missing.append("table:user_sessions")
    else:
        for col in _REQUIRED_COLUMNS:
            if not _has_column("user_sessions", col):
                missing.append(f"user_sessions.{col}")
    return {"ok": not missing, "missing": missing, "user_sessions": _has_table("user_sessions")}


def apply_user_sessions_migration() -> dict[str, Any]:
    """Run at deploy — not on app boot."""
    import app.models.user  # noqa: F401
    from app.models.user_session import UserSession  # noqa: F401

    Base.metadata.create_all(bind=engine, tables=[UserSession.__table__])
    applied: list[str] = ["user_sessions"]

    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE INDEX IF NOT EXISTS ix_user_sessions_user_revoked "
            "ON user_sessions (user_id, revoked_at)",
            "CREATE INDEX IF NOT EXISTS ix_user_sessions_refresh_hash "
            "ON user_sessions (refresh_token_hash)",
            "CREATE INDEX IF NOT EXISTS ix_user_sessions_family "
            "ON user_sessions (family_id)",
            "CREATE INDEX IF NOT EXISTS ix_user_sessions_expires "
            "ON user_sessions (expires_at)",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(ddl.split()[5] if "INDEX" in ddl else "index")
            except Exception as exc:
                _LOG.warning("user_sessions index: %s", exc)

    st = schema_status()
    _LOG.info("user_sessions migration status=%s applied=%s", st, applied)
    return {"applied": applied, "status": st}


def ensure_user_sessions_table() -> bool:
    """Backward-compatible alias for deploy scripts."""
    return bool(apply_user_sessions_migration().get("status", {}).get("ok"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_user_sessions_migration())
