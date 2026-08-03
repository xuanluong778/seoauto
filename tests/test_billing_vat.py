"""Tests for billing VAT helpers."""

from app.services.billing_vat import billing_vat_note, billing_vat_percent, payment_amount_breakdown, price_with_vat


def test_payment_amount_breakdown():
    row = payment_amount_breakdown(399_000)
    assert row["base_amount"] == 399_000
    assert row["vat_amount"] == 39_900
    assert row["amount"] == 438_900


def test_price_with_vat_10_percent():
    assert price_with_vat(399_000) == 438_900
    assert price_with_vat(100_000) == 110_000
    assert price_with_vat(0) == 0
    assert price_with_vat(None) is None


def test_billing_vat_note():
    assert "10%" in billing_vat_note()
    assert billing_vat_percent() == 10
