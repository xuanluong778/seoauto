"""Google Map SEO — Lead Map Scanner tables."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_gbp_leads() -> dict[str, object]:
    from app.models.google_map_gbp import GbpLead, GbpLeadScan  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    for name, table in (
        ("gbp_lead_scans", GbpLeadScan.__table__),
        ("gbp_leads", GbpLead.__table__),
    ):
        if name not in existing:
            Base.metadata.create_all(bind=engine, tables=[table])
            created.append(name)
    return {"tables_created": created}
