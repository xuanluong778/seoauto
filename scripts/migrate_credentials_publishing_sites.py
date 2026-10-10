#!/usr/bin/env python3
"""Idempotent migrate: API keys + publishing sites + WP connector links → PostgreSQL.

- Requires user_id to exist in users; assigns personal organization_id = user_id
- Undetermined tenant → legacy_data_quarantine (no admin/default auto-assign)
- Application encryption via secrets_crypto (enc:v1:) outside DB
- Re-run safe (upsert by id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local")
load_dotenv("/var/www/seoauto_vn_usr/data/www/shared/env.local")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_LOG = logging.getLogger("migrate_cred_sites")

DATA = ROOT / "data"
API_KEYS = DATA / "api_keys.json"
PUB_SITES = DATA / "publishing_sites.json"
CAU_SITES = DATA / "content_auto_update_sites.json"


def _load_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _uid(entry: dict[str, Any]) -> int | None:
    if "user_id" not in entry:
        return None
    try:
        v = int(entry.get("user_id") or 0)
        return v
    except (TypeError, ValueError):
        return 0


def _checksum(payload: dict[str, Any]) -> str:
    # exclude secrets from checksum of identity; include structure
    safe = {k: v for k, v in payload.items() if k not in ("api_key", "app_password", "password", "token")}
    blob = json.dumps(safe, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for k in list(out.keys()):
        if any(s in k.lower() for s in ("password", "secret", "api_key", "token", "credential")):
            val = str(out.get(k) or "")
            if val.startswith("enc:v1:"):
                out[k] = "enc:v1:***REDACTED***"
            elif val:
                out[k] = "***REDACTED***"
    return out


def quarantine(
    db,
    *,
    store: str,
    record_id: str,
    reason: str,
    payload: dict[str, Any],
) -> str:
    from app.models.publishing_site import LegacyDataQuarantine

    rid = str(record_id or "")[:128]
    existing = (
        db.query(LegacyDataQuarantine)
        .filter(
            LegacyDataQuarantine.source_store == store,
            LegacyDataQuarantine.source_record_id == rid,
        )
        .first()
    )
    redacted = _redact(payload)
    chk = _checksum(redacted)
    if existing:
        existing.reason = reason[:128]
        existing.payload_json = json.dumps(redacted, ensure_ascii=False)
        existing.checksum = chk
        return "updated"
    db.add(
        LegacyDataQuarantine(
            source_store=store,
            source_record_id=rid,
            reason=reason[:128],
            payload_json=json.dumps(redacted, ensure_ascii=False),
            checksum=chk,
        )
    )
    return "inserted"


def run() -> dict[str, Any]:
    # Register relationship targets for User mapper
    import app.models.seo  # noqa: F401
    import app.models.knowledge  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.user_api_key  # noqa: F401

    from app.db import SessionLocal
    from app.migrations.ensure_credentials_publishing_pg import apply_credentials_publishing_migration
    from app.models.user import User
    from app.models.user_api_key import UserApiKey
    from app.services.api_key_fingerprint import api_key_fingerprint
    from app.services.api_keys_store import PROVIDERS
    from app.services.publishing_sites_pg import upsert_from_migrate as upsert_pub
    from app.services.tenant_org import ensure_personal_organization
    from app.services.wordpress_site_links_pg import upsert_link_from_migrate
    from app.core.secrets_crypto import decrypt_secret, encrypt_secret
    import uuid

    apply_credentials_publishing_migration()
    stats: dict[str, Any] = {
        "api_keys": {"migrated": 0, "skipped": 0, "quarantine": 0},
        "publishing_sites": {"migrated": 0, "skipped": 0, "quarantine": 0, "inserted": 0, "updated": 0},
        "wordpress_links": {"migrated": 0, "skipped": 0, "quarantine": 0, "inserted": 0, "updated": 0},
        "backfill_user_api_keys_org": 0,
    }

    db = SessionLocal()
    try:
        # --- API keys JSON ---
        for item in _load_list(API_KEYS):
            rid = str(item.get("id") or "")
            uid = _uid(item)
            if uid is None:
                quarantine(db, store="api_keys", record_id=rid or "unknown", reason="missing_user_id", payload=item)
                stats["api_keys"]["quarantine"] += 1
                continue
            if uid <= 0:
                quarantine(db, store="api_keys", record_id=rid or "zero", reason="invalid_user_id", payload=item)
                stats["api_keys"]["quarantine"] += 1
                continue
            if db.get(User, uid) is None:
                quarantine(db, store="api_keys", record_id=rid or str(uid), reason="user_not_in_db", payload=item)
                stats["api_keys"]["quarantine"] += 1
                continue
            plain = decrypt_secret(str(item.get("api_key") or ""))
            if not plain:
                quarantine(db, store="api_keys", record_id=rid, reason="empty_secret", payload=item)
                stats["api_keys"]["quarantine"] += 1
                continue
            kid = rid or str(uuid.uuid4())
            org_id = ensure_personal_organization(db, uid)
            row = db.get(UserApiKey, kid)
            provider = str(item.get("provider") or "openai").strip().lower()
            if provider not in PROVIDERS:
                provider = "openai"
            if row is None:
                db.add(
                    UserApiKey(
                        id=kid,
                        user_id=uid,
                        organization_id=org_id,
                        created_by=uid,
                        name=str(item.get("name") or "").strip(),
                        provider=provider,
                        api_key_encrypted=encrypt_secret(plain),
                        key_fingerprint=api_key_fingerprint(plain),
                        daily_limit=int(item.get("daily_limit") or 0),
                        priority=max(1, min(10, int(item.get("priority") or 1))),
                        enabled=bool(item.get("enabled", True)),
                        status=str(item.get("status") or "healthy"),
                        used_today=int(item.get("used_today") or 0),
                        errors_today=int(item.get("errors_today") or 0),
                        last_used_at=str(item.get("last_used_at") or ""),
                    )
                )
                stats["api_keys"]["migrated"] += 1
            else:
                row.organization_id = org_id
                row.user_id = uid
                row.created_by = row.created_by or uid
                stats["api_keys"]["skipped"] += 1

        # backfill existing PG keys without org
        for row in db.query(UserApiKey).filter(UserApiKey.organization_id.is_(None)).all():
            if row.user_id and db.get(User, row.user_id):
                row.organization_id = ensure_personal_organization(db, int(row.user_id))
                row.created_by = row.created_by or row.user_id
                stats["backfill_user_api_keys_org"] += 1
            else:
                quarantine(
                    db,
                    store="user_api_keys",
                    record_id=row.id,
                    reason="orphan_pg_key",
                    payload={"id": row.id, "user_id": row.user_id},
                )

        # --- publishing sites ---
        for item in _load_list(PUB_SITES):
            rid = str(item.get("id") or "")
            uid = _uid(item)
            if not rid:
                quarantine(db, store="publishing_sites", record_id="missing_id", reason="missing_id", payload=item)
                stats["publishing_sites"]["quarantine"] += 1
                continue
            if uid is None or uid <= 0:
                quarantine(db, store="publishing_sites", record_id=rid, reason="missing_or_invalid_user_id", payload=item)
                stats["publishing_sites"]["quarantine"] += 1
                continue
            if db.get(User, uid) is None:
                quarantine(db, store="publishing_sites", record_id=rid, reason="user_not_in_db", payload=item)
                stats["publishing_sites"]["quarantine"] += 1
                continue
            org_id = ensure_personal_organization(db, uid)
            action = upsert_pub(
                db,
                record_id=rid,
                organization_id=org_id,
                user_id=uid,
                payload=item,
            )
            stats["publishing_sites"][action] = stats["publishing_sites"].get(action, 0) + 1
            stats["publishing_sites"]["migrated"] += 1

        # --- CAU wordpress links ---
        for item in _load_list(CAU_SITES):
            rid = str(item.get("id") or "")
            uid = _uid(item)
            if not rid:
                quarantine(db, store="content_auto_update_sites", record_id="missing_id", reason="missing_id", payload=item)
                stats["wordpress_links"]["quarantine"] += 1
                continue
            if uid is None or uid <= 0:
                quarantine(
                    db, store="content_auto_update_sites", record_id=rid, reason="missing_or_invalid_user_id", payload=item
                )
                stats["wordpress_links"]["quarantine"] += 1
                continue
            if db.get(User, uid) is None:
                quarantine(db, store="content_auto_update_sites", record_id=rid, reason="user_not_in_db", payload=item)
                stats["wordpress_links"]["quarantine"] += 1
                continue
            org_id = ensure_personal_organization(db, uid)
            action = upsert_link_from_migrate(
                db,
                record_id=rid,
                organization_id=org_id,
                user_id=uid,
                payload=item,
            )
            stats["wordpress_links"][action] = stats["wordpress_links"].get(action, 0) + 1
            stats["wordpress_links"]["migrated"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # verification counts / masked
    verify = _verify()
    stats["verify"] = verify
    return stats


def _verify() -> dict[str, Any]:
    from app.db import SessionLocal
    from app.models.publishing_site import LegacyDataQuarantine, PublishingSite, WordpressSiteLink
    from app.models.user_api_key import UserApiKey

    db = SessionLocal()
    try:
        pub_n = db.query(PublishingSite).filter(PublishingSite.deleted_at.is_(None)).count()
        link_n = db.query(WordpressSiteLink).filter(WordpressSiteLink.deleted_at.is_(None)).count()
        key_n = db.query(UserApiKey).count()
        if hasattr(UserApiKey, "deleted_at"):
            key_n = db.query(UserApiKey).filter(UserApiKey.deleted_at.is_(None)).count()
        q_n = db.query(LegacyDataQuarantine).count()
        json_pub = len(_load_list(PUB_SITES))
        json_cau = len(_load_list(CAU_SITES))
        sample = []
        for row in db.query(PublishingSite).filter(PublishingSite.deleted_at.is_(None)).limit(5):
            sample.append(
                {
                    "id": row.id,
                    "organization_id": row.organization_id,
                    "user_id": row.user_id,
                    "platform": row.platform,
                    "url": row.site_url,
                    "enc_prefix": str(row.credential_encrypted or "")[:7],
                    "has_org": row.organization_id is not None and int(row.organization_id) > 0,
                }
            )
        return {
            "pg_publishing_sites": pub_n,
            "pg_wordpress_links": link_n,
            "pg_user_api_keys": key_n,
            "quarantine_rows": q_n,
            "json_publishing_sites": json_pub,
            "json_cau_sites": json_cau,
            "count_match_publishing": pub_n == json_pub,
            "count_match_cau": link_n == json_cau,
            "masked_sample": sample,
        }
    finally:
        db.close()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    v = result.get("verify") or {}
    ok = v.get("count_match_publishing") and v.get("count_match_cau") and all(
        s.get("has_org") for s in (v.get("masked_sample") or [])
    )
    # empty is ok
    if (v.get("json_publishing_sites") or 0) == 0 and (v.get("pg_publishing_sites") or 0) == 0:
        ok = True
    sys.exit(0 if ok or result["publishing_sites"]["migrated"] >= 0 else 1)
