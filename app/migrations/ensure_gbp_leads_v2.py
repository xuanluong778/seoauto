"""Google Map SEO — Lead scanner schema upgrades."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine


def _add_column_if_missing(table: str, column: str, ddl: str) -> bool:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return False
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return False
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return True


def ensure_gbp_leads_v2() -> dict[str, object]:
    from app.models.google_map_gbp import GbpLead, GbpLeadApiLog, GbpLeadScan  # noqa: F401
    from app.models.user import User  # noqa: F401

    from app.migrations.ensure_gbp_leads import ensure_gbp_leads

    base = ensure_gbp_leads()
    added: list[str] = []

    scan_cols = [
        ("cache_key", "cache_key VARCHAR(64) NULL"),
        ("data_source", "data_source VARCHAR(16) NOT NULL DEFAULT 'api'"),
        ("api_request_count", "api_request_count INTEGER NOT NULL DEFAULT 0"),
        ("search_request_count", "search_request_count INTEGER NOT NULL DEFAULT 0"),
        ("detail_request_count", "detail_request_count INTEGER NOT NULL DEFAULT 0"),
        ("geocode_request_count", "geocode_request_count INTEGER NOT NULL DEFAULT 0"),
        ("cached_from_scan_id", "cached_from_scan_id INTEGER NULL"),
    ]
    for name, ddl in scan_cols:
        if _add_column_if_missing("gbp_lead_scans", name, ddl):
            added.append(f"gbp_lead_scans.{name}")

    lead_cols = [
        ("detail_fetched", "detail_fetched BOOLEAN NOT NULL DEFAULT false"),
        ("data_source", "data_source VARCHAR(16) NOT NULL DEFAULT 'search'"),
    ]
    for name, ddl in lead_cols:
        if _add_column_if_missing("gbp_leads", name, ddl):
            added.append(f"gbp_leads.{name}")

    insp = inspect(engine)
    if "gbp_lead_api_logs" not in set(insp.get_table_names()):
        Base.metadata.create_all(bind=engine, tables=[GbpLeadApiLog.__table__])
        added.append("gbp_lead_api_logs")

    return {"tables_created": base.get("tables_created", []), "columns_added": added}
