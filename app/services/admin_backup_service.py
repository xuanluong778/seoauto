"""Admin backup service — list runs, trigger, verify."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.backup_run import BackupRun
from app.models.user import User
from app.services.security_audit_log import log_audit_event

logger = logging.getLogger(__name__)

BACKUP_UNITS = {
    "db": "seoauto-backup-db.service",
    "media": "seoauto-backup-media.service",
    "source": "seoauto-backup-source.service",
    "infra": "seoauto-backup-infra.service",
    "full": "seoauto-backup-full.service",
}

TIMER_INFO = [
    {"name": "seoauto-backup-db.timer", "label": "Database", "schedule": "02:00 daily"},
    {"name": "seoauto-backup-source.timer", "label": "Source code", "schedule": "02:15 daily"},
    {"name": "seoauto-backup-media.timer", "label": "Uploads/Media", "schedule": "02:30 daily"},
    {"name": "seoauto-backup-infra.timer", "label": "Infra/Config", "schedule": "02:45 daily"},
]


def log_admin_backup_action(action: str, admin: User, *, detail: dict | None = None, request=None) -> None:
    log_audit_event(
        action=f"admin.backup.{action}",
        user_id=admin.id,
        resource_type="backup_run",
        detail=detail or {},
        request=request,
    )


def list_backup_runs_admin(
    db: Session,
    *,
    backup_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    q = db.query(BackupRun)
    if backup_type:
        q = q.filter(BackupRun.backup_type == backup_type.strip().lower())
    if status:
        q = q.filter(BackupRun.status == status.strip().lower())
    total = q.count()
    rows = q.order_by(desc(BackupRun.started_at)).offset(offset).limit(limit).all()
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def get_backup_run_admin(db: Session, run_id: str) -> BackupRun | None:
    return db.query(BackupRun).filter(BackupRun.run_id == run_id).first()


def get_backup_status_admin(db: Session) -> dict[str, Any]:
    last_runs: dict[str, BackupRun | None] = {}
    for btype in ("db", "media", "source", "infra"):
        last_runs[btype] = (
            db.query(BackupRun)
            .filter(BackupRun.backup_type == btype)
            .order_by(desc(BackupRun.started_at))
            .first()
        )
    lock_active = False
    try:
        from pathlib import Path
        lock_active = Path("/var/run/seoauto-backup.lock").exists()
    except OSError:
        pass
    timers = []
    for t in TIMER_INFO:
        active = "unknown"
        next_run = ""
        try:
            r = subprocess.run(
                ["systemctl", "is-active", t["name"]],
                capture_output=True, text=True, timeout=5,
            )
            active = (r.stdout or "").strip() or "inactive"
            r2 = subprocess.run(
                ["systemctl", "list-timers", t["name"], "--no-pager"],
                capture_output=True, text=True, timeout=5,
            )
            for line in (r2.stdout or "").splitlines():
                if t["name"] in line and "NEXT" not in line and "n/a" not in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        next_run = parts[1] if parts[0] == t["name"] else parts[0]
                    break
        except (OSError, subprocess.TimeoutExpired):
            pass
        timers.append({**t, "active": active, "next": next_run})
    return {"last_runs": last_runs, "timers": timers, "lock_active": lock_active}


def trigger_backup_admin(db: Session, admin: User, mode: str) -> dict[str, Any]:
    mode = (mode or "db").strip().lower()
    unit = BACKUP_UNITS.get(mode)
    if not unit:
        return {"ok": False, "message": f"Loại backup không hợp lệ: {mode}"}
    row = BackupRun(
        run_id=f"manual_{int(datetime.now(timezone.utc).timestamp())}",
        backup_type=mode,
        status="pending",
        trigger_type="manual",
        admin_id=admin.id,
    )
    db.add(row)
    db.flush()
    script = "/var/www/seoauto_vn_usr4940/data/www/seoauto.vn/scripts/backup/backup_seoauto.sh"
    flag = f"--{mode}" if mode != "full" else "--full"
    try:
        r = subprocess.run(
            ["sudo", "-n", "systemctl", "start", unit],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            r2 = subprocess.Popen(
                ["/bin/bash", script, flag],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if r2.pid:
                return {"ok": True, "message": f"Đã khởi chạy backup {mode} (PID {r2.pid})", "run_id": row.run_id}
            row.status = "failed"
            row.error_message = (r.stderr or r.stdout or "systemctl failed")[:500]
            return {"ok": False, "message": row.error_message}
        return {"ok": True, "message": f"Đã khởi chạy {unit}", "run_id": row.run_id}
    except (OSError, subprocess.TimeoutExpired) as exc:
        row.status = "failed"
        row.error_message = str(exc)[:500]
        return {"ok": False, "message": str(exc)}


def verify_backup_admin(db: Session, run_id: str) -> dict[str, Any]:
    row = get_backup_run_admin(db, run_id)
    if row is None:
        return {"ok": False, "message": "Không tìm thấy backup run"}
    script = "/var/www/seoauto_vn_usr4940/data/www/seoauto.vn/scripts/backup/backup_verify.sh"
    try:
        r = subprocess.run(
            ["/bin/bash", script, run_id, row.backup_type],
            capture_output=True, text=True, timeout=600,
        )
        ok = r.returncode == 0
        row.verify_status = "verified" if ok else "verify_failed"
        if not ok:
            row.error_message = (r.stderr or r.stdout or "verify failed")[-1000:]
        return {"ok": ok, "message": "Verify PASS" if ok else (row.error_message or "Verify FAIL")}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": str(exc)}


def parse_manifest(row: BackupRun) -> dict | None:
    if not row.manifest_json:
        return None
    try:
        return json.loads(row.manifest_json)
    except json.JSONDecodeError:
        return None
