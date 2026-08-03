"""
Persistence for SEO Autopilot: action outcomes and learning aggregates.

JSONL under ``AUTOPILOT_DATA_DIR`` (default ``data/autopilot``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator

_LOG = logging.getLogger(__name__)


def _base_dir() -> Path:
    raw = (os.getenv("AUTOPILOT_DATA_DIR") or "data/autopilot").strip()
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def outcomes_path() -> Path:
    return _base_dir() / "action_outcomes.jsonl"


def append_action_outcome(record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, default=str)
    with outcomes_path().open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def iter_action_outcomes(*, max_lines: int = 800) -> Iterator[dict[str, Any]]:
    path = outcomes_path()
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            _LOG.debug("skip bad outcome line")


def site_key(domain_or_url: str) -> str:
    s = (domain_or_url or "").strip().lower()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def record_autopilot_outcome(
    *,
    action_id: str,
    issue_type: str,
    query: str,
    monitored_url: str,
    predicted_impact_delta_prob: float,
    actual_impact_delta_prob: float | None,
    success: bool | None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one post-validation measurement (typically after a new ground-truth fetch)."""
    row = {
        "action_id": action_id,
        "issue_type": issue_type,
        "query": query,
        "monitored_url": monitored_url,
        "predicted_impact_delta_prob": predicted_impact_delta_prob,
        "actual_impact_delta_prob": actual_impact_delta_prob,
        "success": success,
    }
    if extra:
        row.update(extra)
    append_action_outcome(row)
