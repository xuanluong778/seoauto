"""Google Map SEO — GBP OAuth tables."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_google_map_gbp_tables() -> dict[str, object]:
    from app.models.google_map_gbp import GbpLocation, GbpOAuthConnection  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    for name, table in (
        ("gbp_oauth_connections", GbpOAuthConnection.__table__),
        ("gbp_locations", GbpLocation.__table__),
    ):
        if name not in existing:
            Base.metadata.create_all(bind=engine, tables=[table])
            created.append(name)
    return {"tables_created": created}
