"""
Append-only persistence for SERP ground-truth snapshots and validation events.

Uses JSONL under ``GROUND_TRUTH_DATA_DIR`` (default ``data/ground_truth``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_LOG = logging.getLogger(__name__)


def _base_dir() -> Path:
    raw = (os.getenv("GROUND_TRUTH_DATA_DIR") or "data/ground_truth").strip()
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    (p / "snapshots").mkdir(parents=True, exist_ok=True)
    return p


def _query_hash(query: str) -> str:
    q = (query or "").strip().lower()
    return hashlib.sha256(q.encode("utf-8")).hexdigest()[:32]


def snapshot_path(query: str) -> Path:
    return _base_dir() / "snapshots" / f"{_query_hash(query)}.jsonl"


def append_snapshot(query: str, record: dict[str, Any]) -> Path:
    """
    Append one snapshot line. ``record`` should include ``query``, ``timestamp``, ``results``.
    """
    path = snapshot_path(query)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return path


def iter_snapshots_for_query(query: str) -> list[dict[str, Any]]:
    path = snapshot_path(query)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _LOG.warning("Bad JSONL snapshot line in %s: %s", path, exc)
    out.sort(key=lambda r: str(r.get("timestamp") or ""))
    return out


def validation_log_path() -> Path:
    return _base_dir() / "validation_log.jsonl"


def append_validation_event(record: dict[str, Any]) -> None:
    path = validation_log_path()
    line = json.dumps(record, ensure_ascii=False, default=str)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def iter_validation_events(*, max_lines: int = 500) -> Iterator[dict[str, Any]]:
    path = validation_log_path()
    if not path.is_file():
        return
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
