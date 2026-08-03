"""Registry for Web 2.0 platform adapters."""

from __future__ import annotations

from typing import Any

from app.services.web20_providers.base import PLATFORMS, PLATFORM_LABELS, Web20Provider
from app.services.web20_providers.blogger import BloggerProvider
from app.services.web20_providers.google_sites_manual import GoogleSitesManualProvider
from app.services.web20_providers.medium import MediumProvider
from app.services.web20_providers.tumblr import TumblrProvider
from app.services.web20_providers.wordpress_2_0 import WordPress20Provider

_PROVIDERS: dict[str, Web20Provider] = {
    "wordpress_2_0": WordPress20Provider(),
    "blogger": BloggerProvider(),
    "tumblr": TumblrProvider(),
    "medium": MediumProvider(),
    "google_sites_manual": GoogleSitesManualProvider(),
}


def get_provider(platform: str) -> Web20Provider:
    key = str(platform or "").strip().lower()
    if key not in _PROVIDERS:
        raise ValueError(f"Unsupported platform: {platform}")
    return _PROVIDERS[key]


def list_platforms() -> list[dict[str, Any]]:
    return [{"id": p, "label": PLATFORM_LABELS.get(p, p)} for p in sorted(PLATFORMS)]
