"""
Idempotent migration: data/technical_audits.json → PostgreSQL technical_audits.

Safe to re-run: upserts by audit id; does not duplicate rows.
Does not delete JSON (dual-write phase).

Usage:
  python -m app.migrations.migrate_technical_audits_json_to_pg
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def migrate_json_to_pg(*, json_path: Path | None = None) -> dict[str, Any]:
    from app.migrations.ensure_technical_audits_pg import apply_technical_audits_migration
    from app.services.json_atomic import read_json_list
    from app.services.technical_audit_pg import count_audits_pg, upsert_audit_entry

    apply_technical_audits_migration()
    path = json_path or Path("data/technical_audits.json")
    runs = read_json_list(path) if path.exists() else []
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    from sqlalchemy import text

    from app.db import engine

    for run in runs:
        if not isinstance(run, dict):
            skipped += 1
            continue
        aid = str(run.get("id") or "").strip()
        uid = run.get("user_id")
        if not aid or uid is None:
            skipped += 1
            continue
        try:
            with engine.connect() as conn:
                existed = (
                    conn.execute(
                        text("SELECT 1 FROM technical_audits WHERE id = :id"),
                        {"id": aid},
                    ).first()
                    is not None
                )
            upsert_audit_entry(run)
            if existed:
                updated += 1
            else:
                inserted += 1
        except Exception as exc:
            msg = f"{aid}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            _LOG.exception("migrate_audit_failed %s", msg)

    pg_count = count_audits_pg()
    return {
        "json_path": str(path),
        "json_count": len(runs),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "pg_count": pg_count,
        "counts_match": pg_count >= (len(runs) - skipped) and not errors,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = migrate_json_to_pg()
    print(result)
    sys.exit(0 if result.get("counts_match") and not result.get("errors") else 1)
