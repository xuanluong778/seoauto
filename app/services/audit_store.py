"""Lưu kết quả quét Technical SEO để hiển thị trên Dashboard audit."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.json_atomic import mutate_json_list, read_json_list

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


def save_technical_audit(
    *,
    user_id: int,
    source_url: str,
    result: dict,
    max_issue_rows: int = 250,
) -> str:
    """result: TechnicalAnalyzeResponse.model_dump() hoặc dict tương đương. Trả về audit id."""
    issues = result.get("issues") or []
    if len(issues) > max_issue_rows:
        issues = issues[:max_issue_rows]
    audit_id = str(uuid.uuid4())
    entry = {
        "id": audit_id,
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
    }
    tdv2 = result.get("technical_dashboard_v2")
    if isinstance(tdv2, dict) and tdv2.get("schema_version") == 2:
        entry["technical_dashboard_v2"] = tdv2
    def _save(runs: list[dict]) -> str:
        runs.insert(0, entry)
        _trim_retention_for_user(runs, user_id)
        return audit_id

    return mutate_json_list(AUDIT_FILE, _save)


def get_latest_audit(user_id: int) -> dict | None:
    """Latest audit for a single user. Orphan rows without user_id are never returned."""
    uid = int(user_id)
    if uid <= 0:
        raise ValueError("user_id is required")
    for run in _read_runs():
        raw_uid = run.get("user_id")
        if raw_uid is None:
            continue
        if int(raw_uid) != uid:
            continue
        return normalize_audit_record(run)
    return None


def list_audits(limit: int = 10, *, user_id: int) -> list[dict]:
    uid = int(user_id)
    if uid <= 0:
        raise ValueError("user_id is required")
    out: list[dict] = []
    for run in _read_runs():
        raw_uid = run.get("user_id")
        if raw_uid is None or int(raw_uid) != uid:
            continue
        summary = {
            "at": run.get("at"),
            "user_id": run.get("user_id"),
            "domain": run.get("domain"),
            "source_url": run.get("source_url"),
            "pages_scanned": run.get("pages_scanned"),
            "technical_summary": run.get("technical_summary"),
            "issue_count": len(run.get("issues") or []),
            "truncated_issues": run.get("truncated_issues"),
        }
        summary["id"] = run.get("id")
        out.append(summary)
        if len(out) >= limit:
            break
    return out


def list_mine_recent_by_domain(user_id: int, limit: int = 8) -> list[dict]:
    """Mỗi domain chỉ giữ lần quét mới nhất (đầu file = mới)."""
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
    for run in _read_runs():
        if str(run.get("id", "")) == aid and run.get("user_id") is not None and int(run.get("user_id")) == user_id:
            return normalize_audit_record(run)
    return None


def delete_audit(audit_id: str, user_id: int) -> bool:
    aid = str(audit_id).strip()
    uid = int(user_id)

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

    return mutate_json_list(AUDIT_FILE, _delete)
