"""Medium — integration token (Beta)."""

from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import HTTPException


MEDIUM_API = "https://api.medium.com/v1"


def is_mock_mode() -> bool:
    if str(os.getenv("WEB20_MEDIUM_MOCK", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def fetch_user(integration_token: str) -> dict[str, Any]:
    if integration_token == "mock_medium_token":
        return {"id": "mock_medium_user", "username": "mockuser", "name": "Medium Mock User"}
    r = requests.get(
        f"{MEDIUM_API}/me",
        headers={"Authorization": f"Bearer {integration_token}", "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Medium /me: {(r.text or '')[:300]}")
    data = r.json().get("data") or {}
    return {
        "id": str(data.get("id") or ""),
        "username": str(data.get("username") or ""),
        "name": str(data.get("name") or ""),
    }


class MediumProvider:
    platform = "medium"

    def test_connection(self, account: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        token = str(secrets.get("integration_token") or "")
        if not token:
            return {"ok": False, "message": "Thiếu integration token Medium."}
        try:
            user = fetch_user(token)
        except HTTPException as exc:
            return {"ok": False, "message": str(exc.detail)}
        return {"ok": True, "message": f"Kết nối Medium — @{user.get('username')}", "user": user}

    def list_destinations(self, account: dict[str, Any], secrets: dict[str, Any]) -> list[dict[str, Any]]:
        user_id = str(account.get("external_id") or secrets.get("medium_user_id") or "")
        username = str(account.get("label") or "")
        if not user_id:
            return []
        return [{"id": user_id, "name": username or user_id, "url": f"https://medium.com/@{username}" if username else ""}]

    def publish_post(self, account: dict[str, Any], secrets: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        token = str(secrets.get("integration_token") or "")
        user_id = str(account.get("external_id") or secrets.get("medium_user_id") or "")
        if not token or not user_id:
            raise HTTPException(status_code=400, detail="Thiếu token hoặc user Medium.")
        title = str(post.get("title") or "Bài viết Web 2.0")
        content = str(post.get("html_content") or post.get("content") or "")
        publish_status = "draft"
        if str(post.get("wp_status") or account.get("default_status") or "draft") == "publish":
            publish_status = "public"
        tags = post.get("tags") or []
        tag_list = [str(t).strip() for t in tags if str(t).strip()][:5]
        if token == "mock_medium_token":
            return {
                "external_id": "mock_medium_post",
                "published_url": "https://medium.com/@mockuser/mock-post",
                "status": publish_status,
                "mode": "mock",
            }
        payload = {
            "title": title,
            "contentFormat": "html",
            "content": content,
            "tags": tag_list,
            "publishStatus": publish_status,
        }
        r = requests.post(
            f"{MEDIUM_API}/users/{user_id}/posts",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Medium API: {(r.text or '')[:400]}")
        data = r.json().get("data") or {}
        return {
            "external_id": data.get("id"),
            "published_url": str(data.get("url") or ""),
            "status": publish_status,
            "mode": "api",
        }
