"""Platform card status + publish readiness for Social Auto Web 2.0."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

CARD_CONNECTED = "connected"
CARD_NEED_SETUP = "need_setup"
CARD_TOKEN_EXPIRED = "token_expired"
CARD_BETA = "beta"
CARD_MANUAL = "manual"
CARD_COMING_SOON = "coming_soon"

CARD_STATUS_LABELS = {
    CARD_CONNECTED: "Connected",
    CARD_NEED_SETUP: "Need setup",
    CARD_TOKEN_EXPIRED: "Token expired",
    CARD_BETA: "Beta",
    CARD_MANUAL: "Manual",
    CARD_COMING_SOON: "Coming soon",
}

PLATFORM_META: dict[str, dict[str, Any]] = {
    "wordpress_2_0": {"publish_mode": "auto", "supports_auto_publish": True, "label": "WordPress 2.0"},
    "blogger": {"publish_mode": "auto", "supports_auto_publish": True, "label": "Blogger"},
    "tumblr": {"publish_mode": "auto", "supports_auto_publish": True, "label": "Tumblr"},
    "medium": {"publish_mode": "auto", "supports_auto_publish": True, "label": "Medium (Beta)", "card_default": CARD_BETA},
    "google_sites_manual": {"publish_mode": "manual", "supports_auto_publish": False, "label": "Google Sites (Manual)", "card_default": CARD_MANUAL},
    "zalo_oa": {"publish_mode": "none", "supports_auto_publish": False, "label": "Zalo OA", "card_default": CARD_COMING_SOON},
    "facebook": {"publish_mode": "auto", "supports_auto_publish": True, "label": "Facebook Fanpage"},
}


def supports_auto_publish(platform: str) -> bool:
    meta = PLATFORM_META.get(str(platform or "").strip().lower(), {})
    return bool(meta.get("supports_auto_publish"))


def _is_token_error(account: dict[str, Any]) -> bool:
    if str(account.get("status") or "").lower() == "error":
        return True
    if str(account.get("connection_mode") or "").lower() == "error":
        return True
    msg = str(account.get("last_test_message") or "").lower()
    return any(x in msg for x in ("expired", "invalid", "401", "403", "unauthorized", "revoked", "hết hạn"))


def account_card_status(account: dict[str, Any]) -> str:
    pf = str(account.get("platform") or "").strip().lower()
    meta = PLATFORM_META.get(pf, {})
    default = str(meta.get("card_default") or CARD_CONNECTED)
    if meta.get("publish_mode") == "manual":
        return CARD_MANUAL
    if meta.get("publish_mode") == "none":
        return CARD_COMING_SOON
    if not account.get("has_credentials", True):
        return CARD_NEED_SETUP
    if _is_token_error(account):
        return CARD_TOKEN_EXPIRED
    if pf == "medium":
        return CARD_BETA
    return CARD_CONNECTED


def platform_card_status(platform: str, accounts: list[dict[str, Any]] | None = None) -> str:
    pf = str(platform or "").strip().lower()
    meta = PLATFORM_META.get(pf, {})
    if meta.get("publish_mode") == "none":
        return CARD_COMING_SOON
    if meta.get("publish_mode") == "manual":
        return CARD_MANUAL
    if not accounts:
        return CARD_NEED_SETUP
    statuses = {account_card_status(a) for a in accounts}
    if CARD_TOKEN_EXPIRED in statuses:
        return CARD_TOKEN_EXPIRED
    if pf == "medium":
        return CARD_BETA
    return CARD_CONNECTED


def assert_account_publish_ready(
    account: dict[str, Any],
    *,
    source: str = "manual",
    for_schedule: bool = False,
) -> None:
    pf = str(account.get("platform") or "").strip().lower()
    status = account_card_status(account)

    if pf == "google_sites_manual":
        if for_schedule or source in {"scheduler", "schedule"}:
            raise HTTPException(
                status_code=400,
                detail="Google Sites chỉ hỗ trợ Manual Package — không lên lịch/đăng tự động.",
            )
        return

    if not supports_auto_publish(pf):
        raise HTTPException(status_code=400, detail="Nền tảng chưa hỗ trợ đăng tự động.")

    if status == CARD_NEED_SETUP:
        raise HTTPException(status_code=400, detail="Chưa kết nối nền tảng — hoàn tất cài đặt trước khi đăng.")
    if status == CARD_TOKEN_EXPIRED:
        raise HTTPException(
            status_code=400,
            detail="Token/API hết hạn hoặc không hợp lệ — kết nối lại nền tảng.",
        )
    if status == CARD_COMING_SOON:
        raise HTTPException(status_code=400, detail="Nền tảng đang Coming soon — chưa thể publish.")
