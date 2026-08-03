"""DataForSEO cost guard for Keyword Research runs."""

from __future__ import annotations

import os
from typing import Any


class KeywordResearchCostExceeded(Exception):
    def __init__(self, message: str, stats: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.stats = stats or {}


def default_max_keywords() -> int:
    return max(20, min(200, int(os.getenv("KEYWORD_RESEARCH_DEFAULT_MAX_KEYWORDS", "80"))))


def max_live_calls_per_run() -> int:
    return max(1, min(50, int(os.getenv("KEYWORD_RESEARCH_MAX_LIVE_CALLS_PER_RUN", "8"))))


def serp_enabled_on_initial_run() -> bool:
    return os.getenv("KEYWORD_RESEARCH_ENABLE_SERP_ON_INITIAL_RUN", "0").lower() in (
        "1",
        "true",
        "yes",
    )


def volume_batch_size() -> int:
    return max(10, min(1000, int(os.getenv("VOLUME_BATCH_SIZE", "1000"))))


def k4k_cache_ttl_seconds() -> int:
    return max(86400, int(os.getenv("KEYWORD_RESEARCH_K4K_CACHE_TTL", "5184000")))


def volume_cache_ttl_seconds() -> int:
    return max(86400, int(os.getenv("VOLUME_CACHE_TTL_SECONDS", "5184000")))


def estimated_cost_usd(stats: dict[str, Any]) -> float:
    per_task = float(os.getenv("KEYWORD_RESEARCH_ESTIMATED_COST_PER_TASK", "0.01"))
    live = int(stats.get("live_calls") or 0)
    return round(live * per_task, 4)


def attach_cost_meta(stats: dict[str, Any] | None) -> dict[str, Any]:
    s = stats or {}
    return {
        "live_calls": int(s.get("live_calls") or 0),
        "api_tasks": int(s.get("api_tasks") or 0),
        "cache_hits": int(s.get("cache_hits") or 0),
        "keywords_api": int(s.get("keywords_api") or 0),
        "estimated_cost_usd": estimated_cost_usd(s),
        "max_live_calls": max_live_calls_per_run(),
    }


def check_and_record_live_call(stats: dict[str, Any] | None, *, label: str) -> None:
    if stats is None:
        return
    if stats.get("cost_aborted"):
        raise KeywordResearchCostExceeded(
            "Đã dừng vì vượt ngưỡng chi phí DataForSEO.",
            stats,
        )
    live = int(stats.get("live_calls") or 0) + 1
    stats["live_calls"] = live
    stats["estimated_cost_usd"] = estimated_cost_usd(stats)
    stats.setdefault("live_call_labels", []).append(label)
    if live > max_live_calls_per_run():
        stats["cost_aborted"] = True
        raise KeywordResearchCostExceeded(
            f"Vượt ngưỡng {max_live_calls_per_run()} request DataForSEO mỗi lần research. "
            "Hãy thu hẹp số từ khóa hoặc dùng lại cache.",
            stats,
        )
