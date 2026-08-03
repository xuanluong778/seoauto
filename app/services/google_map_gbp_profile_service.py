"""Google Map SEO — nháp & áp dụng nội dung hồ sơ GBP."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret
from app.models.google_map_gbp import GbpLocation, GbpOAuthConnection, GbpProfileDraft
from app.services.google_map_gbp_api import credentials_from_tokens, patch_location_description
from app.services.google_map_gbp_profile_ai import CONTENT_TYPES, generate_profile_content

_LOG = logging.getLogger("google_map_gbp.profile")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _resolve_location(db: Session, user_id: int, location_key: str) -> tuple[GbpLocation | None, dict[str, Any]]:
    loc_ui: dict[str, Any] = {}
    row: GbpLocation | None = None
    if location_key.startswith("gbp_"):
        try:
            db_id = int(location_key.replace("gbp_", "", 1))
        except ValueError:
            db_id = 0
        if db_id:
            row = db.execute(
                select(GbpLocation).where(
                    GbpLocation.id == db_id,
                    GbpLocation.user_id == user_id,
                    GbpLocation.is_active.is_(True),
                )
            ).scalar_one_or_none()
    if row:
        loc_ui = {
            "name": row.title or "",
            "category": row.primary_category or "",
            "address": ", ".join(p for p in (row.address_line, row.locality) if p),
            "website": row.website_uri or "",
            "google_location_resource": row.google_location_resource,
            "db_id": row.id,
        }
    return row, loc_ui


def draft_to_dict(row: GbpProfileDraft) -> dict[str, Any]:
    inp = None
    if row.input_json:
        try:
            inp = json.loads(row.input_json)
        except json.JSONDecodeError:
            inp = None
    return {
        "id": row.id,
        "location_key": row.location_key,
        "content_type": row.content_type,
        "input": inp,
        "output_text": row.output_text,
        "updated_at": _iso(row.updated_at),
    }


def list_drafts(db: Session, user_id: int, *, location_key: str) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GbpProfileDraft)
        .where(GbpProfileDraft.user_id == user_id, GbpProfileDraft.location_key == location_key)
        .order_by(GbpProfileDraft.updated_at.desc())
    ).scalars().all()
    return [draft_to_dict(r) for r in rows]


def save_draft(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    content_type: str,
    input_data: dict[str, Any],
    output_text: str,
) -> dict[str, Any]:
    ctype = str(content_type or "").strip().lower()
    if ctype not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="content_type không hợp lệ.")

    gbp_row, _ = _resolve_location(db, user_id, location_key)
    row = db.execute(
        select(GbpProfileDraft).where(
            GbpProfileDraft.user_id == user_id,
            GbpProfileDraft.location_key == location_key,
            GbpProfileDraft.content_type == ctype,
        )
    ).scalar_one_or_none()

    payload = json.dumps(input_data, ensure_ascii=False)
    if row is None:
        row = GbpProfileDraft(
            user_id=user_id,
            location_key=location_key,
            gbp_location_id=gbp_row.id if gbp_row else None,
            content_type=ctype,
            input_json=payload,
            output_text=output_text,
        )
        db.add(row)
    else:
        row.input_json = payload
        row.output_text = output_text
        row.gbp_location_id = gbp_row.id if gbp_row else row.gbp_location_id
    db.commit()
    db.refresh(row)
    return draft_to_dict(row)


def ai_generate(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    content_type: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    _, from_gbp = _resolve_location(db, user_id, location_key)
    try:
        result = generate_profile_content(
            content_type=content_type,
            inp=input_data,
            user_id=user_id,
            from_gbp=from_gbp or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


def apply_to_gbp(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    content_type: str,
    content: str,
) -> dict[str, Any]:
    ctype = str(content_type or "").strip().lower()
    if ctype not in {"business_description", "local_intro"}:
        raise HTTPException(
            status_code=400,
            detail="Chỉ hỗ trợ áp dụng trực tiếp mô tả doanh nghiệp / giới thiệu địa phương lên GBP.",
        )

    gbp_row, _ = _resolve_location(db, user_id, location_key)
    if gbp_row is None:
        raise HTTPException(
            status_code=400,
            detail="Chưa kết nối địa điểm GBP thật — lưu nháp và dán thủ công vào Google Business.",
        )

    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    if not conn or conn.status != "active":
        raise HTTPException(status_code=400, detail="Kết nối Google Business Profile không còn hiệu lực.")

    refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
    access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
    creds = credentials_from_tokens(
        refresh_token=refresh,
        access_token=access,
        token_expiry=conn.token_expires_at,
    )
    if not creds:
        raise HTTPException(status_code=400, detail="Không đọc được token GBP — hãy kết nối lại.")

    try:
        patch_location_description(creds, gbp_row.google_location_resource, content)
    except Exception as exc:
        _LOG.exception("GBP apply description failed loc=%s", gbp_row.id)
        raise HTTPException(status_code=502, detail=f"Không cập nhật được lên Google: {exc}") from exc

    gbp_row.last_synced_at = _now()
    db.commit()
    return {
        "applied": True,
        "content_type": ctype,
        "location_key": location_key,
        "message": "Đã cập nhật mô tả lên Google Business Profile.",
    }
