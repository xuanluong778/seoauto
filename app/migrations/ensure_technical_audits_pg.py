"""Deploy-time: technical_audits table (user/org scoped)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def _has_table(name: str) -> bool:
    return name in inspect(engine).get_table_names()


def schema_status() -> dict[str, Any]:
    missing: list[str] = []
    if not _has_table("technical_audits"):
        missing.append("table:technical_audits")
    return {"ok": not missing, "missing": missing}


def apply_technical_audits_migration() -> dict[str, Any]:
    import app.models.technical_audit  # noqa: F401

    from app.models.technical_audit import TechnicalAudit

    Base.metadata.create_all(bind=engine, tables=[TechnicalAudit.__table__])

    applied: list[str] = []
    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE INDEX IF NOT EXISTS ix_technical_audits_user_at_desc "
            "ON technical_audits (user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_technical_audits_user_domain_lower "
            "ON technical_audits (user_id, lower(domain))",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_audits_user_idem "
            "ON technical_audits (user_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append("index")
            except Exception as exc:
                _LOG.warning("technical_audits index: %s", exc)
    else:
        # SQLite supports partial unique indexes
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_audits_user_idem "
                        "ON technical_audits (user_id, idempotency_key) "
                        "WHERE idempotency_key IS NOT NULL AND idempotency_key != ''"
                    )
                )
            applied.append("uq_technical_audits_user_idem")
        except Exception as exc:
            _LOG.warning("technical_audits sqlite index: %s", exc)

    st = schema_status()
    _LOG.info("technical_audits migration applied=%s status=%s", applied, st)
    return {"applied": applied, "status": st}


def ensure_technical_audits_schema() -> None:
    apply_technical_audits_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_technical_audits_migration())
