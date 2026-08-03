"""WordPress 2.0 / site vệ tinh — REST API adapter."""

from __future__ import annotations

from typing import Any

from app.services.social_auto_web20_wp import publish_post_to_wp, test_wp_connection


class WordPress20Provider:
    platform = "wordpress_2_0"

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        return test_wp_connection(
            site_url=str(secrets.get("site_url") or account.get("site_url") or ""),
            username=str(secrets.get("username") or account.get("username") or ""),
            app_password=str(secrets.get("app_password") or ""),
        )

    def list_destinations(self, account: dict[str, Any], secrets: dict[str, Any]) -> list[dict[str, Any]]:
        url = str(account.get("site_url") or secrets.get("site_url") or "")
        if not url:
            return []
        return [{"id": account.get("id"), "name": account.get("label") or url, "url": url}]

    def publish_post(self, account: dict[str, Any], secrets: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        status = str(post.get("wp_status") or account.get("default_status") or "draft")
        result = publish_post_to_wp(
            site_url=str(secrets.get("site_url") or account.get("site_url") or ""),
            username=str(secrets.get("username") or ""),
            app_password=str(secrets.get("app_password") or ""),
            title=str(post.get("title") or ""),
            slug=str(post.get("slug") or ""),
            excerpt=str(post.get("excerpt") or ""),
            html_content=str(post.get("html_content") or ""),
            tags=post.get("tags") or [],
            category=str(post.get("category") or ""),
            status=status,
        )
        return {
            "external_id": result.get("wp_post_id"),
            "published_url": result.get("published_url"),
            "status": result.get("status") or status,
            "mode": "api",
        }
