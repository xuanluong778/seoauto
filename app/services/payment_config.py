"""Payment / SePay configuration — read from environment only (no hardcoded secrets)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

from app.core.runtime import is_production

logger = logging.getLogger(__name__)

# Public bank transfer defaults (documented in .env.example; not secrets).
_DEFAULT_BANK_CODE = "ACB"
_DEFAULT_BANK_ACCOUNT = "7982468"
_DEFAULT_BANK_HOLDER = "Cong ty TNHH The Gioi Digi"
_DEFAULT_ORDER_EXPIRE_MINUTES = 60
_HMAC_MAX_SKEW_SECONDS = 300


def _env_first(*names: str) -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return ""


def sepay_webhook_secret() -> str:
    return _env_first("SEPAY_WEBHOOK_SECRET")


def sepay_api_key() -> str:
    return _env_first("SEPAY_API_KEY", "SEPAY_WEBHOOK_API_KEY")


def sepay_auth_tokens() -> frozenset[str]:
    return frozenset(t for t in (sepay_webhook_secret(), sepay_api_key()) if t)


def is_sepay_webhook_configured() -> bool:
    return bool(sepay_auth_tokens() or sepay_webhook_secret())


def sepay_webhook_require_auth() -> bool:
    """
    Require API Key / HMAC for SePay webhooks.

    Default: True (fail-closed). Production always True — cannot be disabled.
    Non-production may set SEPAY_WEBHOOK_REQUIRE_AUTH=0 only for local unsigned tests.
    """
    if is_production():
        return True
    raw = _env_first("SEPAY_WEBHOOK_REQUIRE_AUTH")
    if raw:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return True


def _looks_like_sepay_payload(payload: dict) -> bool:
    """Minimal shape check before accepting an unsigned webhook."""
    if not isinstance(payload, dict) or not payload:
        return False
    tx_id = payload.get("id") or payload.get("transaction_id") or payload.get("sepay_transaction_id")
    if tx_id is None or str(tx_id).strip() == "":
        return False
    acct = (
        payload.get("accountNumber")
        or payload.get("account_number")
        or payload.get("subAccount")
        or payload.get("bank_account")
    )
    if not str(acct or "").strip():
        return False
    amount = payload.get("transferAmount") or payload.get("transfer_amount") or payload.get("amount")
    if amount is None:
        return False
    try:
        if int(float(str(amount).replace(",", "").strip() or 0)) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def billing_bank_code() -> str:
    return _env_first("BILLING_BANK_CODE", "PAYMENT_BANK_CODE") or _DEFAULT_BANK_CODE


def billing_bank_account() -> str:
    return _env_first("BILLING_BANK_ACCOUNT", "PAYMENT_BANK_ACCOUNT") or _DEFAULT_BANK_ACCOUNT


def billing_bank_holder() -> str:
    return _env_first("BILLING_BANK_HOLDER", "PAYMENT_BANK_HOLDER") or _DEFAULT_BANK_HOLDER


def payment_order_expire_minutes() -> int:
    raw = _env_first("PAYMENT_ORDER_EXPIRE_MINUTES")
    if not raw:
        return _DEFAULT_ORDER_EXPIRE_MINUTES
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("payment_config_invalid PAYMENT_ORDER_EXPIRE_MINUTES=%r using default", raw)
        return _DEFAULT_ORDER_EXPIRE_MINUTES


def payment_bank_details() -> dict[str, str]:
    return {
        "bank_code": billing_bank_code(),
        "bank_account": billing_bank_account(),
        "bank_holder": billing_bank_holder(),
    }


def log_payment_config_status() -> None:
    """Log payment/SePay config at startup — never log secret values."""
    if is_sepay_webhook_configured():
        logger.info(
            "payment_config_sepay_ready webhook_secret=%s api_key=%s",
            "configured" if sepay_webhook_secret() else "missing",
            "configured" if sepay_api_key() else "missing",
        )
    elif is_production():
        logger.error(
            "payment_config_sepay_missing production=true — "
            "SEPAY_WEBHOOK_SECRET and/or SEPAY_API_KEY required; webhooks will be rejected"
        )
    else:
        logger.warning(
            "payment_config_sepay_missing production=false — "
            "SEPAY_WEBHOOK_SECRET and/or SEPAY_API_KEY not set; webhooks will reject auth"
        )

    acct = billing_bank_account()
    masked_acct = (acct[:2] + "****" + acct[-2:]) if len(acct) > 4 else "****"
    logger.info(
        "payment_config_billing bank_code=%s bank_account=%s bank_holder=%r expire_minutes=%s",
        billing_bank_code(),
        masked_acct,
        billing_bank_holder(),
        payment_order_expire_minutes(),
    )


def _auth_header_token_candidates(authorization: str | None) -> list[str]:
    """
    Extract candidate tokens from Authorization.
    SePay API Key auth uses: Authorization: Apikey YOUR_API_KEY
    Also accept Bearer / Api-Key / raw token.
    """
    if not authorization or not str(authorization).strip():
        return []
    auth = str(authorization).strip()
    out: list[str] = [auth]
    lower = auth.lower()
    for prefix in ("bearer ", "apikey ", "api-key ", "api_key ", "token "):
        if lower.startswith(prefix):
            token = auth[len(prefix) :].strip()
            if token:
                out.append(token)
            break
    return out


def verify_sepay_hmac_signature(
    *,
    raw_body: bytes | str | None,
    x_sepay_signature: str | None,
    x_sepay_timestamp: str | None,
) -> bool:
    """
    SePay HMAC-SHA256:
      signed = f"{timestamp}.{raw_body}"
      header X-SePay-Signature: sha256={hex}
    """
    secret = sepay_webhook_secret()
    if not secret or not x_sepay_signature or not x_sepay_timestamp:
        return False
    try:
        ts = int(str(x_sepay_timestamp).strip())
    except (TypeError, ValueError):
        logger.warning("sepay_webhook_auth_hmac_rejected reason=bad_timestamp")
        return False
    if abs(int(time.time()) - ts) > _HMAC_MAX_SKEW_SECONDS:
        logger.warning("sepay_webhook_auth_hmac_rejected reason=timestamp_skew")
        return False

    body_bytes = raw_body if isinstance(raw_body, (bytes, bytearray)) else str(raw_body or "").encode("utf-8")
    signed = f"{ts}.".encode("utf-8") + bytes(body_bytes)
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

    sig = str(x_sepay_signature).strip()
    lower = sig.lower()
    if lower.startswith("sha256="):
        provided = sig.split("=", 1)[1].strip()
    else:
        provided = sig
    ok = hmac.compare_digest(digest, provided)
    if not ok:
        logger.warning("sepay_webhook_auth_hmac_rejected reason=signature_mismatch")
    return ok


def verify_sepay_webhook_auth(
    *,
    authorization: str | None = None,
    x_api_key: str | None = None,
    x_sepay_secret: str | None = None,
    raw_body: bytes | str | None = None,
    x_sepay_signature: str | None = None,
    x_sepay_timestamp: str | None = None,
    payload: dict | None = None,
) -> bool:
    """
    Validate SePay webhook auth (fail-closed by default):
    1) HMAC-SHA256 (X-SePay-Signature + X-SePay-Timestamp) when secret configured
    2) API Key / shared secret headers (Apikey / Bearer / X-API-Key / X-SePay-Secret)
    3) Unsigned payload only when SEPAY_WEBHOOK_REQUIRE_AUTH is explicitly off (non-production)
    """
    require_auth = sepay_webhook_require_auth()
    allowed = sepay_auth_tokens()
    hmac_secret = sepay_webhook_secret()

    if require_auth and not allowed and not hmac_secret:
        logger.error(
            "sepay_webhook_auth_rejected reason=missing_config "
            "set SEPAY_WEBHOOK_SECRET and/or SEPAY_API_KEY"
        )
        return False

    if verify_sepay_hmac_signature(
        raw_body=raw_body,
        x_sepay_signature=x_sepay_signature,
        x_sepay_timestamp=x_sepay_timestamp,
    ):
        logger.info("sepay_webhook_auth_ok method=hmac")
        return True

    candidates: list[str] = []
    if x_api_key and str(x_api_key).strip():
        candidates.append(str(x_api_key).strip())
    if x_sepay_secret and str(x_sepay_secret).strip():
        candidates.append(str(x_sepay_secret).strip())
    candidates.extend(_auth_header_token_candidates(authorization))

    if allowed:
        for token in candidates:
            if token and token in allowed:
                logger.info("sepay_webhook_auth_ok method=api_key")
                return True

    # Dev-only escape hatch: unsigned payloads when auth explicitly disabled.
    if not require_auth and payload and _looks_like_sepay_payload(payload):
        logger.info(
            "sepay_webhook_auth_ok method=unsigned_payload "
            "(non-production SEPAY_WEBHOOK_REQUIRE_AUTH=0 only)"
        )
        return True

    auth_scheme = "none"
    if authorization and str(authorization).strip():
        auth_scheme = str(authorization).strip().split(" ", 1)[0][:32]
    logger.warning(
        "sepay_webhook_auth_rejected reason=invalid_token auth_scheme=%s "
        "has_x_api_key=%s has_x_sepay_secret=%s has_hmac_headers=%s require_auth=%s",
        auth_scheme,
        bool(x_api_key),
        bool(x_sepay_secret),
        bool(x_sepay_signature and x_sepay_timestamp),
        require_auth,
    )
    return False
