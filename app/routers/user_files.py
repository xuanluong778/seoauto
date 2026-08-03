"""Authenticated access to per-user uploaded files."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import user_from_token
from app.services.rbac import is_admin
from app.services.user_data_paths import resolve_user_upload_file

router = APIRouter(prefix="/api/user-files", tags=["user-files"])


def _auth_token_from_request(request: Request, token: str | None) -> str | None:
    auth_token = (token or "").strip()
    if auth_token:
        return auth_token
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()
        if bearer:
            return bearer
    cookie = (request.cookies.get("seo_token") or "").strip()
    return cookie or None


def _resolve_file_user(
    request: Request,
    *,
    token: str | None,
    db: Session,
) -> User:
    auth_token = _auth_token_from_request(request, token)
    if not auth_token:
        raise HTTPException(status_code=401, detail="Đăng nhập để xem ảnh.")
    return user_from_token(db, auth_token)


@router.get("/{owner_id}/{file_path:path}")
def get_user_upload(
    owner_id: int,
    file_path: str,
    request: Request,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> FileResponse:
    current_user = _resolve_file_user(request, token=token, db=db)
    if int(current_user.id) != int(owner_id) and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập file này.")
    target = resolve_user_upload_file(owner_id, file_path)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy file.")
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media)
