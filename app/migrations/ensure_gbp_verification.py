"""Google Map SEO — GBP verification kit tables."""

from __future__ import annotations

from sqlalchemy import inspect

from app.db import Base, engine


def ensure_gbp_verification() -> dict[str, object]:
    from app.models.google_map_gbp import GbpVerificationAsset, GbpVerificationKit  # noqa: F401
    from app.models.user import User  # noqa: F401

    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created: list[str] = []
    for name, table in (
        ("gbp_verification_kits", GbpVerificationKit.__table__),
        ("gbp_verification_assets", GbpVerificationAsset.__table__),
    ):
        if name not in existing:
            Base.metadata.create_all(bind=engine, tables=[table])
            created.append(name)
    return {"tables_created": created}
