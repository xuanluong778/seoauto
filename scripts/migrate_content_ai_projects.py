#!/usr/bin/env python3
"""Idempotent migrate: Content AI projects JSON → PostgreSQL (org-scoped).

- Valid user_id → personal organization_id = user_id
- Undetermined tenant → legacy_data_quarantine
- Secrets stripped from payload before persist
- Re-run safe (upsert by id + checksum)
- GO if pg active count matches migrate-source valid count after migrate
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "env.local")
load_dotenv("/var/www/seoauto_vn_usr/data/www/shared/env.local")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_LOG = logging.getLogger("migrate_content_ai")

DATA = ROOT / "data"
LIVE = DATA / "content_ai_projects.json"
RECOVERY_CANDIDATES = [
    Path("/var/www/seoauto_vn_usr/data/backups/quarantine_public_leaks_20260803/data/content_ai_projects.json"),
    Path("/var/www/seoauto_vn_usr/data/backups/content_ai_projects_20260805_223239/json/recovery_content_ai_projects.json"),
]


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
        return int(entry.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def _checksum(payload: dict[str, Any]) -> str:
    safe = {
        k: v
        for k, v in payload.items()
        if not any(s in str(k).lower() for s in ("password", "secret", "api_key", "token", "credential"))
    }
    blob = json.dumps(safe, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.content_ai_projects_pg import strip_secrets

    out = strip_secrets(dict(payload))
    # also strip content bodies in quarantine to keep size small
    if "content" in out and isinstance(out["content"], str) and len(out["content"]) > 200:
        out["content"] = out["content"][:200] + "…[redacted_body]"
    draft = out.get("draft_output")
    if isinstance(draft, dict) and isinstance(draft.get("content"), str) and len(draft["content"]) > 200:
        draft = dict(draft)
        draft["content"] = draft["content"][:200] + "…[redacted_body]"
        out["draft_output"] = draft
    return out


def quarantine(db, *, store: str, record_id: str, reason: str, payload: dict[str, Any]) -> str:
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


def _merge_sources() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Live first, then recover missing ids from recovery backup (do not delete live)."""
    meta: dict[str, Any] = {"live_path": str(LIVE), "live_count": 0, "recovery_path": None, "recovery_count": 0}
    by_id: dict[str, dict[str, Any]] = {}
    live = _load_list(LIVE)
    meta["live_count"] = len(live)
    for item in live:
        rid = str(item.get("id") or "").strip()
        if rid:
            by_id[rid] = item

    recovery_path = None
    force = str(os.getenv("CONTENT_AI_MIGRATE_RECOVERY", "1")).strip().lower() in {"1", "true", "yes", "on"}
    if force or not by_id:
        for cand in RECOVERY_CANDIDATES:
            if cand.exists():
                recovery_path = cand
                break
    if recovery_path is not None:
        rec = _load_list(recovery_path)
        meta["recovery_path"] = str(recovery_path)
        meta["recovery_count"] = len(rec)
        for item in rec:
            rid = str(item.get("id") or "").strip()
            if rid and rid not in by_id:
                by_id[rid] = item

    items = list(by_id.values())
    meta["merged_count"] = len(items)
    return items, meta


