"""Google Map SEO — review reply drafts table."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_gbp_review_reply_drafts() -> dict[str, object]:
    from app.models.google_map_gbp import GbpReviewReplyDraft  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    name = "gbp_review_reply_drafts"
    if name not in existing:
        Base.metadata.create_all(bind=engine, tables=[GbpReviewReplyDraft.__table__])
        created.append(name)
    return {"tables_created": created}
