"""Structured, grep-friendly crawl logs (job / domain / proxy fields)."""

from __future__ import annotations

import json
import logging
from typing import Any

_LOG = logging.getLogger("crawl.structured")


def crawl_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **{k: v for k, v in fields.items() if v is not None}}
    _LOG.info("%s", json.dumps(payload, ensure_ascii=False, default=str))
