"""Index Control — tab Kết quả (submit batches + index stats)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexNowSubmit, IndexNowSubmitLog
from app.services.submit_project_store import (
    _indexed_label,
    _json_loads,
    _log_to_row,
    get_submit_project,
    make_project_name,
)
from app.services.user_scope import is_admin_role

DEFAULT_DRIPFEED_DAYS = 1


def safe_percent(numerator: int, denominator: int) -> int:
    num = max(0, int(numerator or 0))
    den = max(0, int(denominator or 0))
    if den <= 0:
        return 0
    return min(100, max(0, round(num * 100 / den)))


def _parse_date_param(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _dripfeed_days_from_note(note: str | None) -> int:
    raw = str(note or "").strip()
    if not raw:
        return DEFAULT_DRIPFEED_DAYS
    try:
        import json

        data = json.loads(raw)
        if isinstance(data, dict):
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else data
            days = int(meta.get("dripfeed_days") or DEFAULT_DRIPFEED_DAYS)
            return max(1, days)
    except Exception:
        pass
    return DEFAULT_DRIPFEED_DAYS


def _submit_ui_status(submit_status: str, sent_count: int, total_links: int) -> str:
    st = str(submit_status or "").strip().lower()
    total = max(0, int(total_links or 0))
    sent = max(0, int(sent_count or 0))
    if st in ("failed", "validation_only"):
        return "error"
    if st == "success" and (total == 0 or sent >= total):
        return "completed"
    if st == "partial" or (sent > 0 and sent < total):
        return "processing"
    if st == "success":
        return "completed"
    return "processing"


def _submit_ui_label(code: str) -> str:
    if code == "completed":
        return "Hoàn tất"
    if code == "error":
        return "Lỗi"
    return "Đang xử lý"


def _check_ui_status(
    *,
    submit_status: str,
    checked_count: int,
    total_links: int,
    dripfeed_days: int,
    created_at: datetime | None,
) -> tuple[str, str]:
    """Trả (code, label) cho cột trạng thái check index."""
    if str(submit_status or "").lower() in ("failed", "validation_only"):
        return "error", "Lỗi"

    total = max(0, int(total_links or 0))
    checked = max(0, int(checked_count or 0))
    if total <= 0 or checked <= 0:
        return "not_checked", "Chưa check"
    if checked >= total:
        return "completed", "Hoàn tất"

    days_left = 0
    if created_at:
        now = datetime.now(timezone.utc)
        ca = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        elapsed = max(0, (now - ca).days)
        days_left = max(0, int(dripfeed_days or DEFAULT_DRIPFEED_DAYS) - elapsed)

    if days_left > 0:
        return "processing", f"Đang xử lý · {days_left} ngày còn lại"
    return "processing", "Đang xử lý"


def _count_index_stats(logs: list[IndexNowSubmitLog]) -> tuple[int, int, int]:
    """indexed_count, checked_count, sent_count."""
    indexed = 0
    checked = 0
    sent = 0
    for log in logs:
        if str(log.send_status or "") == "sent":
            sent += 1
        payload = _json_loads(log.payload_json)
        label = _indexed_label(payload)
        if label in ("Index", "No"):
            checked += 1
        if label == "Index":
            indexed += 1
    return indexed, checked, sent


def _batch_row(
    row: IndexNowSubmit,
    *,
    logs: list[IndexNowSubmitLog],
) -> dict[str, Any]:
    name = row.project_name or make_project_name(row.url_count, when=row.created_at)
    total_links = max(0, int(row.url_count or 0))
    indexed_count, checked_count, sent_count = _count_index_stats(logs)
    dripfeed_days = _dripfeed_days_from_note(row.note)
    submit_code = _submit_ui_status(row.submit_status, sent_count, total_links)
    check_code, check_label = _check_ui_status(
        submit_status=row.submit_status,
        checked_count=checked_count,
        total_links=total_links,
        dripfeed_days=dripfeed_days,
        created_at=row.created_at,
    )
    return {
        "id": row.id,
        "batch_name": name,
        "project_name": name,
        "total_links": total_links,
        "uploaded_at": row.created_at.isoformat() if row.created_at else None,
        "dripfeed_days": dripfeed_days,
        "submitted_count": sent_count,
        "submitted_percent": safe_percent(sent_count, total_links),
        "submit_status": submit_code,
        "submit_status_label": _submit_ui_label(submit_code),
        "check_status": check_code,
        "check_status_label": check_label,
        "indexed_count": indexed_count,
        "indexed_percent": safe_percent(indexed_count, total_links),
        "domain": row.domain,
        "raw_submit_status": row.submit_status,
    }


def list_submit_results(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    submit_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = select(IndexNowSubmit).order_by(desc(IndexNowSubmit.created_at))
    if not is_admin_role(role):
        query = query.where(IndexNowSubmit.user_id == int(user_id))

    dt_from = _parse_date_param(date_from)
    dt_to = _parse_date_param(date_to, end_of_day=True)
    if dt_from:
        query = query.where(IndexNowSubmit.created_at >= dt_from)
    if dt_to:
        query = query.where(IndexNowSubmit.created_at <= dt_to)

    search = str(q or "").strip()
    if search:
        query = query.where(IndexNowSubmit.project_name.ilike(f"%{search}%"))

    rows = db.scalars(
        query.offset(max(0, offset)).limit(min(max(1, limit), 100))
    ).all()

    batches: list[dict[str, Any]] = []
    for row in rows:
        logs = list(
            db.scalars(
                select(IndexNowSubmitLog)
                .where(IndexNowSubmitLog.submit_id == row.id)
                .order_by(IndexNowSubmitLog.id)
            ).all()
        )
        batch = _batch_row(row, logs=logs)
        if submit_status:
            want = str(submit_status).strip().lower()
            if batch["submit_status"] != want and batch["check_status"] != want:
                continue
        batches.append(batch)

    total_q = select(func.count(IndexNowSubmit.id))
    if not is_admin_role(role):
        total_q = total_q.where(IndexNowSubmit.user_id == int(user_id))
    if dt_from:
        total_q = total_q.where(IndexNowSubmit.created_at >= dt_from)
    if dt_to:
        total_q = total_q.where(IndexNowSubmit.created_at <= dt_to)
    if search:
        total_q = total_q.where(IndexNowSubmit.project_name.ilike(f"%{search}%"))
    total = int(db.scalar(total_q) or 0)

    return {"ok": True, "count": len(batches), "total": total, "batches": batches}


def _google_index_label(indexed: str) -> str:
    if indexed == "Index":
        return "Index"
    if indexed == "No":
        return "No Index"
    return "Chưa check"


def _check_item_status(indexed: str) -> str:
    if indexed == "Index":
        return "Hoàn tất"
    if indexed == "No":
        return "Hoàn tất"
    return "Chưa check"


def _submit_item_label(send_status: str) -> str:
    st = str(send_status or "").strip().lower()
    if st == "sent":
        return "Đã gửi"
    if st == "duplicate":
        return "Trùng lặp"
    if st == "failed":
        return "Lỗi"
    return st or "—"


def get_submit_result_detail(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    role: str | None,
) -> dict[str, Any] | None:
    project = get_submit_project(
        db, project_id=project_id, user_id=user_id, role=role
    )
    if not project:
        return None

    parent = db.get(IndexNowSubmit, int(project_id))
    logs = list(
        db.scalars(
            select(IndexNowSubmitLog)
            .where(IndexNowSubmitLog.submit_id == int(project_id))
            .order_by(IndexNowSubmitLog.id)
        ).all()
    ) if parent else []

    batch = _batch_row(parent, logs=logs) if parent else {}
    items: list[dict[str, Any]] = []
    for idx, log in enumerate(logs, start=1):
        row = _log_to_row(log)
        payload = _json_loads(log.payload_json)
        indexed = _indexed_label(payload)
        items.append({
            **row,
            "stt": idx,
            "submit_status_label": _submit_item_label(log.send_status),
            "check_status_label": _check_item_status(indexed),
            "google_index": _google_index_label(indexed),
            "no_index_reason": (
                str(payload.get("message") or "").strip()
                if indexed == "No"
                else ""
            ),
            "submitted_at": log.created_at.isoformat() if log.created_at else None,
            "last_checked_at": str(payload.get("checked_at") or "").strip() or None,
        })

    return {
        **project,
        **batch,
        "items": items,
    }
