"""Google Map SEO — GBP posts table."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_gbp_posts() -> dict[str, object]:
    from app.models.google_map_gbp import GbpPost  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    name = "gbp_posts"
    if name not in existing:
        Base.metadata.create_all(bind=engine, tables=[GbpPost.__table__])
        created.append(name)
    return {"tables_created": created}
