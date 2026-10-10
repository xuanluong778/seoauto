"""WAVE 6 — business API response cache + query optimizations."""

from __future__ import annotations

import os


def business_api_cache_enabled() -> bool:
    return os.getenv("BUSINESS_API_CACHE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def request_auth_dedup_enabled() -> bool:
    return os.getenv("REQUEST_AUTH_DEDUP", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
