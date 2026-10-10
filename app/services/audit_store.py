"""Lưu kết quả quét Technical SEO — JSON + PostgreSQL dual-write (Wave 2)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.json_atomic import mutate_json_list, read_json_list

_LOG = logging.getLogger(__name__)

AUDIT_FILE = Path("data/technical_audits.json")
MAX_RUNS_PER_USER = 40


def _truncate_list(items: list | None, limit: int) -> list:
    arr = items if isinstance(items, list) else []
    if len(arr) <= limit:
        return arr
    return arr[:limit]


def _safe_list(val: object) -> list:
    return val if isinstance(val, list) else []


def _safe_dict(val: object) -> dict:
    return val if isinstance(val, dict) else {}


def normalize_audit_record(run: dict | None) -> dict | None:
    """
    Chuẩn hóa audit khi đọc — audit cũ thiếu field SaaS vẫn trả về shape ổn định, không crash.
    Không mutate bản gốc trong file JSON.
    """
    if not run or not isinstance(run, dict):
        return run
    out = dict(run)
    out["issues"] = _safe_list(out.get("issues"))
    out["technical_summary"] = _safe_dict(out.get("technical_summary"))
    gs = out.get("gsc_summary")
    out["gsc_summary"] = gs if isinstance(gs, dict) else None
    out["gsc_enriched_pages"] = _safe_list(out.get("gsc_enriched_pages"))
    out["gsc_confirmed_issues"] = _safe_list(out.get("gsc_confirmed_issues"))
    out["gsc_opportunities"] = _safe_list(out.get("gsc_opportunities"))
    out["url_inspection_results"] = _safe_list(out.get("url_inspection_results"))
    ss = out.get("saas_summary")
    out["saas_summary"] = ss if isinstance(ss, dict) else None
    out["priority_fixes"] = _safe_list(out.get("priority_fixes"))
    out["category_summaries"] = _safe_list(out.get("category_summaries"))
    out["normalized_issues"] = _safe_list(out.get("normalized_issues"))
    out["passed_checks"] = _safe_list(out.get("passed_checks"))
    out["gsc_intelligence_summary"] = _safe_dict(out.get("gsc_intelligence_summary"))
    out["disclaimers"] = _safe_list(out.get("disclaimers"))
    tdv2 = out.get("technical_dashboard_v2")
    out["technical_dashboard_v2"] = tdv2 if isinstance(tdv2, dict) else None
    out["partial_data"] = bool(out.get("partial_data"))
    out["truncated_issues"] = bool(out.get("truncated_issues"))
    out["normalized_issues_truncated"] = bool(out.get("normalized_issues_truncated"))
    out["idempotency_key"] = str(out.get("idempotency_key") or "").strip() or None
    snap = out.get("result_snapshot")
    out["result_snapshot"] = snap if isinstance(snap, dict) else None
    conf = out.get("confidence_overall")
    try:
        out["confidence_overall"] = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        out["confidence_overall"] = None
    aid = out.get("id") or out.get("audit_id")
    if aid:
        out["audit_id"] = str(aid)
    return out


def _audit_owner_id(run: dict) -> int | None:
    raw = run.get("user_id")
    if raw is None:
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    return uid if uid > 0 else None


def _is_json_orphan_audit_id(audit_id: str) -> bool:
    """True when JSON store marks this audit as legacy orphan (no user_id)."""
    aid = str(audit_id or "").strip()
    if not aid:
        return False
    for run in _read_runs():
        if str(run.get("id", "")) == aid and run.get("user_id") is None:
            return True
    return False


def _trim_retention_for_user(runs: list[dict], user_id: int) -> None:
    """Evict oldest audits for this user only — never delete other users' rows."""
    uid = int(user_id)
    user_idxs = [i for i, r in enumerate(runs) if _audit_owner_id(r) == uid]
    if len(user_idxs) <= MAX_RUNS_PER_USER:
        return
    drop = set(user_idxs[MAX_RUNS_PER_USER:])
    runs[:] = [r for i, r in enumerate(runs) if i not in drop]


def _read_runs() -> list[dict]:
    runs = read_json_list(AUDIT_FILE)
    changed = False
    for run in runs:
        if not run.get("id"):
            run["id"] = str(uuid.uuid4())
            changed = True
    if changed:
        from app.services.json_atomic import write_json_list

        write_json_list(AUDIT_FILE, runs)
    return runs


def _pg_ok() -> bool:
    try:
        from app.services.technical_audit_pg import technical_audits_pg_enabled

        return technical_audits_pg_enabled()
    except Exception:
        return False


def _pg_read() -> bool:
    try:
        from app.services.technical_audit_pg import (
            technical_audits_pg_enabled,
            technical_audits_pg_read_enabled,
        )

        return technical_audits_pg_enabled() and technical_audits_pg_read_enabled()
    except Exception:
        return False


