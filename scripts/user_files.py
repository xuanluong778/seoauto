"""Authenticated access to per-user uploaded files."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.models.user import User
from app.services.auth import get_current_user
from app.services.rbac import is_admin
from app.services.user_data_paths import resolve_user_upload_file

router = APIRouter(prefix="/api/user-files", tags=["user-files"])


@router.get("/{owner_id}/{file_path:path}")
def get_user_upload(
    owner_id: int,
    file_path: str,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    if int(current_user.id) != int(owner_id) and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập file này.")
    target = resolve_user_upload_file(owner_id, file_path)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy file.")
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media)
