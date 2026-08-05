"""Credit SaaS gate schema: apply once at deploy; assert-only at startup."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import engine

_LOG = logging.getLogger(__name__)

REQUIRED_LEDGER_COLUMNS = ("organization_id", "feature_code", "job_id", "idempotency_key")


def _has_column(table: str, column: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_table(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def schema_status() -> dict[str, Any]:
    """Read-only view of required SaaS credit gate schema."""
    missing: list[str] = []
    if not _has_table("credit_reservations"):
        missing.append("table:credit_reservations")
    for col in REQUIRED_LEDGER_COLUMNS:
        if not _has_column("credit_ledgers", col):
            missing.append(f"credit_ledgers.{col}")
    return {
        "ok": not missing,
        "missing": missing,
        "credit_reservations": _has_table("credit_reservations"),
        "ledger_columns": {
            c: _has_column("credit_ledgers", c) for c in REQUIRED_LEDGER_COLUMNS
        },
    }


def assert_credit_saas_gate_schema() -> None:
    """
    Startup-safe: NO DDL. Fail loud if migration was not applied at deploy.
    """
    st = schema_status()
    if st["ok"]:
        _LOG.info("credit_saas_gate schema OK")
        return
    msg = (
        "SaaS credit gate schema missing: "
        + ", ".join(st["missing"])
        + ". Run deploy migration: "
        "python -m app.migrations.ensure_credit_saas_gate (as table owner if needed)."
    )
    _LOG.error(msg)
    raise RuntimeError(msg)


def _create_reservations_table() -> None:
    import app.models.user  # noqa: F401
    from app.models.credit_reservation import CreditReservation  # noqa: F401
    from app.db import Base

    try:
        Base.metadata.create_all(bind=engine, tables=[CreditReservation.__table__])
        return
    except Exception as exc:
        _LOG.warning("create_all credit_reservations failed, fallback SQL: %s", exc)

    dialect = engine.dialect.name
    if dialect == "postgresql":
        ddl = """
        CREATE TABLE IF NOT EXISTS credit_reservations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            organization_id INTEGER,
            amount INTEGER NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'reserved',
            feature_code VARCHAR(64) NOT NULL,
            job_id VARCHAR(128),
            idempotency_key VARCHAR(128),
            request_id VARCHAR(64),
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS credit_reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            organization_id INTEGER,
            amount INTEGER NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'reserved',
            feature_code VARCHAR(64) NOT NULL,
            job_id VARCHAR(128),
            idempotency_key VARCHAR(128),
            request_id VARCHAR(64),
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_reservations_idempotency "
                    "ON credit_reservations (idempotency_key)"
                )
            )
        except Exception:
            pass
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_credit_reservations_user_id ON credit_reservations (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_credit_reservations_feature_code ON credit_reservations (feature_code)",
            "CREATE INDEX IF NOT EXISTS ix_credit_reservations_status ON credit_reservations (status)",
            "CREATE INDEX IF NOT EXISTS ix_credit_reservations_job_id ON credit_reservations (job_id)",
        ]:
            try:
                conn.execute(text(idx_sql))
            except Exception:
                pass


def apply_credit_saas_gate_migration() -> dict[str, Any]:
    """
    Deploy-time only: apply DDL once. Requires table-owner privileges for ALTER.
    """
    if not _has_table("credit_reservations"):
        _create_reservations_table()

    applied: list[str] = []
    for col, ddl in [
        ("organization_id", "ALTER TABLE credit_ledgers ADD COLUMN organization_id INTEGER"),
        ("feature_code", "ALTER TABLE credit_ledgers ADD COLUMN feature_code VARCHAR(64)"),
        ("job_id", "ALTER TABLE credit_ledgers ADD COLUMN job_id VARCHAR(128)"),
        ("idempotency_key", "ALTER TABLE credit_ledgers ADD COLUMN idempotency_key VARCHAR(128)"),
    ]:
        if not _has_column("credit_ledgers", col):
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(f"credit_ledgers.{col}")
                _LOG.info("added credit_ledgers.%s", col)
            except Exception as exc:
                _LOG.error("add column %s failed: %s", col, exc)
                raise

    if engine.dialect.name == "postgresql":
        for name, ddl in [
            (
                "uq_credit_ledgers_idempotency",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledgers_idempotency "
                "ON credit_ledgers (idempotency_key) WHERE idempotency_key IS NOT NULL",
            ),
            (
                "ix_credit_ledgers_feature_code",
                "CREATE INDEX IF NOT EXISTS ix_credit_ledgers_feature_code ON credit_ledgers (feature_code)",
            ),
            (
                "ix_credit_ledgers_job_id",
                "CREATE INDEX IF NOT EXISTS ix_credit_ledgers_job_id ON credit_ledgers (job_id)",
            ),
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(name)
            except Exception as exc:
                _LOG.warning("index %s: %s", name, exc)

    st = schema_status()
    if not st["ok"]:
        raise RuntimeError(f"Migration incomplete: {st['missing']}")
    _LOG.info("apply_credit_saas_gate_migration done applied=%s", applied)
    return {"applied": applied, "status": st}


def ensure_credit_saas_gate() -> None:
    """Backward-compatible alias for deploy CLI (applies DDL). """
    apply_credit_saas_gate_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_credit_saas_gate_migration())
