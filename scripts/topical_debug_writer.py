"""
Write topical authority debug JSON files per topic (opt-in via env).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _slug(label: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", (label or "topic").lower()).strip("_")
    return (s[:80] or "topic")[:80]


def maybe_write_topical_debug(
    topic_label: str,
    *,
    topic_graph: dict[str, Any],
    topic_coverage: dict[str, Any],
    topical_gap: dict[str, Any],
    topical_authority_row: dict[str, Any],
    entity_resolved: list[dict[str, Any]] | None = None,
    intent_analysis: dict[str, Any] | None = None,
    serp_alignment: dict[str, Any] | None = None,
    topical_trust: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """
    If ``TOPICAL_AUTH_DEBUG_DIR`` is set, writes JSON debug files under
    ``{dir}/{slug}/``. Returns paths dict or None.
    """
    base = (os.getenv("TOPICAL_AUTH_DEBUG_DIR") or "").strip()
    if not base:
        return None
    slug = _slug(topic_label)
    out_dir = os.path.join(base, slug)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return None

    paths: dict[str, str] = {}
    payloads: dict[str, Any] = {
        "topic_graph.json": topic_graph,
        "topic_coverage.json": topic_coverage,
        "topical_gap.json": topical_gap,
        "topical_authority.json": topical_authority_row,
    }
    if entity_resolved is not None:
        payloads["entity_resolved.json"] = entity_resolved
    if intent_analysis is not None:
        payloads["intent_analysis.json"] = intent_analysis
    if serp_alignment is not None:
        payloads["serp_alignment.json"] = serp_alignment
    if topical_trust is not None:
        payloads["topical_trust.json"] = topical_trust
    for name, payload in payloads.items():
        path = os.path.join(out_dir, name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            paths[name] = path
        except OSError:
            continue
    return paths or None
