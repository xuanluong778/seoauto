"""IndexNow — persist submit logs per user (no key stored)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.index_control import IndexNowSubmit, IndexNowSubmitLog
from app.services.submit_project_store import make_project_name
from app.services.user_scope import is_admin_role


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def save_indexnow_logs(
    db: Session,
    *,
    user_id: int,
    domain: str,
    api_http_status: int | None,
    submit_status: str,
    batch_note: str | None,
    items: list[dict[str, Any]],
    project_name: str | None = None,
) -> int:
    """Lưu batch + từng URL. Trả về submit_id."""
    pname = (project_name or make_project_name(len(items)))[:255]
    submit = IndexNowSubmit(
        user_id=int(user_id),
        domain=domain[:253],
        url_count=len(items),
        api_http_status=api_http_status,
        submit_status=(submit_status or "unknown")[:32],
        note=(batch_note or "")[:1000] or None,
        project_name=pname,
    )
    db.add(submit)
    db.flush()

    for item in items:
        payload = item.get("payload")
        payload_json = _json_dumps(payload) if isinstance(payload, dict) and payload else None
        db.add(
            IndexNowSubmitLog(
                submit_id=submit.id,
                user_id=int(user_id),
                url=str(item.get("url") or "")[:2000],
                send_status=str(item.get("send_status") or "unknown")[:32],
                http_status=int(item["http_status"]) if item.get("http_status") is not None else None,
                note=(str(item.get("note") or "")[:1000] or None),
                payload_json=payload_json,
            )
        )
    db.commit()
    db.refresh(submit)
    return int(submit.id)


def list_indexnow_logs(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    domain: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    q = (
        select(IndexNowSubmitLog)
        .join(IndexNowSubmit, IndexNowSubmitLog.submit_id == IndexNowSubmit.id)
        .order_by(desc(IndexNowSubmitLog.created_at))
    )
    if not is_admin_role(role):
        q = q.where(IndexNowSubmitLog.user_id == int(user_id))
    if domain:
        q = q.where(IndexNowSubmit.domain == domain.strip().lower())

    rows = db.scalars(q.offset(max(0, offset)).limit(min(max(1, limit), 200))).all()
    items = [
        {
            "id": r.id,
            "submit_id": r.submit_id,
            "user_id": r.user_id,
            "url": r.url,
            "send_status": r.send_status,
            "http_status": r.http_status,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "is_admin": is_admin_role(role),
    }
