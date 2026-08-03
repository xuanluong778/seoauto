"""Platform card status + publish readiness."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.web20_platform_status import (
    CARD_BETA,
    CARD_COMING_SOON,
    CARD_MANUAL,
    CARD_NEED_SETUP,
    CARD_TOKEN_EXPIRED,
    account_card_status,
    assert_account_publish_ready,
    platform_card_status,
    supports_auto_publish,
)


def test_supports_auto_publish():
    assert supports_auto_publish("wordpress_2_0") is True
    assert supports_auto_publish("google_sites_manual") is False
    assert supports_auto_publish("zalo_oa") is False


def test_platform_card_status_zalo():
    assert platform_card_status("zalo_oa", []) == CARD_COMING_SOON


def test_platform_card_status_google_sites():
    assert platform_card_status("google_sites_manual", []) == CARD_MANUAL


def test_account_card_status_medium_beta():
    acc = {"platform": "medium", "has_credentials": True, "status": "connected", "connection_mode": "live"}
    assert account_card_status(acc) == CARD_BETA


def test_account_token_expired():
    acc = {
        "platform": "blogger",
        "has_credentials": True,
        "status": "error",
        "connection_mode": "error",
        "last_test_message": "Token expired",
    }
    assert account_card_status(acc) == CARD_TOKEN_EXPIRED


def test_assert_blocks_google_sites_schedule():
    acc = {"platform": "google_sites_manual", "has_credentials": True}
    with pytest.raises(HTTPException) as exc:
        assert_account_publish_ready(acc, source="schedule", for_schedule=True)
    assert "Manual Package" in str(exc.value.detail)


def test_assert_blocks_need_setup():
    acc = {"platform": "wordpress_2_0", "has_credentials": False, "status": "connected", "connection_mode": "live"}
    with pytest.raises(HTTPException):
        assert_account_publish_ready(acc, source="manual")
