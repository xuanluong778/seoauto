"""SePay payment webhooks — auth, store event, process once, always success after auth."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.runtime import is_production
from app.db import get_db
from app.services.payment_config import is_sepay_webhook_configured, verify_sepay_webhook_auth
from app.services.sepay_webhook_service import process_sepay_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/sepay/webhook")
@router.head("/sepay/webhook")
async def sepay_webhook_health():
    """SePay / monitor probes — endpoint must exist and return success."""
    return {"success": True}


@router.post("/sepay/webhook")
async def sepay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_sepay_secret: str | None = Header(default=None, alias="X-SePay-Secret"),
    x_sepay_signature: str | None = Header(default=None, alias="X-SePay-Signature"),
    x_sepay_timestamp: str | None = Header(default=None, alias="X-SePay-Timestamp"),
):
    """
    SePay bank-transfer webhook.

    Flow: verify auth → process (stores raw event first, idempotent) → commit.
    Authenticated requests always return {"success": true} so provider does not hammer retries
    on business skips; already-processed events return success without re-applying plan/credit.
    """
    from app.services.payment_config import sepay_webhook_require_auth

    # Fail-closed: missing secrets while auth is required (always in production; default elsewhere).
    if not is_sepay_webhook_configured() and sepay_webhook_require_auth():
        logger.error(
            "sepay_webhook_rejected reason=missing_config production=%s "
            "SEPAY_WEBHOOK_SECRET and/or SEPAY_API_KEY required",
            is_production(),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "payment_not_configured",
                "message": "SePay webhook is not configured on this server.",
            },
        )

    try:
        body = await request.body()
    except Exception:
        logger.exception("sepay_webhook_read_body_failed")
        body = b""

    payload: dict | None = None
    try:
        if body:
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
    except json.JSONDecodeError:
        pass

    if not verify_sepay_webhook_auth(
        authorization=authorization,
        x_api_key=x_api_key,
        x_sepay_secret=x_sepay_secret,
        raw_body=body,
        x_sepay_signature=x_sepay_signature,
        x_sepay_timestamp=x_sepay_timestamp,
        payload=payload,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Webhook authentication failed."},
        )

    try:
        if not body:
            logger.warning("sepay_webhook_empty_body")
            return {"success": True}
        if payload is None:
            logger.warning("sepay_webhook_invalid_json")
            return {"success": True}

        # Durable raw log *before* business application (survives process crash/rollback)
        from app.services.sepay_webhook_service import store_raw_webhook_event

        store_raw_webhook_event(db, payload, raw_body=body)
        db.commit()

        result = process_sepay_webhook(db, payload, raw_body=body)
        db.commit()
        logger.info("sepay_webhook_done result=%s", {k: result.get(k) for k in ("reason", "handled", "order_code", "replay", "event_id")})
        return {"success": True}
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception(
            "sepay_webhook_process_failed payload_keys=%s",
            list(payload.keys()) if isinstance(payload, dict) else None,
        )
        # Still 200 so SePay does not infinite-retry on our bugs; FAILED is logged if event was stored.
        return {"success": True}
