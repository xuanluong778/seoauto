"""Google Map SEO — sync guard & 429 handling tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.google_map_gbp_api import (
    GbpApiError,
    _MAX_RETRIES,
    _request_with_retry,
    classify_gbp_api_error,
    compute_retry_delay,
)
from app.services.google_map_gbp_sync_guard import (
    ACCOUNTS_CACHE_TTL_SEC,
    GbpSyncGuard,
    ensure_google_api_allowed,
    get_accounts_cached,
    get_locations_cached,
    invalidate_accounts_cache,
    is_rate_limited,
    mark_rate_limited,
    retry_after_seconds,
    set_accounts_cached,
    set_locations_cached,
)


def test_mark_rate_limited_respects_retry_after():
    user_id = 900001
    invalidate_accounts_cache(user_id)
    mark_rate_limited(user_id, retry_after_sec=45, reason="test")
    assert is_rate_limited(user_id)
    sec = retry_after_seconds(user_id)
    assert sec is not None
    assert 1 <= sec <= 45


def test_ensure_google_api_allowed_raises_during_cooldown():
    user_id = 900002
    mark_rate_limited(user_id, retry_after_sec=30, reason="test")
    with pytest.raises(GbpApiError) as exc:
        ensure_google_api_allowed(user_id, "manual_sync")
    assert exc.value.status_code == 429
    assert exc.value.is_quota


def test_accounts_cache_ttl_10_minutes():
    assert ACCOUNTS_CACHE_TTL_SEC == 600


def test_accounts_cache_hit():
    user_id = 900003
    set_accounts_cached(user_id, [{"name": "accounts/1"}])
    cached = get_accounts_cached(user_id)
    assert cached is not None
    assert cached[0]["name"] == "accounts/1"


def test_locations_cache_hit():
    user_id = 900010
    set_locations_cached(user_id, "accounts/1", [{"name": "locations/1"}])
    cached = get_locations_cached(user_id, "accounts/1")
    assert cached is not None
    assert cached[0]["name"] == "locations/1"


def test_gbp_sync_guard_single_flight():
    user_id = 900004
    with GbpSyncGuard(user_id, 11) as g1:
        assert g1.acquired is True
        with GbpSyncGuard(user_id, 11) as g2:
            assert g2.acquired is False


def test_gbp_sync_guard_different_users_parallel():
    with GbpSyncGuard(900005, 1) as g1, GbpSyncGuard(900006, 1) as g2:
        assert g1.acquired is True
        assert g2.acquired is True


def test_compute_retry_delay_prefers_retry_after():
    assert compute_retry_delay(0, 90) == 90.0
    d = compute_retry_delay(2, None)
    assert d >= 8.0


def test_compute_retry_delay_caps_retry_after():
    assert compute_retry_delay(0, 900) == 600.0


def test_classify_gbp_api_error_quota():
    err = GbpApiError("quota", status_code=429, endpoint="accounts.list")
    assert classify_gbp_api_error(err) == "api_quota"


def test_classify_oauth_invalid():
    assert classify_gbp_api_error(Exception("401 unauthorized")) == "api_unauthorized"


def test_request_with_retry_stops_after_max_retries():
    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.headers = {"Retry-After": "1"}
    resp429.text = "rate limit"
    resp429.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED"}}

    with patch("app.services.google_map_gbp_api.requests.request", return_value=resp429) as req:
        with patch("app.services.google_map_gbp_api.time.sleep"):
            with pytest.raises(GbpApiError) as exc:
                _request_with_retry(
                    method="GET",
                    url="https://example.com/accounts",
                    headers={},
                    endpoint="accounts.list",
                    source_action="test",
                    user_id=900007,
                )
    assert exc.value.status_code == 429
    assert exc.value.retry_count == _MAX_RETRIES
    assert req.call_count == _MAX_RETRIES + 1


def test_request_with_retry_succeeds_after_transient_429():
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"accounts": []}
    fail = MagicMock()
    fail.status_code = 429
    fail.headers = {"Retry-After": "2"}
    fail.text = "rate limit"
    fail.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED"}}

    with patch("app.services.google_map_gbp_api.requests.request", side_effect=[fail, ok]) as req:
        with patch("app.services.google_map_gbp_api.time.sleep"):
            r = _request_with_retry(
                method="GET",
                url="https://example.com/accounts",
                headers={},
                endpoint="accounts.list",
                source_action="test",
                user_id=900008,
            )
    assert r.status_code == 200
    assert req.call_count == 2
