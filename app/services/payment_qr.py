"""VietQR image URL helper for bank-transfer checkout (optional)."""

from __future__ import annotations

import os
from urllib.parse import quote

# BIN acquirer IDs for VietQR (img.vietqr.io).
_VIETQR_BANK_BINS: dict[str, str] = {
    "ACB": "970416",
    "VCB": "970436",
    "TCB": "970407",
    "MB": "970422",
    "BIDV": "970418",
}


def vietqr_enabled() -> bool:
    raw = (os.getenv("PAYMENT_QR_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def build_vietqr_url(
    *,
    bank_code: str,
    bank_account: str,
    amount: int,
    transfer_content: str,
    account_name: str | None = None,
) -> str | None:
    """
    Build VietQR image URL when enabled.
    Returns None if QR generation is disabled or bank is unsupported.
    """
    if not vietqr_enabled():
        return None
    code = str(bank_code or "").strip().upper()
    acq = _VIETQR_BANK_BINS.get(code)
    account = str(bank_account or "").strip()
    if not acq or not account:
        return None
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        return None
    if amt <= 0:
        return None

    template = (os.getenv("PAYMENT_VIETQR_TEMPLATE") or "compact2").strip() or "compact2"
    base = f"https://img.vietqr.io/image/{acq}-{account}-{template}.jpg"
    params = [f"amount={amt}", f"addInfo={quote(str(transfer_content or ''), safe='')}"]
    if account_name:
        params.append(f"accountName={quote(str(account_name), safe='')}")
    return base + "?" + "&".join(params)
