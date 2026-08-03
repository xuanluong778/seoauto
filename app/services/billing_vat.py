"""Billing VAT — applied to customer-facing prices and payment order amounts."""

from __future__ import annotations

import os

_DEFAULT_VAT_PERCENT = 10


def billing_vat_percent() -> int:
    raw = (os.getenv("BILLING_VAT_PERCENT") or str(_DEFAULT_VAT_PERCENT)).strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_VAT_PERCENT


def billing_vat_rate() -> float:
    return billing_vat_percent() / 100.0


def vat_amount_from_base(base: int) -> int:
    """VAT portion for a pre-tax base price (rounded to VND)."""
    if base <= 0:
        return 0
    pct = billing_vat_percent()
    if pct <= 0:
        return 0
    return int(round(int(base) * pct / 100.0))


def payment_amount_breakdown(base: int) -> dict[str, int]:
    """Split catalog base price into subtotal, VAT, and transfer total."""
    base_int = max(0, int(base))
    vat = vat_amount_from_base(base_int)
    total = base_int + vat
    return {
        "base_amount": base_int,
        "vat_amount": vat,
        "amount": total,
        "vat_percent": billing_vat_percent(),
    }


def price_with_vat(base: int | None) -> int | None:
    """Return base price + VAT (rounded to VND). None stays None."""
    if base is None:
        return None
    if base <= 0:
        return base
    pct = billing_vat_percent()
    if pct <= 0:
        return int(base)
    return int(round(int(base) * (1 + pct / 100.0)))


def billing_vat_note() -> str:
    pct = billing_vat_percent()
    if pct <= 0:
        return ""
    return f"Đã bao gồm VAT {pct}%"
