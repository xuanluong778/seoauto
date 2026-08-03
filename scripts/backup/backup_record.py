#!/usr/bin/env python3
"""Record backup runs to backup_runs table for admin UI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = os.environ.get("APP_ROOT", "/var/www/seoauto_vn_usr4940/data/www/seoauto.vn")
sys.path.insert(0, APP_ROOT)
os.chdir(APP_ROOT)

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(APP_ROOT) / "env.local")
        load_dotenv("/etc/seoauto/backup.env")
    except ImportError:
        pass

def _session():
    _load_env()
    from app.db import SessionLocal
    return SessionLocal()

def cmd_start(args: argparse.Namespace) -> int:
    db = _session()
    try:
        from app.models.backup_run import BackupRun
        existing = db.query(BackupRun).filter(BackupRun.run_id == args.run_id).first()
        if existing:
            existing.status = "running"
            existing.started_at = datetime.now(timezone.utc)
            existing.error_message = None
        else:
            db.add(BackupRun(
                run_id=args.run_id,
                backup_type=args.type,
                status="running",
                trigger_type=args.trigger or "scheduled",
                local_dir=args.local_dir,
            ))
        db.commit()
        return 0
    except Exception as exc:
        db.rollback()
        print(f"backup_record start error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

def cmd_finish(args: argparse.Namespace) -> int:
    db = _session()
    try:
        from app.models.backup_run import BackupRun
        row = db.query(BackupRun).filter(BackupRun.run_id == args.run_id).first()
        if not row:
            row = BackupRun(run_id=args.run_id, backup_type=args.type or "db", status="failed", trigger_type="scheduled")
            db.add(row)
        row.status = args.status
        row.finished_at = datetime.now(timezone.utc)
        if args.duration is not None:
            row.duration_seconds = int(args.duration)
        if args.size_bytes is not None:
            row.size_bytes = int(args.size_bytes)
        if args.remote_path:
            row.remote_path = args.remote_path
        if args.checksum:
            row.checksum_sha256 = args.checksum
        if args.error:
            row.error_message = args.error[:2000]
        if args.manifest and Path(args.manifest).is_file():
            row.manifest_json = Path(args.manifest).read_text(encoding="utf-8")[:50000]
        if args.verify_status:
            row.verify_status = args.verify_status
        db.commit()
        return 0
    except Exception as exc:
        db.rollback()
        print(f"backup_record finish error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--run-id", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--trigger", default="scheduled")
    s.add_argument("--local-dir", default="")
    s.set_defaults(func=cmd_start)
    f = sub.add_parser("finish")
    f.add_argument("--run-id", required=True)
    f.add_argument("--status", required=True)
    f.add_argument("--type", default="")
    f.add_argument("--duration", type=int, default=None)
    f.add_argument("--size-bytes", type=int, default=None)
    f.add_argument("--remote-path", default="")
    f.add_argument("--checksum", default="")
    f.add_argument("--error", default="")
    f.add_argument("--manifest", default="")
    f.add_argument("--verify-status", default="")
    f.set_defaults(func=cmd_finish)
    args = p.parse_args()
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
