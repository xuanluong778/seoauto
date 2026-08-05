"""Add credit reservation + ledger audit columns for central SaaS gate."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db import engine

_LOG = logging.getLogger(__name__)


def _has_column(table: str, column: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_table(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def _create_reservations_table() -> None:
    # Import referenced models so FK metadata can resolve
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
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_reservations_idempotency ON credit_reservations (idempotency_key)"))
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


def ensure_credit_saas_gate() -> None:
    """Idempotent schema ensure for SaaS central credit gate."""
    if not _has_table("credit_reservations"):
        _create_reservations_table()

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
                _LOG.info("added credit_ledgers.%s", col)
            except Exception as exc:
                _LOG.warning("add column %s failed: %s", col, exc)

    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledgers_idempotency "
            "ON credit_ledgers (idempotency_key) WHERE idempotency_key IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS ix_credit_ledgers_feature_code ON credit_ledgers (feature_code)",
            "CREATE INDEX IF NOT EXISTS ix_credit_ledgers_job_id ON credit_ledgers (job_id)",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            except Exception as exc:
                _LOG.warning("ledger index failed: %s", exc)

    _LOG.info("ensure_credit_saas_gate complete table=%s", _has_table("credit_reservations"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_credit_saas_gate()
    print("ok")
