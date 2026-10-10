"""Public endpoints for email open/click tracking + unsubscribe."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.email_automation_marketing import EmailMarketingUnsubscribe, EmailSend, EmailSendLog


_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email"])

_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc``\x00\x00\x00\x04\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _touch_log(db: Session, *, outbox: EmailSend, status: str, detail: str | None = None) -> None:
    db.add(
        EmailSendLog(
            owner_user_id=int(outbox.owner_user_id),
            email_send_id=int(outbox.id),
            recipient_email=str(outbox.recipient_email or ""),
            status=status,
            detail=detail,
        )
    )


@router.get("/track/open", response_class=Response)
def track_open(token: str, db: Session = Depends(get_db)) -> Response:
    if not token:
        return Response(status_code=204)
    outbox = db.execute(select(EmailSend).where(EmailSend.event_token == str(token).strip())).scalar_one_or_none()
    if outbox is None:
        return Response(status_code=204)

    now = _utc_now()
    changed = False
    if outbox.opened_at is None:
        outbox.opened_at = now
        changed = True
    if outbox.status != "clicked" and outbox.status != "opened":
        outbox.status = "opened"
        changed = True
    if changed:
        _touch_log(db, outbox=outbox, status="opened", detail=None)
        db.commit()
    return Response(content=_ONE_PIXEL_PNG, media_type="image/png")


@router.get("/track/click", response_class=Response)
def track_click(token: str, request: Request, db: Session = Depends(get_db)) -> Response:
    if not token:
        return Response(status_code=204)
    outbox = db.execute(select(EmailSend).where(EmailSend.event_token == str(token).strip())).scalar_one_or_none()
    if outbox is None:
        return Response(status_code=204)

    now = _utc_now()
    changed = False
    if outbox.clicked_at is None:
        outbox.clicked_at = now
        changed = True
    if outbox.status != "clicked":
        outbox.status = "clicked"
        changed = True
    if changed:
        _touch_log(db, outbox=outbox, status="clicked", detail=None)
        db.commit()

    from app.services.email_automation_marketing_engine import build_click_target_url

    url = build_click_target_url(db, outbox)
    return RedirectResponse(url=url, status_code=302)


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)) -> HTMLResponse:
    if not token:
        return HTMLResponse("<h3>Unsubscribe không hợp lệ.</h3>", status_code=400)
    unsub = (
        db.execute(select(EmailMarketingUnsubscribe).where(EmailMarketingUnsubscribe.unsub_token == str(token).strip()))
        .scalar_one_or_none()
    )
    if unsub is None:
        return HTMLResponse("<h3>Không tìm thấy yêu cầu unsubscribe.</h3>", status_code=404)
    if unsub.unsubscribed_at is None:
        unsub.unsubscribed_at = _utc_now()
        related = (
            db.execute(select(EmailSend).where(EmailSend.unsub_token == str(token).strip()))
            .scalars()
            .all()
        )
        for row in related:
            row.status = "unsubscribed"
            _touch_log(db, outbox=row, status="unsubscribed", detail="user_unsub")
        db.commit()
    return HTMLResponse("<h3>Đã hủy nhận email marketing thành công.</h3><p>Bạn có thể tiếp tục sử dụng SEOAuto.</p>")

