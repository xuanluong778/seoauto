"""Google Map SEO — trợ lý xác minh Google Map."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.google_map_gbp import GbpLocation, GbpVerificationAsset, GbpVerificationKit
from app.services.google_map_gbp_profile_service import _resolve_location

_LOG = logging.getLogger("google_map_gbp.verification")

STATUSES = frozenset({
    "verified",
    "unverified",
    "needs_reverify",
    "pending",
    "rejected",
})

STATUS_LABELS = {
    "verified": "Đã xác minh",
    "unverified": "Chưa xác minh",
    "needs_reverify": "Cần xác minh lại",
    "pending": "Đang chờ Google duyệt",
    "rejected": "Bị từ chối",
}

CHECKLIST_ITEMS = (
    {"id": "business_sign", "label": "Bảng hiệu doanh nghiệp", "hint": "Tên thương hiệu khớp với hồ sơ Google"},
    {"id": "storefront", "label": "Mặt tiền / cửa hàng", "hint": "Ảnh hoặc video thấy rõ địa chỉ/ cửa vào"},
    {"id": "workspace", "label": "Khu vực làm việc", "hint": "Quầy lễ tân, phòng làm việc, không gian dịch vụ"},
    {"id": "products_services", "label": "Công cụ / sản phẩm / dịch vụ thật", "hint": "Thiết bị, sản phẩm hoặc quy trình thực tế"},
    {"id": "business_documents", "label": "Giấy tờ doanh nghiệp (nếu có)", "hint": "GPKD, hóa đơn địa chỉ, hợp đồng thuê — tùy phương thức Google yêu cầu"},
)

METHOD_GUIDES = (
    {
        "id": "postcard",
        "label": "Thư bưu điện",
        "available_hint": "Google thường gửi thư có mã PIN tới địa chỉ hồ sơ",
        "steps": [
            "Mở Google Business Profile → Xác minh địa điểm.",
            "Chọn nhận mã PIN qua thư bưu điện.",
            "Chuẩn bị có người nhận thư tại địa chỉ đã khai (5–14 ngày).",
            "Nhập mã PIN trong vòng thời hạn Google quy định.",
        ],
        "always": True,
    },
    {
        "id": "phone",
        "label": "Điện thoại / SMS",
        "available_hint": "Cần số điện thoại trên hồ sơ và Google cho phép phương thức này",
        "steps": [
            "Chọn xác minh qua cuộc gọi hoặc SMS.",
            "Trực máy số điện thoại đã đăng ký trên GBP.",
            "Nhập mã PIN ngay khi nhận được.",
        ],
        "requires_phone": True,
    },
    {
        "id": "email",
        "label": "Email domain",
        "available_hint": "Cần website/email @tên miền khớp doanh nghiệp",
        "steps": [
            "Chọn xác minh qua email (nếu Google hiển thị).",
            "Truy cập hộp thư @tênmiền doanh nghiệp.",
            "Bấm link hoặc nhập mã trong email từ Google.",
        ],
        "requires_website": True,
    },
    {
        "id": "video",
        "label": "Video xác minh",
        "available_hint": "Google có thể yêu cầu quay video tại địa điểm",
        "steps": [
            "Quay video ngắn (thường dưới 2 phút) tại địa điểm thật.",
            "Hiển thị bảng hiệu, mặt tiền hoặc không gian làm việc.",
            "Đọc rõ tên doanh nghiệp và địa chỉ nếu Google yêu cầu.",
            "Tải video theo hướng dẫn trong GBP — Google tự duyệt.",
        ],
        "always": True,
    },
)

PHOTO_SUFFIX = frozenset({".jpg", ".jpeg", ".png", ".webp"})
DOC_SUFFIX = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".webp"})
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_DOC_BYTES = 15 * 1024 * 1024


def _upload_root() -> Path:
    root = Path("static") / "uploads" / "gbp-verification"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_json(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _default_checklist() -> dict[str, bool]:
    return {item["id"]: False for item in CHECKLIST_ITEMS}


def _map_gbp_status(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if s in ("verified", "true", "1"):
        return "verified"
    if s in ("pending", "waiting", "in_review", "under_review"):
        return "pending"
    if s in ("needs_reverification", "needs_reverify", "suspended", "reverify"):
        return "needs_reverify"
    if s in ("rejected", "denied", "failed"):
        return "rejected"
    if s in ("unverified", "not_verified", "false", "0", "unknown", ""):
        return "unverified"
    return "unverified"


def _resolve_status(
    gbp_row: GbpLocation | None,
    kit: GbpVerificationKit | None,
    *,
    demo_status: str | None = None,
) -> dict[str, Any]:
    source = "manual"
    status = "unverified"
    if gbp_row and gbp_row.verification_status:
        status = _map_gbp_status(gbp_row.verification_status)
        source = "google_business_profile"
    elif demo_status:
        status = _map_gbp_status(demo_status)
        source = "demo"
    if kit and kit.manual_status and kit.manual_status in STATUSES:
        if source != "google_business_profile" or status == "unverified":
            status = kit.manual_status
            source = "manual"
    return {
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "source": source,
    }


def _method_availability(loc_ui: dict[str, Any]) -> list[dict[str, Any]]:
    has_phone = bool(str(loc_ui.get("phone") or "").strip())
    has_website = bool(str(loc_ui.get("website") or "").strip())
    out: list[dict[str, Any]] = []
    for m in METHOD_GUIDES:
        available = bool(m.get("always"))
        reason = ""
        if m.get("requires_phone"):
            available = has_phone
            reason = "Có số điện thoại trên hồ sơ" if available else "Chưa có SĐT trên hồ sơ — bổ sung trước khi thử"
        elif m.get("requires_website"):
            available = has_website
            reason = "Có website/domain" if available else "Chưa có website — email domain có thể không khả dụng"
        else:
            reason = str(m.get("available_hint") or "")
        out.append({
            "id": m["id"],
            "label": m["label"],
            "available": available,
            "available_hint": reason,
            "steps": list(m["steps"]),
        })
    return out


def asset_to_dict(row: GbpVerificationAsset) -> dict[str, Any]:
    return {
        "id": row.id,
        "asset_type": row.asset_type,
        "label": row.label or "",
        "file_name": row.file_name,
        "public_url": row.public_url,
        "mime_type": row.mime_type,
        "file_size_bytes": row.file_size_bytes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _get_or_create_kit(
    db: Session,
    user_id: int,
    location_key: str,
    gbp_row: GbpLocation | None,
) -> GbpVerificationKit:
    row = db.execute(
        select(GbpVerificationKit).where(
            GbpVerificationKit.user_id == user_id,
            GbpVerificationKit.location_key == location_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = GbpVerificationKit(
            user_id=user_id,
            location_key=location_key,
            gbp_location_id=gbp_row.id if gbp_row else None,
            checklist_json=json.dumps(_default_checklist(), ensure_ascii=False),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_verification(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    demo_status: str | None = None,
) -> dict[str, Any]:
    gbp_row, loc_ui = _resolve_location(db, user_id, location_key)
    if gbp_row:
        loc_ui = {
            **loc_ui,
            "phone": gbp_row.phone or "",
            "website": gbp_row.website_uri or loc_ui.get("website") or "",
            "verification_status": gbp_row.verification_status,
        }
    kit = _get_or_create_kit(db, user_id, location_key, gbp_row)
    checklist = _load_json(kit.checklist_json, _default_checklist())
    if not isinstance(checklist, dict):
        checklist = _default_checklist()
    for item in CHECKLIST_ITEMS:
        checklist.setdefault(item["id"], False)

    assets = db.execute(
        select(GbpVerificationAsset).where(
            GbpVerificationAsset.user_id == user_id,
            GbpVerificationAsset.location_key == location_key,
        ).order_by(GbpVerificationAsset.created_at.desc())
    ).scalars().all()

    status_info = _resolve_status(gbp_row, kit, demo_status=demo_status)
    checked = sum(1 for item in CHECKLIST_ITEMS if checklist.get(item["id"]))
    return {
        "location_key": location_key,
        "business": loc_ui,
        "status": status_info["status"],
        "status_label": status_info["status_label"],
        "status_source": status_info["source"],
        "disclaimer": (
            "Google là bên duyệt cuối cùng. SEOAuto chỉ hỗ trợ chuẩn bị hồ sơ — "
            "không cam kết xác minh 100% tự động."
        ),
        "checklist_template": list(CHECKLIST_ITEMS),
        "checklist": checklist,
        "checklist_progress": {"checked": checked, "total": len(CHECKLIST_ITEMS)},
        "notes": kit.notes or "",
        "manual_status": kit.manual_status,
        "methods": _method_availability(loc_ui),
        "assets": [asset_to_dict(a) for a in assets],
        "updated_at": kit.updated_at.isoformat() if kit.updated_at else None,
    }


def save_verification(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    checklist: dict[str, bool] | None = None,
    notes: str | None = None,
    manual_status: str | None = None,
) -> dict[str, Any]:
    gbp_row, _ = _resolve_location(db, user_id, location_key)
    kit = _get_or_create_kit(db, user_id, location_key, gbp_row)
    if checklist is not None:
        merged = _default_checklist()
        for k, v in checklist.items():
            if k in merged:
                merged[k] = bool(v)
        kit.checklist_json = json.dumps(merged, ensure_ascii=False)
    if notes is not None:
        kit.notes = str(notes).strip()[:8000]
    if manual_status is not None:
        ms = str(manual_status).strip().lower()
        if ms and ms not in STATUSES:
            raise HTTPException(status_code=400, detail="manual_status không hợp lệ.")
        kit.manual_status = ms or None
    db.commit()
    db.refresh(kit)
    return get_verification(db, user_id, location_key=location_key)


async def upload_asset(
    db: Session,
    user_id: int,
    *,
    location_key: str,
    asset_type: str,
    file: UploadFile,
    label: str = "",
) -> dict[str, Any]:
    atype = str(asset_type or "photo").strip().lower()
    if atype not in {"photo", "document"}:
        raise HTTPException(status_code=400, detail="asset_type phải là photo hoặc document.")

    filename = file.filename or "file"
    suffix = Path(filename).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    allowed = PHOTO_SUFFIX if atype == "photo" else DOC_SUFFIX
    max_bytes = MAX_PHOTO_BYTES if atype == "photo" else MAX_DOC_BYTES
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Định dạng file không được hỗ trợ.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="File rỗng.")
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File vượt quá {max_bytes // 1024 // 1024}MB.")

    gbp_row, _ = _resolve_location(db, user_id, location_key)
    kit = _get_or_create_kit(db, user_id, location_key, gbp_row)
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-").lower() or "file"
    target_name = f"{safe_stem}-{uuid4().hex[:8]}{suffix}"
    rel_dir = Path(str(user_id)) / re.sub(r"[^a-zA-Z0-9_-]+", "_", location_key)[:48]
    dest_dir = _upload_root() / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / target_name
    dest_path.write_bytes(data)

    public_url = f"/static/uploads/gbp-verification/{rel_dir.as_posix()}/{target_name}"
    row = GbpVerificationAsset(
        user_id=user_id,
        location_key=location_key,
        kit_id=kit.id,
        asset_type=atype,
        label=str(label or "").strip()[:200] or None,
        file_name=target_name,
        file_path=str(dest_path),
        public_url=public_url,
        mime_type=file.content_type,
        file_size_bytes=len(data),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return asset_to_dict(row)


def delete_asset(db: Session, user_id: int, asset_id: int) -> dict[str, Any]:
    row = db.get(GbpVerificationAsset, asset_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")
    try:
        Path(row.file_path).unlink(missing_ok=True)
    except OSError:
        _LOG.warning("Could not delete verification asset %s", row.file_path)
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": asset_id}
