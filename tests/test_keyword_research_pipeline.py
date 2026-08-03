from __future__ import annotations

from app.services.search_volume import monthly_search_volume_shape


def test_monthly_shape_estimated_flag() -> None:
    s = monthly_search_volume_shape("example query test", avg_monthly=1200, volume_source="estimated")
    assert s["is_estimated"] is True
    assert s["jan"] >= 0
    assert abs(sum(s[m] for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]) - 1200 * 12) <= 12


def test_monthly_shape_api_flat() -> None:
    s = monthly_search_volume_shape("buy shoes", avg_monthly=500, volume_source="api")
    assert s["is_estimated"] is False
    assert s["feb"] == 500


def test_monthly_shape_dataforseo_flat() -> None:
    s = monthly_search_volume_shape("dịch vụ seo", avg_monthly=33100, volume_source="dataforseo")
    assert s["is_estimated"] is False
    assert s["avg_monthly"] == 33100
    assert s["jan"] == 33100


def test_monthly_shape_dataforseo_zero_volume() -> None:
    s = monthly_search_volume_shape("best dịch vụ seo", avg_monthly=0, volume_source="dataforseo")
    assert s["is_estimated"] is False
    assert s["avg_monthly"] == 0
