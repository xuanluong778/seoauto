"""In-memory registry mapping async task IDs to owner user_id (Celery poll IDOR guard)."""

from __future__ import annotations

from threading import Lock

from fastapi import HTTPException, status

from app.services.user_scope import is_admin_role

_lock = Lock()
_owners: dict[str, int] = {}


def register_task_owner(task_id: str, user_id: int) -> None:
    tid = str(task_id or "").strip()
    if not tid:
        return
    with _lock:
        _owners[tid] = int(user_id)


def assert_task_owner(task_id: str, user_id: int, *, role: str = "user") -> None:
    tid = str(task_id or "").strip()
    if not tid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy task.")
    if is_admin_role(role):
        return
    with _lock:
        owner = _owners.get(tid)
    if owner is None or int(owner) != int(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy task.")