def run() -> dict[str, Any]:
    import app.models.knowledge  # noqa: F401
    import app.models.organization  # noqa: F401
    import app.models.plan  # noqa: F401
    import app.models.publishing_site  # noqa: F401
    import app.models.seo  # noqa: F401
    import app.models.subscription  # noqa: F401
    import app.models.usage_limit  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.content_ai_project  # noqa: F401

    from app.db import SessionLocal
    from app.migrations.ensure_content_ai_projects_pg import apply_content_ai_projects_migration
    from app.migrations.ensure_credentials_publishing_pg import apply_credentials_publishing_migration
    from app.models.content_ai_project import ContentAiProject
    from app.models.publishing_site import LegacyDataQuarantine
    from app.models.user import User
    from app.services.content_ai_projects_pg import entry_checksum, sanitize_entry, upsert_from_migrate
    from app.services.tenant_org import ensure_personal_organization

    apply_credentials_publishing_migration()
    apply_content_ai_projects_migration()

    items, source_meta = _merge_sources()
    stats: dict[str, Any] = {
        "source": source_meta,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "quarantine": 0,
        "migrated": 0,
        "secret_fields_stripped": 0,
    }

    db = SessionLocal()
    try:
        for item in items:
            rid = str(item.get("id") or "")
            uid = _uid(item)
            raw_keys = list(item.keys())
            safe = sanitize_entry(item)
            if len(safe.keys()) < len(raw_keys):
                stats["secret_fields_stripped"] += 1
            if not rid:
                quarantine(db, store="content_ai_projects", record_id="missing_id", reason="missing_id", payload=item)
                stats["quarantine"] += 1
                continue
            if uid is None or uid <= 0:
                quarantine(db, store="content_ai_projects", record_id=rid, reason="missing_or_invalid_user_id", payload=item)
                stats["quarantine"] += 1
                continue
            if db.get(User, uid) is None:
                quarantine(db, store="content_ai_projects", record_id=rid, reason="user_not_in_db", payload=item)
                stats["quarantine"] += 1
                continue
            org_id = ensure_personal_organization(db, uid)
            action = upsert_from_migrate(
                db,
                record_id=rid,
                organization_id=org_id,
                user_id=uid,
                payload=safe,
            )
            stats[action] = stats.get(action, 0) + 1
            stats["migrated"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    verify = _verify(source_meta=source_meta, expected_migrated=stats["migrated"])
    stats["verify"] = verify
    stats["go"] = bool(verify.get("go"))
    return stats


def _verify(*, source_meta: dict[str, Any], expected_migrated: int) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.models.content_ai_project import ContentAiProject
    from app.models.publishing_site import LegacyDataQuarantine
    from app.services.content_ai_projects_pg import entry_checksum, row_to_entry

    db = SessionLocal()
    try:
        pg_n = db.query(ContentAiProject).filter(ContentAiProject.deleted_at.is_(None)).count()
        q_n = (
            db.query(LegacyDataQuarantine)
            .filter(LegacyDataQuarantine.source_store == "content_ai_projects")
            .count()
        )
        orgs = {
            int(r[0])
            for r in db.query(ContentAiProject.organization_id)
            .filter(ContentAiProject.deleted_at.is_(None))
            .distinct()
            .all()
        }
        missing_org = (
            db.query(ContentAiProject)
            .filter(ContentAiProject.deleted_at.is_(None), ContentAiProject.organization_id.is_(None))
            .count()
        )
        # sample masked: no content body
        samples = []
        for row in (
            db.query(ContentAiProject)
            .filter(ContentAiProject.deleted_at.is_(None))
            .order_by(ContentAiProject.created_at.desc())
            .limit(5)
            .all()
        ):
            e = row_to_entry(row)
            samples.append(
                {
                    "id": e.get("id"),
                    "organization_id": e.get("organization_id"),
                    "user_id": e.get("user_id"),
                    "title_len": len(str(e.get("title") or "")),
                    "content_len": len(str(e.get("content") or "")),
                    "has_org": bool(e.get("organization_id")),
                    "checksum": entry_checksum(e)[:12],
                }
            )
        # GO: every migrated row has org; pg == migrated (+0 dual); quarantine accounted
        count_match = int(pg_n) == int(expected_migrated)
        go = count_match and missing_org == 0 and int(pg_n) >= 0
        return {
            "pg_active": pg_n,
            "quarantine_content_ai": q_n,
            "distinct_orgs": sorted(orgs),
            "missing_org": missing_org,
            "source_merged": source_meta.get("merged_count"),
            "expected_migrated": expected_migrated,
            "count_match_migrated": count_match,
            "masked_sample": samples,
            "go": go,
            "decision": "GO" if go else "NO-GO",
        }
    finally:
        db.close()


if __name__ == "__main__":
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("go") else 2)
