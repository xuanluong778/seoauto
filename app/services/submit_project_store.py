"""Submit Indexing — projects (batches) with URL table metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexNowSubmit, IndexNowSubmitLog
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


def make_project_name(url_count: int, *, when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    return f"{url_count}-links-at-{dt.strftime('%d-%m-%Y')}"


def normalize_project_name(name: str | None, url_count: int) -> str:
    raw = str(name or "").strip()
    if not raw:
        return make_project_name(url_count)
    collapsed = " ".join(raw.split())
    return collapsed[:255] if collapsed else make_project_name(url_count)


def _indexed_label(payload: dict[str, Any]) -> str:
    label = str(payload.get("indexed") or payload.get("indexed_label") or "").strip()
    if label in ("Index", "No"):
        return label
    status = str(payload.get("index_status") or payload.get("status") or "").lower()
    if status == "indexed":
        return "Index"
    if status in ("not_indexed", "not_found", "cannot_check", "unknown"):
        return "No"
    return ""


def _broken_label(payload: dict[str, Any], indexed: str) -> str:
    broken = str(payload.get("broken") or "").strip()
    if broken:
        return broken
    if not indexed:
        return "not check indexed"
    return ""


def _log_to_row(log: IndexNowSubmitLog) -> dict[str, Any]:
    payload = _json_loads(log.payload_json)
    indexed = _indexed_label(payload)
    return {
        "id": log.id,
        "submit_id": log.submit_id,
        "url": log.url,
        "send_status": log.send_status,
        "indexed": indexed or "—",
        "status_code": payload.get("status_code") or payload.get("http_status") or "—",
        "indexability": payload.get("indexability") or "—",
        "redirect_url": payload.get("redirect_url") or payload.get("final_url") or "—",
        "broken": _broken_label(payload, indexed),
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def list_submit_projects(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    q = select(IndexNowSubmit).order_by(desc(IndexNowSubmit.created_at))
    if not is_admin_role(role):
        q = q.where(IndexNowSubmit.user_id == int(user_id))
    rows = db.scalars(q.offset(max(0, offset)).limit(min(max(1, limit), 100))).all()

    projects: list[dict[str, Any]] = []
    for row in rows:
        sent_count = db.scalar(
            select(func.count(IndexNowSubmitLog.id))
            .where(IndexNowSubmitLog.submit_id == row.id)
            .where(IndexNowSubmitLog.send_status == "sent")
        ) or 0
        name = row.project_name or make_project_name(
            row.url_count,
            when=row.created_at,
        )
        projects.append({
            "id": row.id,
            "project_name": name,
            "domain": row.domain,
            "url_count": row.url_count,
            "sent_count": int(sent_count),
            "submit_status": row.submit_status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return {"ok": True, "count": len(projects), "projects": projects}


def get_submit_project(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    role: str | None,
) -> dict[str, Any] | None:
    parent = db.get(IndexNowSubmit, int(project_id))
    if not parent:
        return None
    if not is_admin_role(role) and parent.user_id != int(user_id):
        return None
    logs = db.scalars(
        select(IndexNowSubmitLog)
        .where(IndexNowSubmitLog.submit_id == parent.id)
        .order_by(IndexNowSubmitLog.id)
    ).all()
    name = parent.project_name or make_project_name(
        parent.url_count,
        when=parent.created_at,
    )
    return {
        "ok": True,
        "id": parent.id,
        "project_name": name,
        "domain": parent.domain,
        "url_count": parent.url_count,
        "submit_status": parent.submit_status,
        "created_at": parent.created_at.isoformat() if parent.created_at else None,
        "items": [_log_to_row(log) for log in logs],
    }


def refresh_submit_project_index_status(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    role: str | None,
) -> dict[str, Any] | None:
    """Kiểm tra index từng URL trong dự án submit và lưu Index/No."""
    from app.services.crawler import normalize_url
    from app.services.index_status_checker import (
        INDEX_STATUS_INDEXED,
        check_urls_index_status,
    )

    parent = db.get(IndexNowSubmit, int(project_id))
    if not parent:
        return None
    if not is_admin_role(role) and parent.user_id != int(user_id):
        return None

    logs = list(
        db.scalars(
            select(IndexNowSubmitLog)
            .where(IndexNowSubmitLog.submit_id == parent.id)
            .order_by(IndexNowSubmitLog.id)
        ).all()
    )
    if not logs:
        return get_submit_project(
            db, project_id=project_id, user_id=user_id, role=role
        )

    urls = [str(log.url or "").strip() for log in logs if str(log.url or "").strip()]
    checked = check_urls_index_status(db, user_id=user_id, urls=urls)
    by_url: dict[str, dict[str, Any]] = {}
    for row in checked:
        key = normalize_url(str(row.get("url") or "").strip())
        if key:
            by_url[key] = row

    for log in logs:
        row = by_url.get(normalize_url(str(log.url or "").strip()))
        if not row:
            continue
        index_status = str(row.get("index_status") or "")
        indexed = "Index" if index_status == INDEX_STATUS_INDEXED else "No"
        payload = _json_loads(log.payload_json)
        payload.update({
            "indexed": indexed,
            "index_status": index_status,
            "status": "indexed" if indexed == "Index" else "not_indexed",
            "message": row.get("message") or "",
            "source": row.get("source") or "",
            "checked_at": row.get("checked_at"),
            "broken": "",
        })
        log.payload_json = _json_dumps(payload)

    db.commit()
    from app.services.index_control_results_store import get_submit_result_detail

    return get_submit_result_detail(
        db, project_id=project_id, user_id=user_id, role=role
    )


def delete_submit_project(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    role: str | None,
) -> bool:
    parent = db.get(IndexNowSubmit, int(project_id))
    if not parent:
        return False
    if not is_admin_role(role) and parent.user_id != int(user_id):
        return False
    db.delete(parent)
    db.commit()
    return True


def delete_all_submit_projects(
    db: Session,
    *,
    user_id: int,
    role: str | None,
) -> int:
    q = select(IndexNowSubmit)
    if not is_admin_role(role):
        q = q.where(IndexNowSubmit.user_id == int(user_id))
    rows = db.scalars(q).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)


def export_submit_project_xlsx(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    role: str | None,
) -> bytes | None:
    project = get_submit_project(
        db, project_id=project_id, user_id=user_id, role=role
    )
    if not project:
        return None

    wb = Workbook()
    ws = wb.active
    ws.title = "Submit Project"
    headers = [
        "ID",
        "URL",
        "Index",
        "Mã phản hồi",
        "Khả năng index",
        "URL redirect",
        "Broken",
        "Trạng thái gửi",
    ]
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True)

    for item in project.get("items") or []:
        ws.append([
            item.get("id"),
            item.get("url") or "",
            item.get("indexed") or "—",
            item.get("status_code") or "—",
            item.get("indexability") or "—",
            item.get("redirect_url") or "—",
            item.get("broken") or "—",
            item.get("send_status") or "",
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
