"""In-memory + disk pause state for Check Index Free (CAPTCHA / resume)."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from app.services.user_data_paths import user_data_dir

_LOG = logging.getLogger(__name__)
_LOCK = threading.RLock()
_JOBS: dict[str, dict[str, Any]] = {}


def _job_key(user_id: int, check_id: int) -> str:
    return f"{int(user_id)}:{int(check_id)}"


def _disk_path(user_id: int) -> Path:
    return user_data_dir(int(user_id)) / "index_check_free_jobs.json"


def _load_disk(user_id: int) -> dict[str, Any]:
    path = _disk_path(user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_disk(user_id: int, store: dict[str, Any]) -> None:
    path = _disk_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def save_paused_job(
    *,
    user_id: int,
    check_id: int,
    pending_urls: list[str],
    done_count: int,
    total: int,
    project_name: str | None = None,
    captcha_url: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    job = {
        "user_id": int(user_id),
        "check_id": int(check_id),
        "status": "captcha_paused",
        "pending_urls": list(pending_urls or []),
        "done_count": int(done_count),
        "total": int(total),
        "project_name": project_name,
        "captcha_url": captcha_url,
        "reason": reason or "Google yêu cầu xác minh (CAPTCHA / unusual traffic).",
        "updated_at": time.time(),
    }
    key = _job_key(user_id, check_id)
    with _LOCK:
        _JOBS[key] = job
        store = _load_disk(user_id)
        store[str(int(check_id))] = job
        _save_disk(user_id, store)
    return dict(job)


def get_paused_job(*, user_id: int, check_id: int) -> dict[str, Any] | None:
    key = _job_key(user_id, check_id)
    with _LOCK:
        job = _JOBS.get(key)
        if job and int(job.get("user_id") or 0) == int(user_id):
            return dict(job)
        store = _load_disk(user_id)
        raw = store.get(str(int(check_id)))
        if isinstance(raw, dict) and int(raw.get("user_id") or 0) == int(user_id):
            _JOBS[key] = raw
            return dict(raw)
    return None


def get_latest_paused_job(*, user_id: int) -> dict[str, Any] | None:
    with _LOCK:
        store = _load_disk(user_id)
        best: dict[str, Any] | None = None
        for raw in store.values():
            if not isinstance(raw, dict):
                continue
            if int(raw.get("user_id") or 0) != int(user_id):
                continue
            if str(raw.get("status") or "") != "captcha_paused":
                continue
            if not raw.get("pending_urls"):
                continue
            if best is None or float(raw.get("updated_at") or 0) > float(best.get("updated_at") or 0):
                best = raw
        if best:
            key = _job_key(user_id, int(best["check_id"]))
            _JOBS[key] = best
            return dict(best)
    return None


def clear_paused_job(*, user_id: int, check_id: int) -> None:
    key = _job_key(user_id, check_id)
    with _LOCK:
        _JOBS.pop(key, None)
        store = _load_disk(user_id)
        store.pop(str(int(check_id)), None)
        _save_disk(user_id, store)
