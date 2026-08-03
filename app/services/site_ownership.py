"""Verify WordPress / publishing site URLs belong to the current user."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status

from app.services.publishing_sites_store import list_sites as list_publishing_sites
from app.services.user_scope import belongs_to_user, is_admin_role
from app.services.wp_connect import normalize_wp_base_url
from app.services.wp_site_connector import _read_sites as _read_wp_sites


def _host_key(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (p.netloc or p.path or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host.rstrip("/")
    except Exception:
        return raw.lower().rstrip("/")


def _normalize_wp_site(url: str) -> str:
    try:
        return normalize_wp_base_url(str(url or "").strip())
    except Exception:
        return str(url or "").strip().rstrip("/")


def _urls_for_user(user_id: int) -> set[str]:
    hosts: set[str] = set()
    bases: set[str] = set()
    for s in _read_wp_sites():
        if not belongs_to_user(s, user_id):
            continue
        u = str(s.get("url") or "").strip()
        if u:
            bases.add(_normalize_wp_site(u))
            hosts.add(_host_key(u))
    try:
        for s in list_publishing_sites(user_id=user_id):
            u = str(s.get("url") or s.get("website_url") or "").strip()
            if u:
                bases.add(_normalize_wp_site(u))
                hosts.add(_host_key(u))
    except Exception:
        pass
    return bases | hosts


def user_owns_wp_site(user_id: int, wp_site: str, *, role: str = "user") -> bool:
    if is_admin_role(role):
        return bool(str(wp_site or "").strip())
    target_base = _normalize_wp_site(wp_site)
    target_host = _host_key(wp_site)
    if not target_base and not target_host:
        return False
    owned = _urls_for_user(user_id)
    if target_base in owned or target_host in owned:
        return True
    for o in owned:
        if "://" in o:
            if o == target_base:
                return True
            oh = _host_key(o)
            if oh and target_host and (oh == target_host or oh in target_host or target_host in oh):
                return True
        elif o == target_host:
            return True
    return False


def require_wp_site_owner(
    user_id: int,
    wp_site: str,
    *,
    role: str = "user",
    detail: str = "Không tìm thấy website hoặc bạn không có quyền truy cập.",
) -> str:
    site = str(wp_site or "").strip()
    if not site:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wp_site is required")
    if not user_owns_wp_site(user_id, site, role=role):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return _normalize_wp_site(site)
