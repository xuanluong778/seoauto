"""Create / rollback WordPress plugin connection tables (idempotent upgrade).

Prefer reusing publishing_sites (JSON) via wordpress_connections.publishing_site_id.
No existing wordpress_* tables — creates all five.

Upgrade: SQLAlchemy create_all (works on SQLite + PostgreSQL).
PostgreSQL operators may also run:
  app/migrations/sql/20260722_wordpress_plugin_connections.up.sql
Rollback:
  rollback_wordpress_plugin_tables()
  or app/migrations/sql/20260722_wordpress_plugin_connections.down.sql
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from app.db import Base, engine

TABLE_ORDER_CREATE = (
    "wordpress_connections",
    "wordpress_pairing_codes",
    "wordpress_entitlements",
    "wordpress_command_logs",
    "wordpress_publish_jobs",
    "wordpress_request_idempotency",
    "wordpress_plugin_releases",
    "wordpress_plugin_download_tokens",
    "wordpress_plugin_update_events",
)

# Drop children before parents
TABLE_ORDER_DROP = tuple(reversed(TABLE_ORDER_CREATE))

SQL_DIR = Path(__file__).resolve().parent / "sql"
UP_SQL = SQL_DIR / "20260722_wordpress_plugin_connections.up.sql"
DOWN_SQL = SQL_DIR / "20260722_wordpress_plugin_connections.down.sql"


def _model_tables():
    from app.models.wordpress_plugin import (
        WordpressCommandLog,
        WordpressConnection,
        WordpressEntitlement,
        WordpressPairingCode,
        WordpressPluginDownloadToken,
        WordpressPluginRelease,
        WordpressPluginUpdateEvent,
        WordpressPublishJob,
        WordpressRequestIdempotency,
    )

    return [
        WordpressConnection.__table__,
        WordpressPairingCode.__table__,
        WordpressEntitlement.__table__,
        WordpressCommandLog.__table__,
        WordpressPublishJob.__table__,
        WordpressRequestIdempotency.__table__,
        WordpressPluginRelease.__table__,
        WordpressPluginDownloadToken.__table__,
        WordpressPluginUpdateEvent.__table__,
    ]


def ensure_wordpress_plugin_tables() -> dict[str, object]:
    """Idempotent upgrade — create missing wordpress_* tables + release columns."""
    tables = _model_tables()
    Base.metadata.create_all(bind=engine, tables=tables)
    cols = ensure_wordpress_plugin_release_columns()
    insp = inspect(engine)
    names = set(insp.get_table_names())
    expected = set(TABLE_ORDER_CREATE)
    present = sorted(expected & names)
    return {
        "wordpress_plugin_tables": expected.issubset(names),
        "tables": present,
        "missing": sorted(expected - names),
        "release_columns": cols,
    }


def ensure_wordpress_plugin_release_columns() -> dict[str, object]:
    """Add CI/R2 release columns if table already existed without them."""
    insp = inspect(engine)
    if "wordpress_plugin_releases" not in set(insp.get_table_names()):
        return {"skipped": True, "reason": "table_missing"}
    existing = {c["name"] for c in insp.get_columns("wordpress_plugin_releases")}
    dialect = engine.dialect.name
    bool_default = "false" if dialect == "postgresql" else "0"
    int_default = "100"
    alters: list[tuple[str, str]] = [
        ("storage_key", "VARCHAR(1000) NOT NULL DEFAULT ''"),
        ("package_signature", "VARCHAR(128) NOT NULL DEFAULT ''"),
        ("rollout_percent", f"INTEGER NOT NULL DEFAULT {int_default}"),
        ("allowed_site_ids_json", "TEXT"),
        ("blocked_site_ids_json", "TEXT"),
        ("released_at", "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"),
    ]
    applied: list[str] = []
    with engine.begin() as conn:
        for name, ddl in alters:
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE wordpress_plugin_releases ADD COLUMN {name} {ddl}"))
            applied.append(name)
    return {"applied": applied, "ok": True}


def rollback_wordpress_plugin_tables() -> dict[str, object]:
    """Drop wordpress_* plugin tables (rollback). Safe if already absent."""
    dialect = engine.dialect.name
    dropped: list[str] = []
    with engine.begin() as conn:
        if dialect == "postgresql":
            for name in TABLE_ORDER_DROP:
                conn.execute(text(f"DROP TABLE IF EXISTS {name} CASCADE"))
                dropped.append(name)
        else:
            # SQLite / others
            for name in TABLE_ORDER_DROP:
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
                dropped.append(name)
    insp = inspect(engine)
    remaining = [t for t in TABLE_ORDER_CREATE if t in set(insp.get_table_names())]
    return {"rolled_back": dropped, "remaining": remaining, "ok": len(remaining) == 0}


def _exec_sql_script(conn, sql: str) -> None:
    cleaned = "\n".join(
        line
        for line in sql.splitlines()
        if line.strip().upper() not in {"BEGIN;", "COMMIT;", "BEGIN", "COMMIT"}
    )
    # Strip line comments for simple splitting; keep statement order.
    statements: list[str] = []
    buf: list[str] = []
    for line in cleaned.splitlines():
        if line.lstrip().startswith("--"):
            continue
        buf.append(line)
        if ";" in line:
            chunk = "\n".join(buf).strip()
            buf = []
            for part in chunk.split(";"):
                part = part.strip()
                if part:
                    statements.append(part)
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            statements.append(tail)
    for stmt in statements:
        conn.execute(text(stmt))


def apply_postgres_sql_upgrade() -> dict[str, object]:
    """Run raw PostgreSQL UP script (optional; prefer ensure_* for app boot)."""
    if engine.dialect.name != "postgresql":
        return {"skipped": True, "reason": "not_postgresql"}
    sql = UP_SQL.read_text(encoding="utf-8")
    with engine.begin() as conn:
        _exec_sql_script(conn, sql)
    return ensure_wordpress_plugin_tables()


def apply_postgres_sql_rollback() -> dict[str, object]:
    """Run raw PostgreSQL DOWN script."""
    if engine.dialect.name != "postgresql":
        return rollback_wordpress_plugin_tables()
    sql = DOWN_SQL.read_text(encoding="utf-8")
    with engine.begin() as conn:
        _exec_sql_script(conn, sql)
    insp = inspect(engine)
    remaining = [t for t in TABLE_ORDER_CREATE if t in set(insp.get_table_names())]
    return {"rolled_back": list(TABLE_ORDER_DROP), "remaining": remaining, "ok": len(remaining) == 0}
