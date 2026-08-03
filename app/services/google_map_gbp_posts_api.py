"""Google Business Profile — Local Posts API (v4)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from google.oauth2.credentials import Credentials

from app.services.google_map_gbp_api import _auth_headers

_LOG = logging.getLogger("google_map_gbp.posts_api")

MYBUSINESS_V4 = "https://mybusiness.googleapis.com/v4"

_CTA_API = {
    "call": "CALL",
    "book": "BOOK",
    "learn_more": "LEARN_MORE",
    "message": "LEARN_MORE",
}

_TOPIC_API = {
    "service_update": "STANDARD",
    "promotion": "OFFER",
    "event": "EVENT",
    "news": "STANDARD",
    "case_study": "STANDARD",
}


def _local_posts_url(account_resource: str, location_resource: str) -> str:
    acct = account_resource if account_resource.startswith("accounts/") else f"accounts/{account_resource}"
    if location_resource.startswith("accounts/"):
        loc_path = "/".join(location_resource.split("/")[-2:])
    elif location_resource.startswith("locations/"):
        loc_path = location_resource
    else:
        loc_path = f"locations/{location_resource}"
    return f"{MYBUSINESS_V4}/{acct}/{loc_path}/localPosts"


def create_local_post(
    creds: Credentials,
    *,
    account_resource: str,
    location_resource: str,
    post_type: str,
    title: str,
    content: str,
    cta_type: str,
) -> dict[str, Any]:
    """Tạo Local Post trên GBP — có thể lỗi nếu API chưa bật / chưa được duyệt quota."""
    headers = {**_auth_headers(creds), "Content-Type": "application/json"}
    url = _local_posts_url(account_resource, location_resource)
    ptype = str(post_type or "service_update").strip().lower()
    cta = str(cta_type or "learn_more").strip().lower()
    body: dict[str, Any] = {
        "languageCode": "vi",
        "summary": str(title or content or "")[:58],
        "topicType": _TOPIC_API.get(ptype, "STANDARD"),
    }
    action = _CTA_API.get(cta, "LEARN_MORE")
    body["callToAction"] = {"actionType": action}
    if ptype == "promotion":
        body["offer"] = {"couponCode": "", "redeemOnlineUrl": "", "termsConditions": content[:1000]}
        body["summary"] = str(title or content[:58])[:58]
    elif ptype == "event":
        body["event"] = {"title": title[:58], "schedule": {}}
        body["summary"] = str(content or title)[:1500]
    else:
        combined = f"{title}\n\n{content}".strip() if title else content
        if combined:
            body["summary"] = combined[:1500]

    r = requests.post(url, headers=headers, json=body, timeout=45)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"localPosts.create HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    return {
        "name": str(data.get("name") or ""),
        "state": str(data.get("state") or ""),
        "searchUrl": str(data.get("searchUrl") or ""),
    }