def _json_write() -> bool:
    try:
        from app.services.technical_audit_pg import technical_audits_json_write_enabled

        return technical_audits_json_write_enabled()
    except Exception:
        return True


def _build_entry(
    *,
    user_id: int,
    source_url: str,
    result: dict,
    max_issue_rows: int,
    idempotency_key: str | None,
    audit_id: str | None = None,
) -> dict:
    issues = result.get("issues") or []
    if len(issues) > max_issue_rows:
        issues = issues[:max_issue_rows]
    idem = str(idempotency_key or "").strip()[:128] or None
    entry = {
        "id": audit_id or str(uuid.uuid4()),
        "at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "source_url": source_url,
        "domain": result.get("domain", ""),
        "pages_scanned": result.get("pages_scanned", 0),
        "technical_summary": result.get("technical_summary", {}),
        "issues": issues,
        "truncated_issues": len(result.get("issues") or []) > max_issue_rows,
        "gsc_summary": result.get("gsc_summary"),
        "gsc_enriched_pages": result.get("gsc_enriched_pages") or [],
        "gsc_confirmed_issues": result.get("gsc_confirmed_issues") or [],
        "gsc_opportunities": result.get("gsc_opportunities") or [],
        "url_inspection_results": result.get("url_inspection_results") or [],
        "confidence_overall": result.get("confidence_overall"),
        "saas_summary": result.get("saas_summary"),
        "priority_fixes": result.get("priority_fixes") or [],
        "category_summaries": result.get("category_summaries") or [],
        "normalized_issues": _truncate_list(result.get("normalized_issues"), max_issue_rows),
        "passed_checks": result.get("passed_checks") or [],
        "gsc_intelligence_summary": result.get("gsc_intelligence_summary") or {},
        "partial_data": bool(result.get("partial_data")),
        "disclaimers": result.get("disclaimers") or [],
        "normalized_issues_truncated": len(result.get("normalized_issues") or []) > max_issue_rows,
        "idempotency_key": idem,
        "result_snapshot": result,
    }
    tdv2 = result.get("technical_dashboard_v2")
    if isinstance(tdv2, dict) and tdv2.get("schema_version") == 2:
        entry["technical_dashboard_v2"] = tdv2
    return entry


def save_technical_audit(
    *,
    user_id: int,
    source_url: str,
    result: dict,
    max_issue_rows: int = 250,
    idempotency_key: str | None = None,
) -> str:
    """result: TechnicalAnalyzeResponse.model_dump() hoặc dict tương đương. Trả về audit id."""
    # Idempotent replay: prefer PG then JSON
    if idempotency_key:
        existing = get_audit_by_idempotency(user_id, idempotency_key)
        if existing and existing.get("id"):
            return str(existing["id"])

    entry = _build_entry(
        user_id=user_id,
        source_url=source_url,
        result=result,
        max_issue_rows=max_issue_rows,
        idempotency_key=idempotency_key,
    )
    audit_id = str(entry["id"])

    if _pg_ok():
        try:
            from app.services.technical_audit_pg import trim_retention_pg, upsert_audit_entry

            audit_id = upsert_audit_entry(entry)
            trim_retention_pg(user_id, keep=MAX_RUNS_PER_USER)
        except Exception:
            _LOG.exception("technical_audit_pg_write_failed id=%s", audit_id)
            if not _json_write():
                raise

    if _json_write():
        def _save(runs: list[dict]) -> str:
            # Avoid duplicate id if retry after PG success
            runs[:] = [r for r in runs if str(r.get("id", "")) != audit_id]
            entry["id"] = audit_id
            runs.insert(0, entry)
            _trim_retention_for_user(runs, user_id)
            return audit_id

        return mutate_json_list(AUDIT_FILE, _save)

    return audit_id


def get_latest_audit(user_id: int) -> dict | None:
    """Latest audit for a single user. Orphan rows without user_id are never returned."""
    uid = int(user_id)
    if uid <= 0:
        raise ValueError("user_id is required")
    if _pg_read():
        try:
            from app.services.technical_audit_pg import get_latest_pg

            hit = get_latest_pg(uid)
            if hit and not _is_json_orphan_audit_id(str(hit.get("id") or "")):
                return normalize_audit_record(hit)
        except Exception:
            _LOG.exception("technical_audit_pg_latest_failed user=%s", uid)
    for run in _read_runs():
        raw_uid = run.get("user_id")
        if raw_uid is None:
            continue
        if int(raw_uid) != uid:
            continue
        return normalize_audit_record(run)
    return None


