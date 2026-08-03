"""Index Control — persist & query check history (SQLAlchemy)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexControlCheck, IndexControlCheckItem
from app.services.user_scope import is_admin_role


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _item_to_dict(row: IndexControlCheckItem, *, include_payload: bool = False) -> dict[str, Any]:
    checks = _json_loads(row.checks_json)
    if not checks and row.checks_json:
        try:
            checks = json.loads(row.checks_json)
        except json.JSONDecodeError:
            checks = {}
    out: dict[str, Any] = {
        "id": row.id,
        "check_id": row.check_id,
        "user_id": row.user_id,
        "domain": row.domain,
        "url_type": row.url_type,
        "url": row.url,
        "final_url": row.final_url,
        "status_code": row.status_code,
        "indexability": row.indexability,
        "main_issue": row.main_issue,
        "severity": row.severity,
        "checks": checks if isinstance(checks, dict) else {},
        "suggestion": row.suggestion,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_payload:
        payload = _json_loads(row.payload_json)
        if payload:
            out.update({k: v for k, v in payload.items() if k not in out})
    return out


def create_check_session(
    db: Session,
    *,
    user_id: int,
    domain: str | None,
    url_type: str,
    project_name: str | None = None,
) -> int:
    from app.services.submit_project_store import normalize_project_name

    check = IndexControlCheck(
        user_id=int(user_id),
        domain=(domain or "").strip() or None,
        url_type=(url_type or "website").strip().lower() or "website",
        item_count=0,
        project_name=normalize_project_name(project_name, 0),
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return int(check.id)


def append_check_session_item(
    db: Session,
    *,
    check_id: int,
    user_id: int,
    domain: str | None,
    url_type: str,
    item: dict[str, Any],
) -> int:
    checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
    row = IndexControlCheckItem(
        check_id=int(check_id),
        user_id=int(user_id),
        domain=(domain or item.get("domain") or "").strip() or None,
        url_type=(url_type or item.get("url_type") or "website").strip().lower(),
        url=str(item.get("url") or "")[:2000],
        final_url=(str(item.get("final_url") or item.get("matched_url") or "")[:2000] or None),
        status_code=int(item["status_code"]) if item.get("status_code") is not None else None,
        indexability=str(item.get("indexability") or item.get("indexability_status") or "error")[:32],
        main_issue=str(item.get("main_issue") or item.get("reason") or "HTTP error")[:128],
        severity=str(item.get("severity") or "medium")[:16],
        checks_json=_json_dumps(checks),
        suggestion=(str(item.get("suggestion") or item.get("reason") or "")[:4000] or None),
        payload_json=_json_dumps(item),
    )
    db.add(row)
    parent = db.get(IndexControlCheck, int(check_id))
    if parent:
        parent.item_count = int(parent.item_count or 0) + 1
    db.commit()
    db.refresh(row)
    return int(row.id)


def save_check_history(
    db: Session,
    *,
    user_id: int,
    domain: str | None,
    url_type: str,
    items: list[dict[str, Any]],
    project_name: str | None = None,
) -> int:
    """Lưu batch check + từng URL item. Trả về check_id."""
    from app.services.submit_project_store import normalize_project_name

    clean_items = [i for i in items if i and i.get("url")]
    check = IndexControlCheck(
        user_id=int(user_id),
        domain=(domain or "").strip() or None,
        url_type=(url_type or "website").strip().lower() or "website",
        item_count=len(clean_items),
        project_name=normalize_project_name(project_name, len(clean_items)),
    )
    db.add(check)
    db.flush()

    for item in clean_items:
        checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
        db.add(
            IndexControlCheckItem(
                check_id=check.id,
                user_id=int(user_id),
                domain=(domain or item.get("domain") or "").strip() or None,
                url_type=(url_type or item.get("url_type") or "website").strip().lower(),
                url=str(item.get("url") or "")[:2000],
                final_url=(str(item.get("final_url") or "")[:2000] or None),
                status_code=int(item["status_code"]) if item.get("status_code") is not None else None,
                indexability=str(item.get("indexability") or "error")[:32],
                main_issue=str(item.get("main_issue") or "HTTP error")[:128],
                severity=str(item.get("severity") or "low")[:16],
                checks_json=_json_dumps(checks),
                suggestion=(str(item.get("suggestion") or "")[:4000] or None),
                payload_json=_json_dumps(item),
            )
        )
    db.commit()
    db.refresh(check)
    return int(check.id)


def list_history_items(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    domain: str | None = None,
    url_type: str | None = None,
    indexability: str | None = None,
    severity: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    q = select(IndexControlCheckItem).order_by(desc(IndexControlCheckItem.created_at))
    if not is_admin_role(role):
        q = q.where(IndexControlCheckItem.user_id == int(user_id))
    if domain:
        q = q.where(IndexControlCheckItem.domain == domain.strip().lower())
    if url_type:
        q = q.where(IndexControlCheckItem.url_type == url_type.strip().lower())
    if indexability:
        q = q.where(IndexControlCheckItem.indexability == indexability.strip().lower())
    if severity:
        q = q.where(IndexControlCheckItem.severity == severity.strip().lower())
    if date_from:
        q = q.where(IndexControlCheckItem.created_at >= date_from)
    if date_to:
        q = q.where(IndexControlCheckItem.created_at <= date_to)

    rows = db.scalars(q.offset(max(0, offset)).limit(min(max(1, limit), 200))).all()
    items = [_item_to_dict(r) for r in rows]
    domains = sorted({str(i.get("domain") or "") for i in items if i.get("domain")})
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "domains": domains,
        "is_admin": is_admin_role(role),
    }


def get_history_item(
    db: Session,
    *,
    item_id: int,
    user_id: int,
    role: str | None,
) -> dict[str, Any] | None:
    row = db.get(IndexControlCheckItem, int(item_id))
    if not row:
        return None
    if not is_admin_role(role) and row.user_id != int(user_id):
        return None
    item = _item_to_dict(row, include_payload=True)
    item["ok"] = True
    return item


def delete_history_item(
    db: Session,
    *,
    item_id: int,
    user_id: int,
    role: str | None,
) -> bool:
    row = db.get(IndexControlCheckItem, int(item_id))
    if not row:
        return False
    if not is_admin_role(role) and row.user_id != int(user_id):
        return False
    check_id = row.check_id
    db.delete(row)
    db.flush()
    remaining = db.scalar(
        select(IndexControlCheckItem.id)
        .where(IndexControlCheckItem.check_id == check_id)
        .limit(1)
    )
    if not remaining:
        parent = db.get(IndexControlCheck, check_id)
        if parent:
            db.delete(parent)
    db.commit()
    return True


def delete_all_history(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    target_user_id: int | None = None,
) -> int:
    """Xóa toàn bộ lịch sử của user (owner) hoặc target user (admin)."""
    uid = int(target_user_id if is_admin_role(role) and target_user_id else user_id)
    if not is_admin_role(role) and uid != int(user_id):
        return 0
    items = db.scalars(select(IndexControlCheckItem).where(IndexControlCheckItem.user_id == uid)).all()
    n = len(items)
    check_ids = {i.check_id for i in items}
    for i in items:
        db.delete(i)
    for cid in check_ids:
        parent = db.get(IndexControlCheck, cid)
        if parent:
            db.delete(parent)
    db.commit()
    return n


def _index_label_from_item(item: dict[str, Any]) -> str:
    index_status = str(item.get("index_status") or "").lower()
    if index_status in ("indexed", "index", "INDEX"):
        return "Index"
    if str(item.get("indexability") or "").lower() == "indexable":
        return "Index"
    if index_status in ("captcha_required", "pending_retry", "unknown", "error", "CAPTCHA_REQUIRED", "PENDING_RETRY", "UNKNOWN", "ERROR"):
        return index_status.upper() if index_status.islower() else index_status
    return "No"


def _index_label_from_row(row: dict[str, Any]) -> str:
    status = str(row.get("status") or row.get("index_status") or "").lower()
    if status in ("indexed", "index", "INDEX"):
        return "Index"
    label = str(row.get("status_label") or "").strip()
    if label == "Index":
        return "Index"
    if status in ("pending", "") and not label:
        return "—"
    if status in ("not_indexed", "not_found", "NO_INDEX") or label == "No":
        return "No"
    if status in ("captcha_required", "pending_retry", "unknown", "error", "CAPTCHA_REQUIRED", "PENDING_RETRY", "UNKNOWN", "ERROR"):
        return status.upper() if status.islower() else status
    if label and label not in ("—", "…"):
        return label
    return "No" if status else "—"


def _build_check_free_xlsx_rows(
    rows: list[dict[str, Any]],
    *,
    exported_at: str | None = None,
) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Check Index"
    headers = [
        "STT",
        "URL",
        "Query site",
        "Index status",
        "HTTP status",
        "Khả năng index",
        "Matched URL",
        "Title",
        "Reason",
        "Checked at",
        "Retry count",
    ]
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True)

    ts = exported_at or datetime.now(timezone.utc).isoformat()
    for idx, row in enumerate(rows, start=1):
        ws.append([
            idx,
            row.get("url") or "",
            row.get("query") or "",
            row.get("index_status") or row.get("index_label") or _index_label_from_row(row),
            row.get("http_status") or "—",
            row.get("indexability") or row.get("indexability_status") or "—",
            row.get("matched_url") or row.get("final_url") or "",
            row.get("title") or row.get("page_title") or "—",
            row.get("reason") or row.get("message") or row.get("suggestion") or row.get("main_issue") or "",
            row.get("checked_at") or row.get("created_at") or ts,
            row.get("retry_count") or 0,
        ])

    for col in ws.columns:
        max_len = 0
        letter = col[0].column_letter
        for cell in col:
            val = str(cell.value or "")
            max_len = max(max_len, min(len(val), 80))
        ws.column_dimensions[letter].width = max(10, min(max_len + 2, 60))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_check_free_rows_xlsx(rows: list[dict[str, Any]]) -> bytes:
    clean = [r for r in rows if r and r.get("url")]
    return _build_check_free_xlsx_rows(clean)


def list_check_free_sessions(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    q = (
        select(IndexControlCheck)
        .where(IndexControlCheck.url_type == "check_free")
        .order_by(desc(IndexControlCheck.created_at))
    )
    if not is_admin_role(role):
        q = q.where(IndexControlCheck.user_id == int(user_id))

    rows = db.scalars(q.offset(max(0, offset)).limit(min(max(1, limit), 100))).all()
    sessions: list[dict[str, Any]] = []
    for row in rows:
        indexed_n = 0
        items = db.scalars(
            select(IndexControlCheckItem).where(IndexControlCheckItem.check_id == row.id)
        ).all()
        for it in items:
            if _index_label_from_item(_item_to_dict(it)) == "Index":
                indexed_n += 1
        sessions.append({
            "check_id": row.id,
            "domain": row.domain,
            "url_type": row.url_type,
            "project_name": row.project_name,
            "item_count": row.item_count,
            "indexed_count": indexed_n,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return {"ok": True, "count": len(sessions), "sessions": sessions}


def get_check_free_session_items(
    db: Session,
    *,
    check_id: int,
    user_id: int,
    role: str | None,
) -> dict[str, Any] | None:
    parent = db.get(IndexControlCheck, int(check_id))
    if not parent or parent.url_type != "check_free":
        return None
    if not is_admin_role(role) and parent.user_id != int(user_id):
        return None
    items = db.scalars(
        select(IndexControlCheckItem)
        .where(IndexControlCheckItem.check_id == parent.id)
        .order_by(IndexControlCheckItem.id)
    ).all()
    return {
        "ok": True,
        "check_id": parent.id,
        "domain": parent.domain,
        "project_name": parent.project_name,
        "item_count": parent.item_count,
        "created_at": parent.created_at.isoformat() if parent.created_at else None,
        "items": [_item_to_dict(i, include_payload=True) for i in items],
    }


def export_check_free_session_xlsx(
    db: Session,
    *,
    check_id: int,
    user_id: int,
    role: str | None,
) -> bytes | None:
    session = get_check_free_session_items(
        db, check_id=check_id, user_id=user_id, role=role
    )
    if not session:
        return None

    rows: list[dict[str, Any]] = []
    for item in session.get("items") or []:
        payload = item.get("checks") if isinstance(item.get("checks"), dict) else {}
        if item.get("index_status"):
            payload = item
        status_code = item.get("status_code")
        http_label = str(status_code) if status_code is not None else "—"
        rows.append({
            "url": item.get("url") or "",
            "query": item.get("query") or payload.get("query") or "",
            "index_status": item.get("index_status") or payload.get("index_status") or _index_label_from_item(item),
            "http_status": http_label,
            "indexability": payload.get("indexability_status") or item.get("indexability") or "—",
            "matched_url": item.get("matched_url") or item.get("final_url") or payload.get("matched_url") or "",
            "title": item.get("title") or item.get("page_title") or payload.get("title") or payload.get("page_title") or "—",
            "reason": item.get("reason") or item.get("suggestion") or item.get("main_issue") or payload.get("reason") or "",
            "checked_at": item.get("checked_at") or item.get("created_at") or session.get("created_at") or "",
            "retry_count": item.get("retry_count") or payload.get("retry_count") or 0,
        })
    return _build_check_free_xlsx_rows(rows, exported_at=session.get("created_at"))


def delete_check_free_session(
    db: Session,
    *,
    check_id: int,
    user_id: int,
    role: str | None,
) -> bool:
    parent = db.get(IndexControlCheck, int(check_id))
    if not parent or parent.url_type != "check_free":
        return False
    if not is_admin_role(role) and parent.user_id != int(user_id):
        return False
    db.delete(parent)
    db.commit()
    return True


def delete_all_check_free_sessions(
    db: Session,
    *,
    user_id: int,
    role: str | None,
) -> int:
    q = select(IndexControlCheck).where(IndexControlCheck.url_type == "check_free")
    if not is_admin_role(role):
        q = q.where(IndexControlCheck.user_id == int(user_id))
    rows = db.scalars(q).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def parse_date_param(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        if len(text) <= 10:
            dt = datetime.strptime(text, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
