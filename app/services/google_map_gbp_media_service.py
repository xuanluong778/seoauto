"""Google Map SEO — quản lý ảnh & media GBP."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets_crypto import decrypt_secret
from app.models.google_map_gbp import GbpLocation, GbpMedia, GbpMediaReminder, GbpOAuthConnection
from app.services.google_map_gbp_media_ai import (
    MEDIA_TYPE_LABELS,
    MEDIA_TYPES,
    generate_media_caption,
    suggest_seo_filename,
)
from app.services.google_map_gbp_media_api import upload_location_media
from app.services.google_map_gbp_api import credentials_from_tokens
from app.services.google_map_gbp_profile_service import _resolve_location

_LOG = logging.getLogger("google_map_gbp.media")

ALLOWED_SUFFIX = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_BYTES = 10 * 1024 * 1024
MIN_SHORT_EDGE = 720
MIN_LOGO = 250

CRITICAL_TYPES = frozenset({"logo", "cover"})
IMPORTANT_TYPES = frozenset({"storefront", "interior", "product_service"})
RECOMMENDED_TYPES = frozenset({"team", "customer_case"})

WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _upload_root() -> Path:
    root = Path("static") / "uploads" / "gbp-media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def media_to_dict(row: GbpMedia) -> dict[str, Any]:
    validation = _load_json(row.validation_json)
    return {
        "id": row.id,
        "location_key": row.location_key,
        "media_type": row.media_type,
        "media_type_label": MEDIA_TYPE_LABELS.get(row.media_type, row.media_type),
        "status": row.status,
        "file_name": row.file_name,
        "public_url": row.public_url,
        "mime_type": row.mime_type,
        "file_size_bytes": row.file_size_bytes,
        "width_px": row.width_px,
        "height_px": row.height_px,
        "suggested_filename": row.suggested_filename,
        "caption": row.caption,
        "validation": validation,
        "google_media_name": row.google_media_name,
        "last_error": row.last_error,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _validate_image_bytes(data: bytes, *, media_type: str, suffix: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings: list[str] = []
    ok = True
    size = len(data)
    if size > MAX_BYTES:
        ok = False
        issues.append({
            "code": "file_too_large",
            "severity": "error",
            "message": f"Dung lượng {size // 1024}KB vượt giới hạn {MAX_BYTES // 1024 // 1024}MB.",
        })
    width = height = 0
    try:
        img = Image.open(__import__("io").BytesIO(data))
        width, height = img.size
    except Exception:
        ok = False
        issues.append({"code": "invalid_image", "severity": "error", "message": "Không đọc được file ảnh."})
        return {"ok": ok, "width": width, "height": height, "size": size, "issues": issues, "warnings": warnings}

    short_edge = min(width, height)
    if short_edge < MIN_SHORT_EDGE:
        ok = False
        issues.append({
            "code": "resolution_low",
            "severity": "error",
            "message": f"Cạnh ngắn {short_edge}px — tối thiểu {MIN_SHORT_EDGE}px.",
        })
    mtype = str(media_type or "").lower()
    if mtype == "logo" and (width < MIN_LOGO or height < MIN_LOGO):
        warnings.append(f"Logo nên ≥{MIN_LOGO}×{MIN_LOGO}px.")
    if mtype == "cover":
        ratio = width / height if height else 0
        if ratio < 1.5 or ratio > 2.0:
            warnings.append("Ảnh bìa khuyến nghị tỷ lệ ~16:9 (1080×608).")
    if suffix not in ALLOWED_SUFFIX:
        ok = False
        issues.append({"code": "bad_format", "severity": "error", "message": "Chỉ hỗ trợ JPG, PNG, WebP."})

    return {"ok": ok, "width": width, "height": height, "size": size, "issues": issues, "warnings": warnings}


def _types_present(rows: list[GbpMedia]) -> dict[str, bool]:
    present = {t: False for t in MEDIA_TYPES}
    for row in rows:
        if row.media_type in present:
            present[row.media_type] = True
    return present


def _audit_issues(types_present: dict[str, bool]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for mtype in CRITICAL_TYPES:
        if not types_present.get(mtype):
            label = MEDIA_TYPE_LABELS[mtype]
            issues.append({
                "id": f"media_missing_{mtype}",
                "severity": "critical",
                "groupId": "media",
                "title": f"Thiếu {label.lower()}",
                "cause": f"Chưa upload {label.lower()} cho hồ sơ Map.",
                "fix": f"Upload {label.lower()} chất lượng cao trong tab Ảnh & Media.",
                "aiFixable": False,
                "media_type": mtype,
            })
    for mtype in IMPORTANT_TYPES:
        if not types_present.get(mtype):
            label = MEDIA_TYPE_LABELS[mtype]
            issues.append({
                "id": f"media_missing_{mtype}",
                "severity": "warning",
                "groupId": "media",
                "title": f"Thiếu {label.lower()}",
                "cause": f"Chưa có {label.lower()} — ảnh thực tế tăng trust Local Pack.",
                "fix": f"Bổ sung ít nhất 1 {label.lower()}.",
                "aiFixable": False,
                "media_type": mtype,
            })
    for mtype in RECOMMENDED_TYPES:
        if not types_present.get(mtype):
            label = MEDIA_TYPE_LABELS[mtype]
            issues.append({
                "id": f"media_missing_{mtype}",
                "severity": "opportunity",
                "groupId": "media",
                "title": f"Nên thêm {label.lower()}",
                "cause": f"Chưa có {label.lower()} trên thư viện nội bộ.",
                "fix": f"Upload {label.lower()} để làm phong phú hồ sơ.",
                "aiFixable": False,
                "media_type": mtype,
            })
    return issues


def _can_publish_gbp(db: Session, gbp_row: GbpLocation | None) -> bool:
    if gbp_row is None:
        return False
    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    return bool(conn and conn.status == "active")


def _next_remind_at(weekday: int, from_dt: datetime | None = None) -> datetime:
    base = from_dt or _now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    wd = max(0, min(6, int(weekday)))
    days_ahead = (wd - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    nxt = base.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    return nxt.astimezone(timezone.utc)


def list_media(db: Session, user_id: int, *, location_key: str) -> dict[str, Any]:
    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    rows = db.execute(
        select(GbpMedia).where(
            GbpMedia.user_id == user_id,
            GbpMedia.location_key == location_key,
        ).order_by(GbpMedia.media_type.asc(), GbpMedia.updated_at.desc())
    ).scalars().all()
    types_present = _types_present(rows)
    by_type: dict[str, list[dict[str, Any]]] = {t: [] for t in MEDIA_TYPES}
    for row in rows:
        if row.media_type in by_type:
            by_type[row.media_type].append(media_to_dict(row))
    return {
        "location_key": location_key,
        "can_publish": _can_publish_gbp(db, gbp_row),
        "business": loc_ui,
        "items": [media_to_dict(r) for r in rows],
        "by_type": by_type,
        "types_present": types_present,
        "summary": {
            "total": len(rows),
            "types_covered": sum(1 for v in types_present.values() if v),
            "types_total": len(MEDIA_TYPES),
        },
    }


def audit_media(db: Session, user_id: int, *, location_key: str) -> dict[str, Any]:
    data = list_media(db, user_id, location_key=location_key)
    issues = _audit_issues(data["types_present"])
    return {
        "location_key": location_key,
        "types_present": data["types_present"],
        "optimization_issues": issues,
        "summary": {
            "critical": sum(1 for i in issues if i["severity"] == "critical"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
            "opportunity": sum(1 for i in issues if i["severity"] == "opportunity"),
        },
    }


async def upload_media(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    media_type: str,
    file: UploadFile,
    keywords: str = "",
    locality: str = "",
) -> dict[str, Any]:
    mtype = str(media_type or "").strip().lower()
    if mtype not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="media_type không hợp lệ.")

    filename = file.filename or "image.jpg"
    suffix = Path(filename).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ JPG, PNG, WebP.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File rỗng.")

    validation = _validate_image_bytes(data, media_type=mtype, suffix=suffix)
    if not validation["ok"]:
        msg = validation["issues"][0]["message"] if validation["issues"] else "Ảnh không hợp lệ."
        raise HTTPException(status_code=400, detail=msg)

    from app.services.media_storage import private_upload_url
    from app.services.user_data_paths import user_gbp_media_dir, user_gbp_media_relative_path

    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-").lower() or "image"
    target_name = f"{safe_stem}-{uuid4().hex[:8]}{suffix}"
    dest_dir = user_gbp_media_dir(user_id, location_key)
    dest_path = dest_dir / target_name
    dest_path.write_bytes(data)

    rel_path = user_gbp_media_relative_path(location_key, target_name)
    public_url = private_upload_url(user_id, rel_path)
    suggested = suggest_seo_filename(
        media_type=mtype,
        keywords=keywords or loc_ui.get("category") or "",
        locality=locality or loc_ui.get("address") or "",
        ext=suffix,
    )

    row = GbpMedia(
        user_id=user_id,
        location_key=location_key,
        gbp_location_id=gbp_row.id if gbp_row else None,
        media_type=mtype,
        status="local",
        file_name=target_name,
        file_path=str(dest_path),
        public_url=public_url,
        mime_type=file.content_type or f"image/{suffix.lstrip('.')}",
        file_size_bytes=validation["size"],
        width_px=validation["width"],
        height_px=validation["height"],
        suggested_filename=suggested,
        validation_json=json.dumps(validation, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = media_to_dict(row)
    out["validation_warnings"] = validation.get("warnings") or []
    return out


def update_media(
    db: Session,
    user_id: int,
    media_id: int,
    *,
    caption: str | None = None,
    suggested_filename: str | None = None,
) -> dict[str, Any]:
    row = db.get(GbpMedia, media_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    if caption is not None:
        row.caption = str(caption).strip()[:2000]
    if suggested_filename is not None:
        row.suggested_filename = str(suggested_filename).strip()[:255]
    db.commit()
    db.refresh(row)
    return media_to_dict(row)


def delete_media(db: Session, user_id: int, media_id: int) -> dict[str, Any]:
    row = db.get(GbpMedia, media_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    try:
        Path(row.file_path).unlink(missing_ok=True)
    except OSError:
        _LOG.warning("Could not delete file %s", row.file_path)
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": media_id}


def ai_caption(
    db: Session,
    user_id: int,
    media_id: int,
    *,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = db.get(GbpMedia, media_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")
    _, loc_ui = _resolve_location(db, user_id, row.location_key)
    inp = dict(input_data or {})
    if not inp.get("keywords"):
        inp["keywords"] = loc_ui.get("category") or ""
    if not inp.get("locality"):
        inp["locality"] = loc_ui.get("address") or ""
    inp["ext"] = Path(row.file_name).suffix or ".jpg"
    try:
        result = generate_media_caption(
            user_id=user_id,
            media_type=row.media_type,
            inp=inp,
            business=loc_ui,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row.caption = result["caption"]
    row.suggested_filename = result.get("suggested_filename") or row.suggested_filename
    db.commit()
    db.refresh(row)
    return {**result, "media": media_to_dict(row)}


def publish_media(db: Session, user_id: int, media_id: int) -> dict[str, Any]:
    row = db.get(GbpMedia, media_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh.")

    gbp_row, _ = _resolve_location(db, user_id, row.location_key)
    if gbp_row is None or not _can_publish_gbp(db, gbp_row):
        row.last_error = "Chưa kết nối GBP — ảnh lưu nội bộ, chưa đăng Google."
        db.commit()
        db.refresh(row)
        return {**media_to_dict(row), "published": False, "message": row.last_error}

    conn = db.get(GbpOAuthConnection, gbp_row.connection_id)
    refresh = decrypt_secret(str(conn.refresh_token_encrypted or "")).strip()
    access = decrypt_secret(str(conn.access_token_encrypted or "")).strip() or None
    creds = credentials_from_tokens(
        refresh_token=refresh,
        access_token=access,
        token_expiry=conn.token_expires_at,
    )
    if not creds:
        row.status = "error"
        row.last_error = "Token GBP không hợp lệ."
        db.commit()
        raise HTTPException(status_code=400, detail=row.last_error)

    # GBP cần URL public — chỉ thử khi có domain thật
    source_url = row.public_url
    if source_url.startswith("/"):
        row.status = "error"
        row.last_error = "Ảnh chưa có URL public — lưu nội bộ, đăng thủ công trên Google."
        db.commit()
        db.refresh(row)
        return {**media_to_dict(row), "published": False, "message": row.last_error}

    try:
        result = upload_location_media(
            creds,
            account_resource=gbp_row.google_account_resource,
            location_resource=gbp_row.google_location_resource,
            source_url=source_url,
            description=row.caption or "",
        )
        row.status = "published"
        row.google_media_name = result.get("name") or None
        row.last_error = None
    except Exception as exc:
        _LOG.exception("GBP media publish failed id=%s", media_id)
        row.status = "error"
        row.last_error = str(exc)[:500]
        db.commit()
        db.refresh(row)
        raise HTTPException(
            status_code=502,
            detail=f"Không đăng được lên Google — ảnh vẫn lưu nội bộ. {exc}",
        ) from exc

    db.commit()
    db.refresh(row)
    return {**media_to_dict(row), "published": True, "message": "Đã đăng ảnh lên Google Business Profile."}


def get_reminder(db: Session, user_id: int, *, location_key: str) -> dict[str, Any]:
    row = db.execute(
        select(GbpMediaReminder).where(
            GbpMediaReminder.user_id == user_id,
            GbpMediaReminder.location_key == location_key,
        )
    ).scalar_one_or_none()
    if row is None:
        return {
            "enabled": False,
            "remind_weekday": 1,
            "remind_weekday_label": WEEKDAY_LABELS[1],
            "next_remind_at": _iso(_next_remind_at(1)),
        }
    nxt = _next_remind_at(row.remind_weekday, row.last_reminded_at or _now())
    return {
        "enabled": bool(row.enabled),
        "remind_weekday": row.remind_weekday,
        "remind_weekday_label": WEEKDAY_LABELS[row.remind_weekday % 7],
        "last_reminded_at": _iso(row.last_reminded_at),
        "next_remind_at": _iso(nxt),
    }


def save_reminder(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    enabled: bool,
    remind_weekday: int,
) -> dict[str, Any]:
    wd = max(0, min(6, int(remind_weekday)))
    row = db.execute(
        select(GbpMediaReminder).where(
            GbpMediaReminder.user_id == user_id,
            GbpMediaReminder.location_key == location_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = GbpMediaReminder(
            user_id=user_id,
            location_key=location_key,
            enabled=enabled,
            remind_weekday=wd,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.remind_weekday = wd
    db.commit()
    db.refresh(row)
    return get_reminder(db, user_id, location_key=location_key)
