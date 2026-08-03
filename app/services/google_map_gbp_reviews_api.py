"""Google Business Profile — Reviews API (v4)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests
from google.oauth2.credentials import Credentials

from app.services.google_map_gbp_api import _auth_headers

_LOG = logging.getLogger("google_map_gbp.reviews_api")

MYBUSINESS_V4 = "https://mybusiness.googleapis.com/v4"

_STAR_MAP = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
}


def _reviews_list_url(account_resource: str, location_resource: str) -> str:
    acct = account_resource if account_resource.startswith("accounts/") else f"accounts/{account_resource}"
    if location_resource.startswith("accounts/"):
        loc_path = "/".join(location_resource.split("/")[-2:])
    elif location_resource.startswith("locations/"):
        loc_path = location_resource
    else:
        loc_path = f"locations/{location_resource}"
    return f"{MYBUSINESS_V4}/{acct}/{loc_path}/reviews"


def _parse_review(item: dict[str, Any]) -> dict[str, Any]:
    reviewer = item.get("reviewer") or {}
    reply = item.get("reviewReply") or {}
    stars_raw = str(item.get("starRating") or "")
    stars = _STAR_MAP.get(stars_raw, 0)
    name = str(item.get("name") or "")
    review_id = str(item.get("reviewId") or name.split("/")[-1] or "")
    reply_text = str(reply.get("comment") or "").strip()
    return {
        "id": review_id,
        "resource_name": name,
        "author": str(reviewer.get("displayName") or "Khách Google"),
        "stars": stars,
        "text": str(item.get("comment") or "").strip(),
        "date": str(item.get("createTime") or ""),
        "replied": bool(reply_text),
        "reply_text": reply_text,
        "reply_date": str(reply.get("updateTime") or ""),
        "is_negative": stars in (1, 2),
    }


def list_location_reviews(
    creds: Credentials,
    *,
    account_resource: str,
    location_resource: str,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    headers = _auth_headers(creds)
    url = _reviews_list_url(account_resource, location_resource)
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"pageSize": min(page_size, 50)}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"reviews.list HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        for raw in data.get("reviews") or []:
            if isinstance(raw, dict):
                items.append(_parse_review(raw))
        page_token = str(data.get("nextPageToken") or "")
        if not page_token:
            break
    return items


def post_review_reply(creds: Credentials, review_resource_name: str, comment: str) -> dict[str, Any]:
    headers = {**_auth_headers(creds), "Content-Type": "application/json"}
    name = review_resource_name.strip().strip("/")
    if not name.startswith("accounts/"):
        raise ValueError("review_resource_name không hợp lệ")
    url = f"{MYBUSINESS_V4}/{name}/reply"
    body = {"comment": str(comment or "")[:4096]}
    r = requests.put(url, headers=headers, json=body, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"reviews.updateReply HTTP {r.status_code}: {r.text[:400]}")
    return r.json() if r.content else {}
