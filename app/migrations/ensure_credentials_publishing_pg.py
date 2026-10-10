"""Deploy-time: organizations + publishing_sites + wordpress_site_links + quarantine + api key org cols."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def _has_table(name: str) -> bool:
    return name in inspect(engine).get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in inspect(engine).get_columns(table))


def schema_status() -> dict[str, Any]:
    missing: list[str] = []
    for t in (
        "organizations",
        "organization_members",
        "publishing_sites",
        "wordpress_site_links",
        "legacy_data_quarantine",
    ):
        if not _has_table(t):
            missing.append(f"table:{t}")
    for col in ("organization_id", "created_by", "deleted_at"):
        if _has_table("user_api_keys") and not _has_column("user_api_keys", col):
            missing.append(f"user_api_keys.{col}")
    return {"ok": not missing, "missing": missing}


def apply_credentials_publishing_migration() -> dict[str, Any]:
    import app.models.organization  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.user_api_key  # noqa: F401

    from app.models.organization import Organization, OrganizationMember
    from app.models.publishing_site import LegacyDataQuarantine, PublishingSite, WordpressSiteLink

    Base.metadata.create_all(
        bind=engine,
        tables=[
            Organization.__table__,
            OrganizationMember.__table__,
            PublishingSite.__table__,
            WordpressSiteLink.__table__,
            LegacyDataQuarantine.__table__,
        ],
    )

    applied: list[str] = []
    for col, ddl in [
        ("organization_id", "ALTER TABLE user_api_keys ADD COLUMN organization_id INTEGER"),
        ("created_by", "ALTER TABLE user_api_keys ADD COLUMN created_by INTEGER"),
        ("deleted_at", "ALTER TABLE user_api_keys ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE"),
    ]:
        if _has_table("user_api_keys") and not _has_column("user_api_keys", col):
            try:
                # SQLite: without timezone type name
                if engine.dialect.name == "sqlite" and col == "deleted_at":
                    ddl = "ALTER TABLE user_api_keys ADD COLUMN deleted_at DATETIME"
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(f"user_api_keys.{col}")
            except Exception as exc:
                _LOG.warning("alter user_api_keys.%s: %s", col, exc)

    if engine.dialect.name == "postgresql":
        for ddl in [
            "CREATE INDEX IF NOT EXISTS ix_user_api_keys_org ON user_api_keys (organization_id) WHERE deleted_at IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_publishing_sites_org_platform_host "
            "ON publishing_sites (organization_id, platform, site_url_normalized) WHERE deleted_at IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_wordpress_site_links_org_url "
            "ON wordpress_site_links (organization_id, site_url) WHERE deleted_at IS NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_legacy_quarantine_store_record "
            "ON legacy_data_quarantine (source_store, source_record_id)",
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                applied.append(ddl.split()[5] if "INDEX" in ddl else "index")
            except Exception as exc:
                _LOG.warning("index: %s", exc)

    st = schema_status()
    _LOG.info("credentials_publishing migration applied=%s status=%s", applied, st)
    return {"applied": applied, "status": st}


def ensure_credentials_publishing_schema() -> None:
    apply_credentials_publishing_migration()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(apply_credentials_publishing_migration())
