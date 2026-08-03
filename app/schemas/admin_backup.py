"""Admin backup API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AdminBackupRunRow(BaseModel):
    id: int
    run_id: str
    backup_type: str
    status: str
    trigger_type: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: int | None = None
    size_bytes: int | None = None
    remote_path: str | None = None
    checksum_sha256: str | None = None
    verify_status: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AdminBackupRunDetail(AdminBackupRunRow):
    local_dir: str | None = None
    manifest: dict[str, Any] | None = None


class AdminBackupRunListResponse(BaseModel):
    items: list[AdminBackupRunRow]
    total: int
    limit: int
    offset: int


class AdminBackupStatusResponse(BaseModel):
    last_runs: dict[str, AdminBackupRunRow | None] = Field(default_factory=dict)
    timers: list[dict[str, str]] = Field(default_factory=list)
    lock_active: bool = False


class AdminBackupActionResponse(BaseModel):
    ok: bool
    message: str
    run_id: str | None = None
