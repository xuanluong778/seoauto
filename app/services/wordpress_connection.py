"""Shared WordPress connection — publishing_sites is the only credential store.

Tabs receive public site list + default_site_id. Credentials stay server-side,
scoped by organization_id + user_id. Never load a site by id alone.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException

from app.services.publishing_sites_pg import site_url_normalized
from app.services.publishing_sites_store import get_site, list_sites

logger = logging.getLogger(__name__)


def _public_item(site: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(site.get("id") or ""),
        "name": str(site.get("name") or site.get("url") or ""),
        "url": str(site.get("url") or ""),
        "username": str(site.get("username") or ""),
        "verified": bool(site.get("verified")),
        "platform": "wordpress",
    }


def list_wordpress_connections(
    *,
    user_id: int,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Public list for tabs — no app_password. Org+user scoped."""
    rows = list_sites(user_id=user_id, organization_id=organization_id, platform="wordpress")
    items = [_public_item(s) for s in rows if str(s.get("id") or "")]
    default_site_id = ""
    if len(items) == 1:
        default_site_id = items[0]["id"]
    else:
        verified = [x for x in items if x.get("verified")]
        if len(verified) == 1:
            default_site_id = verified[0]["id"]
    return {"items": items, "default_site_id": default_site_id}


def _match_by_url(items: list[dict[str, Any]], site_url: str) -> dict[str, Any] | None:
    key = site_url_normalized(site_url)
    if not key:
        return None
    for row in items:
        if site_url_normalized(str(row.get("url") or "")) == key:
            return row
    return None


def resolve_wordpress_connection(
    *,
    user_id: int,
    site_id: str | None = None,
    site_url: str | None = None,
    organization_id: int | None = None,
) -> dict[str, str]:
    """Resolve WP credentials from the shared store. Never trust client secrets.

    Lookup order: site_id → URL match → single saved site.
    Raises HTTPException 400/404. Other orgs cannot resolve this user's sites.
    """
    if int(user_id or 0) <= 0:
        raise HTTPException(status_code=401, detail="Cần đăng nhập.")

    listing = list_wordpress_connections(user_id=user_id, organization_id=organization_id)
    items = listing["items"]
    sid = str(site_id or "").strip()
    url = str(site_url or "").strip()

    chosen: dict[str, Any] | None = None
    if sid:
        chosen = next((x for x in items if x["id"] == sid), None)
        if chosen is None:
            try:
                from app.services.wordpress_site_links_pg import get_credentials_pg

                link_cred = get_credentials_pg(
                    sid,
                    user_id=user_id,
                    organization_id=organization_id,
                )
                if (
                    str(link_cred.get("url") or "").strip()
                    and str(link_cred.get("username") or "").strip()
                    and str(link_cred.get("app_password") or "").strip()
                ):
                    return {
                        "site_id": sid,
                        "url": str(link_cred.get("url") or "").strip(),
                        "username": str(link_cred.get("username") or "").strip(),
                        "app_password": re.sub(
                            r"\s+",
                            "",
                            str(link_cred.get("app_password") or "").strip(),
                        ),
                    }
            except LookupError:
                pass
    if chosen is None and url:
        chosen = _match_by_url(items, url)
    if chosen is None and not sid and not url and listing.get("default_site_id"):
        default_id = str(listing["default_site_id"])
        chosen = next((x for x in items if x["id"] == default_id), None)
    if chosen is None:
        if not items:
            raise HTTPException(
                status_code=400,
                detail="Chưa kết nối WordPress. Thêm website một lần tại Cài đặt → Xuất bản.",
            )
        raise HTTPException(
            status_code=400,
            detail="Chọn website WordPress đã kết nối tại Cài đặt.",
        )

    full = get_site(
        chosen["id"],
        user_id=user_id,
        organization_id=organization_id,
        reveal_password=True,
    )
    if not full or str(full.get("platform") or "").lower() != "wordpress":
        raise HTTPException(status_code=404, detail="Không tìm thấy website đã kết nối.")

    site_url_out = str(full.get("url") or "").strip()
    username = str(full.get("username") or "").strip()
    password = re.sub(r"\s+", "", str(full.get("app_password") or "").strip())
    if not site_url_out or not username or not password:
        logger.warning(
            "wp connection missing secret site_id=%s user_id=%s url=%s user_len=%s pass_len=%s",
            chosen.get("id"),
            user_id,
            site_url_out,
            len(username),
            len(password),
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Không đọc được Application Password đã lưu. "
                "Mở Cài đặt → Xuất bản, nhập lại Application Password rồi Lưu."
            ),
        )
    return {
        "site_id": str(full.get("id") or chosen["id"]),
        "url": site_url_out,
        "username": username,
        "app_password": password,
    }
