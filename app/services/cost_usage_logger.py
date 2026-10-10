"""Infra cost usage logger — meter even when user credit charge is 0.

Writes UsageEvent with metadata:
organization_id, feature_key, quantity, estimated_cost, provider, request_id.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.usage_event import UsageEvent

_LOG = logging.getLogger(__name__)

# Soft estimated VND cost when credit_cost is 0 (infra attribution).
DEFAULT_ESTIMATED_COST_VND: dict[str, int] = {
    "crawl_job": 80,
    "email_user_notify": 120,
    "storage_put": 40,
    "storage_get": 15,
    "r2_put": 50,
    "r2_get": 20,
}


def estimate_cost_vnd(feature_key: str, *, quantity: int = 1, bytes_len: int = 0) -> int:
    base = int(DEFAULT_ESTIMATED_COST_VND.get(str(feature_key), 50))
    qty = max(1, int(quantity or 1))
    extra = 0
    if bytes_len > 0:
        # ~1 VND per KB soft infra (storage/egress)
        extra = max(1, (int(bytes_len) + 1023) // 1024)
    return max(0, base * qty + extra)


def record_infra_cost_usage(
    db: Session,
    *,
    user_id: int | None,
    organization_id: int | None,
    feature_key: str,
    quantity: int = 1,
    estimated_cost: int | None = None,
    provider: str,
    request_id: str | None = None,
    credits_used: int = 0,
    bytes_len: int = 0,
    extra: dict[str, Any] | None = None,
) -> UsageEvent | None:
    """
    Record usage/cost for infra surfaces (crawl/email/storage).
    credits_used may be 0 — estimated_cost is still required for economics.
    """
    fk = str(feature_key or "").strip()[:64]
    if not fk:
        return None
    uid = int(user_id or 0)
    if uid <= 0:
        # System/CI paths — still log under synthetic user 0 is invalid FK.
        # Skip DB row but keep structured log for ops.
        _LOG.info(
            "infra_cost_usage feature=%s org=%s qty=%s cost=%s provider=%s request_id=%s",
            fk,
            organization_id,
            quantity,
            estimated_cost,
            provider,
            request_id,
        )
        return None

    rid = str(request_id or "").strip() or f"infra:{fk}:{uuid.uuid4().hex[:16]}"
    qty = max(1, int(quantity or 1))
    cost = int(estimated_cost) if estimated_cost is not None else estimate_cost_vnd(
        fk, quantity=qty, bytes_len=bytes_len
    )
    org_id = int(organization_id) if organization_id is not None else uid
    meta: dict[str, Any] = {
        "organization_id": org_id,
        "feature_key": fk,
        "quantity": qty,
        "estimated_cost": max(0, cost),
        "provider": str(provider or "other")[:64],
        "request_id": rid[:128],
    }
    if bytes_len > 0:
        meta["bytes"] = int(bytes_len)
    if extra:
        meta.update(extra)

    try:
        from app.services.usage_tracking_service import record_successful_usage

        return record_successful_usage(
            db,
            uid,
            fk,
            quantity=qty,
            credits_used=max(0, int(credits_used or 0)),
            idempotency_key=rid[:128],
            metadata=meta,
        )
    except Exception:
        _LOG.exception(
            "record_infra_cost_usage failed user_id=%s feature=%s request_id=%s",
            uid,
            fk,
            rid,
        )
        return None
