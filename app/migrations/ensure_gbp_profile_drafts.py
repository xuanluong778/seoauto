"""Google Map SEO — GBP profile AI drafts table."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_gbp_profile_drafts() -> dict[str, object]:
    from app.models.google_map_gbp import GbpProfileDraft  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    name = "gbp_profile_drafts"
    if name not in existing:
        Base.metadata.create_all(bind=engine, tables=[GbpProfileDraft.__table__])
        created.append(name)
    return {"tables_created": created}
