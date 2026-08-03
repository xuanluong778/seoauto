"""SePay payment webhooks."""

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
    Always returns {"success": true} for authenticated, parseable requests (even when skipped).
    """
    if is_production() and not is_sepay_webhook_configured():
        from app.services.payment_config import sepay_webhook_require_auth

        if sepay_webhook_require_auth():
            logger.error(
                "sepay_webhook_rejected production=true reason=missing_config "
                "SEPAY_WEBHOOK_SECRET and/or SEPAY_API_KEY required"
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

        result = process_sepay_webhook(db, payload)
        db.commit()
        logger.info("sepay_webhook_done result=%s", result)
        return {"success": True}
    except Exception:
        db.rollback()
        logger.exception(
            "sepay_webhook_process_failed payload_keys=%s",
            list(payload.keys()) if isinstance(payload, dict) else None,
        )
        return {"success": True}
