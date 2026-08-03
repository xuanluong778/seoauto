"""Web 2.0 provider adapter interface."""

from __future__ import annotations

from typing import Any, Protocol


PLATFORMS = frozenset(
    {
        "wordpress_2_0",
        "blogger",
        "tumblr",
        "medium",
        "google_sites_manual",
    }
)

PLATFORM_LABELS = {
    "wordpress_2_0": "WordPress 2.0 / Site vệ tinh",
    "blogger": "Blogger / Blogspot",
    "tumblr": "Tumblr",
    "medium": "Medium (Beta)",
    "google_sites_manual": "Google Sites (Manual)",
}


class Web20Provider(Protocol):
    platform: str

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]: ...

    def publish_post(self, account: dict[str, Any], secrets: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]: ...

    def list_destinations(self, account: dict[str, Any], secrets: dict[str, Any]) -> list[dict[str, Any]]: ...
