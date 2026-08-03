"""Google Business Profile — Media upload API (v4 stub)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from google.oauth2.credentials import Credentials

from app.services.google_map_gbp_api import _auth_headers

_LOG = logging.getLogger("google_map_gbp.media_api")

MYBUSINESS_V4 = "https://mybusiness.googleapis.com/v4"


def _media_url(account_resource: str, location_resource: str) -> str:
    acct = account_resource if account_resource.startswith("accounts/") else f"accounts/{account_resource}"
    if location_resource.startswith("accounts/"):
        loc_path = "/".join(location_resource.split("/")[-2:])
    elif location_resource.startswith("locations/"):
        loc_path = location_resource
    else:
        loc_path = f"locations/{location_resource}"
    return f"{MYBUSINESS_V4}/{acct}/{loc_path}/media"


def upload_location_media(
    creds: Credentials,
    *,
    account_resource: str,
    location_resource: str,
    source_url: str,
    media_format: str = "PHOTO",
    description: str = "",
) -> dict[str, Any]:
    """Đăng ảnh lên GBP qua URL nguồn (ảnh phải public)."""
    headers = {**_auth_headers(creds), "Content-Type": "application/json"}
    url = _media_url(account_resource, location_resource)
    body: dict[str, Any] = {
        "mediaFormat": media_format,
        "locationAssociation": {"category": "CATEGORY_UNSPECIFIED"},
        "sourceUrl": source_url,
    }
    if description:
        body["description"] = description[:1000]
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"media.create HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    return {
        "name": str(data.get("name") or ""),
        "googleUrl": str(data.get("googleUrl") or ""),
    }