def list_audits(limit: int = 10, *, user_id: int, offset: int = 0) -> list[dict]:
    uid = int(user_id)
    if uid <= 0:
        raise ValueError("user_id is required")
    if _pg_read():
        try:
            from app.services.technical_audit_pg import list_audits_pg

            return list_audits_pg(uid, limit=limit, offset=offset)
        except Exception:
            _LOG.exception("technical_audit_pg_list_failed user=%s", uid)
    out: list[dict] = []
    skipped = 0
    for run in _read_runs():
        raw_uid = run.get("user_id")
        if raw_uid is None or int(raw_uid) != uid:
            continue
        if skipped < offset:
            skipped += 1
            continue
        summary = {
            "at": run.get("at"),
            "user_id": run.get("user_id"),
            "domain": run.get("domain"),
            "source_url": run.get("source_url"),
            "pages_scanned": run.get("pages_scanned"),
            "technical_summary": run.get("technical_summary"),
            "health_score": None,
            "issue_count": len(run.get("issues") or []),
            "truncated_issues": run.get("truncated_issues"),
        }
        tdv2 = run.get("technical_dashboard_v2")
        if isinstance(tdv2, dict) and tdv2.get("technical_health_score") is not None:
            summary["health_score"] = tdv2.get("technical_health_score")
        elif isinstance(run.get("technical_summary"), dict):
            summary["health_score"] = (run.get("technical_summary") or {}).get("health_score")
        summary["id"] = run.get("id")
        out.append(summary)
        if len(out) >= limit:
            break
    return out


def list_mine_recent_by_domain(user_id: int, limit: int = 8, db: Any | None = None) -> list[dict]:
    """Mỗi domain chỉ giữ lần quét mới nhất (đầu file = mới)."""
    if _pg_read():
        try:
            from app.services.technical_audit_pg import list_mine_recent_by_domain_pg

            return list_mine_recent_by_domain_pg(user_id, limit=limit, db=db)
        except Exception:
            _LOG.exception("technical_audit_pg_mine_failed user=%s", user_id)
    runs = _read_runs()
    seen: set[str] = set()
    out: list[dict] = []
    for run in runs:
        raw_uid = run.get("user_id")
        if raw_uid is None or int(raw_uid) != user_id:
            continue
        dom = (run.get("domain") or "").strip().lower()
        if not dom:
            dom = (run.get("source_url") or "").strip().lower() or f"id:{run.get('id', '')}"
        if dom in seen:
            continue
        seen.add(dom)
        out.append(
            {
                "id": str(run.get("id", "")),
                "at": run.get("at"),
                "domain": run.get("domain", ""),
                "source_url": run.get("source_url", ""),
                "pages_scanned": run.get("pages_scanned", 0),
                "technical_summary": run.get("technical_summary", {}),
                "issue_count": len(run.get("issues") or []),
                "truncated_issues": run.get("truncated_issues", False),
            }
        )
        if len(out) >= limit:
            break
    return out


def get_audit_for_user(audit_id: str, user_id: int) -> dict | None:
    aid = str(audit_id).strip()
    if _pg_read():
        try:
            from app.services.technical_audit_pg import get_audit_pg

            hit = get_audit_pg(aid, user_id)
            if hit and not _is_json_orphan_audit_id(aid):
                return normalize_audit_record(hit)
        except Exception:
            _LOG.exception("technical_audit_pg_get_failed id=%s", aid)
    for run in _read_runs():
        if str(run.get("id", "")) == aid and run.get("user_id") is not None and int(run.get("user_id")) == user_id:
            return normalize_audit_record(run)
    return None


def get_audit_by_idempotency(user_id: int, idempotency_key: str) -> dict | None:
    """Return latest audit for user matching idempotency key (retry-safe)."""
    key = str(idempotency_key or "").strip()[:128]
    if not key:
        return None
    uid = int(user_id)
    if _pg_read():
        try:
            from app.services.technical_audit_pg import get_by_idempotency_pg

            hit = get_by_idempotency_pg(uid, key)
            if hit:
                return normalize_audit_record(hit)
        except Exception:
            _LOG.exception("technical_audit_pg_idem_failed user=%s", uid)
    for run in _read_runs():
        if _audit_owner_id(run) != uid:
            continue
        if str(run.get("idempotency_key") or "").strip() == key:
            return normalize_audit_record(run)
    return None


def delete_audit(audit_id: str, user_id: int) -> bool:
    aid = str(audit_id).strip()
    uid = int(user_id)
    pg_deleted = False
    if _pg_ok():
        try:
            from app.services.technical_audit_pg import delete_audit_pg

            pg_deleted = delete_audit_pg(aid, uid)
        except Exception:
            _LOG.exception("technical_audit_pg_delete_failed id=%s", aid)

    def _delete(runs: list[dict]) -> bool:
        before = len(runs)
        runs[:] = [
            r
            for r in runs
            if not (
                str(r.get("id", "")) == aid
                and r.get("user_id") is not None
                and int(r.get("user_id")) == uid
            )
        ]
        return len(runs) < before

    json_deleted = False
    if _json_write() or not pg_deleted:
        try:
            json_deleted = mutate_json_list(AUDIT_FILE, _delete)
        except Exception:
            _LOG.exception("technical_audit_json_delete_failed id=%s", aid)
    return bool(pg_deleted or json_deleted)
