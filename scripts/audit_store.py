"""Lưu kết quả quét Technical SEO để hiển thị trên Dashboard audit."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

AUDIT_FILE = Path("data/technical_audits.json")
MAX_RUNS = 40


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


def _read_runs() -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    try:
        data = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    runs = data if isinstance(data, list) else []
    changed = False
    for run in runs:
        if not run.get("id"):
            run["id"] = str(uuid.uuid4())
            changed = True
    if changed:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_FILE.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    return runs


def save_technical_audit(
    *,
    user_id: int,
    source_url: str,
    result: dict,
    max_issue_rows: int = 250,
) -> str:
    """result: TechnicalAnalyzeResponse.model_dump() hoặc dict tương đương. Trả về audit id."""
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    runs = _read_runs()
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
    runs.insert(0, entry)
    del runs[MAX_RUNS:]
    AUDIT_FILE.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit_id


def get_latest_audit(user_id: int | None = None) -> dict | None:
    for run in _read_runs():
        if user_id is not None and int(run.get("user_id", -1)) != user_id:
            continue
        return normalize_audit_record(run)
    return None


def list_audits(limit: int = 10, user_id: int | None = None) -> list[dict]:
    out: list[dict] = []
    for run in _read_runs():
        if user_id is not None and int(run.get("user_id", -1)) != user_id:
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
        if int(run.get("user_id", -1)) != user_id:
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
        if str(run.get("id", "")) == aid and int(run.get("user_id", -1)) == user_id:
            return normalize_audit_record(run)
    return None


def delete_audit(audit_id: str, user_id: int) -> bool:
    aid = str(audit_id).strip()
    runs = _read_runs()
    new_runs = [
        r
        for r in runs
        if not (str(r.get("id", "")) == aid and int(r.get("user_id", -1)) == user_id)
    ]
    if len(new_runs) == len(runs):
        return False
    AUDIT_FILE.write_text(json.dumps(new_runs, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
