"""Shared idempotency helpers (UsageEvent-backed, no billing/credit schema changes)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.usage_event import UsageEvent
from app.services.usage_tracking_service import record_successful_usage


def build_idempotency_key(scope: str, *parts: Any) -> str:
    """Build a stable idempotency key capped at 128 chars."""
    raw = f"{scope}:{':'.join(str(p) for p in parts if p is not None and str(p) != '')}"
    return raw.strip()[:128]


def job_fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash for duplicate job detection (same user + same inputs)."""
    key_data = {
        "keywords": sorted(str(k) for k in (payload.get("keywords") or [])),
        "target_website": str(payload.get("target_website") or "").strip(),
        "items_count": len(payload.get("items") or []),
    }
    blob = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def technical_analyze_fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash for technical scan inputs (retry-safe idempotency)."""
    key_data = {
        "url": str(payload.get("url") or "").strip().lower().rstrip("/"),
        "max_pages": int(payload.get("max_pages") or 25),
        "use_gsc": bool(payload.get("use_gsc")),
        "gsc_property": str(payload.get("gsc_property") or "").strip().lower(),
        "gsc_date_range": str(payload.get("gsc_date_range") or "28d"),
        "gsc_start_date": str(payload.get("gsc_start_date") or ""),
        "gsc_end_date": str(payload.get("gsc_end_date") or ""),
        "url_inspection_limit": int(payload.get("url_inspection_limit") or 10),
    }
    blob = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def url_seo_scoreboard_fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash for SEO Score URL inputs (retry-safe idempotency)."""
    sec = payload.get("secondary_keywords")
    if isinstance(sec, list):
        sec_norm = sorted(str(x).strip().lower() for x in sec if str(x).strip())
    else:
        sec_norm = sorted(
            x.strip().lower()
            for x in str(sec or "").replace(";", ",").split(",")
            if x.strip()
        )
    key_data = {
        "url": str(payload.get("url") or "").strip().lower().rstrip("/"),
        "keyword": str(payload.get("keyword") or "").strip().lower(),
        "secondary_keywords": sec_norm,
        "page_type": str(payload.get("page_type") or "").strip().lower(),
        "search_volume": int(payload.get("search_volume") or 0),
        "current_serp_position": int(payload.get("current_serp_position") or 0),
    }
    blob = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def find_usage_by_key(db: Session, idempotency_key: str) -> UsageEvent | None:
    key = str(idempotency_key or "").strip()[:128]
    if not key:
        return None
    return db.query(UsageEvent).filter(UsageEvent.idempotency_key == key).one_or_none()


def record_usage_idempotent(
    db: Session,
    user_id: int,
    feature_key: str,
    *,
    quantity: int = 1,
    credits_used: int = 0,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    """Record usage once per idempotency_key (delegates to usage_tracking_service)."""
    return record_successful_usage(
        db,
        int(user_id),
        feature_key,
        quantity=quantity,
        credits_used=credits_used,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )
