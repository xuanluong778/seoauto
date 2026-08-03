"""Tests for hybrid SaaS pricing defaults."""

from __future__ import annotations

from app.services.saas_hybrid_pricing import (
    HYBRID_PLAN_DEFAULTS,
    PLAN_MONTHLY_BONUS_CREDITS,
    build_billing_saas_products,
    yearly_price,
)


def test_hybrid_monthly_prices():
    assert HYBRID_PLAN_DEFAULTS["starter"]["month_price"] == 399_000
    assert HYBRID_PLAN_DEFAULTS["pro"]["month_price"] == 799_000
    assert HYBRID_PLAN_DEFAULTS["agency"]["month_price"] == 1_690_000
    assert HYBRID_PLAN_DEFAULTS["business"]["month_price"] == 3_490_000


def test_hybrid_credits_per_month():
    assert PLAN_MONTHLY_BONUS_CREDITS["starter"] == 500
    assert PLAN_MONTHLY_BONUS_CREDITS["pro"] == 2_500
    assert PLAN_MONTHLY_BONUS_CREDITS["agency"] == 7_000
    assert PLAN_MONTHLY_BONUS_CREDITS["business"] == 18_000


def test_yearly_is_ten_months():
    assert yearly_price(399_000) == 3_990_000
    assert yearly_price(799_000) == 7_990_000


def test_billing_products_keep_sepay_codes():
    products = build_billing_saas_products()
    codes = {p["product_code"] for p in products}
    assert "PRO_M" in codes
    assert "STARTER_Y" in codes
    pro_m = next(p for p in products if p["product_code"] == "PRO_M")
    assert pro_m["price"] == 799_000
    pro_y = next(p for p in products if p["product_code"] == "PRO_Y")
    assert pro_y["price"] == 7_990_000
