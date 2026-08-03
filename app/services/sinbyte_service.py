"""Sinbyte third-party indexing API client."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.services.platform_integration_store import (
    PROVIDER_SINBYTE,
    get_decrypted_api_key,
    mask_api_key,
    record_test_result,
)

logger = logging.getLogger(__name__)

SINBYTE_API_BASE = (os.getenv("SINBYTE_API_BASE") or "https://app.sinbyte.com/api/indexing/").strip()
DEFAULT_TIMEOUT = float(os.getenv("SINBYTE_API_TIMEOUT", "25") or "25")
_KEY_IN_TEXT_RE = re.compile(r"(apikey|api_key|token|secret)[\"'\s:=]+[A-Za-z0-9\-_]{8,}", re.I)


def _sanitize_text(text: str) -> str:
    s = str(text or "")
    if not s:
        return ""
    s = _KEY_IN_TEXT_RE.sub(r"\1=***", s)
    return s[:500]


def resolve_api_key(db: Session) -> str | None:
    return get_decrypted_api_key(db, PROVIDER_SINBYTE)


def test_connection(db: Session, *, api_key: str | None = None) -> dict[str, Any]:
    key = (api_key or "").strip() or resolve_api_key(db)
    if not key:
        return {
            "ok": False,
            "connected": False,
            "message": "Chưa cấu hình API key Sinbyte.",
        }

    try:
        resp = requests.get(
            SINBYTE_API_BASE,
            params={"apikey": key},
            headers={"Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            msg = "API key không hợp lệ hoặc bị từ chối."
            record_test_result(db, provider=PROVIDER_SINBYTE, ok=False, message=msg)
            return {"ok": False, "connected": False, "message": msg, "http_status": resp.status_code}

        if resp.status_code >= 500:
            msg = "Sinbyte tạm thời không phản hồi — thử lại sau."
            record_test_result(db, provider=PROVIDER_SINBYTE, ok=False, message=msg)
            return {"ok": False, "connected": False, "message": msg, "http_status": resp.status_code}

        if resp.status_code >= 400:
            msg = "Không kết nối được Sinbyte — kiểm tra API key."
            record_test_result(db, provider=PROVIDER_SINBYTE, ok=False, message=msg)
            return {"ok": False, "connected": False, "message": msg, "http_status": resp.status_code}

        data: Any = None
        try:
            data = resp.json()
        except ValueError:
            data = None

        msg = "Kết nối Sinbyte thành công."
        if isinstance(data, dict) and data.get("message"):
            msg = _sanitize_text(str(data.get("message")))

        record_test_result(db, provider=PROVIDER_SINBYTE, ok=True, message=msg)
        return {
            "ok": True,
            "connected": True,
            "message": msg,
            "http_status": resp.status_code,
            "api_key_masked": mask_api_key(key),
        }
    except requests.Timeout:
        msg = "Hết thời gian chờ khi kết nối Sinbyte."
        record_test_result(db, provider=PROVIDER_SINBYTE, ok=False, message=msg)
        return {"ok": False, "connected": False, "message": msg}
    except requests.RequestException as exc:
        msg = "Lỗi mạng khi kết nối Sinbyte."
        logger.warning("sinbyte_test_failed: %s", type(exc).__name__)
        record_test_result(db, provider=PROVIDER_SINBYTE, ok=False, message=msg)
        return {"ok": False, "connected": False, "message": msg}


def submit_urls(
    db: Session,
    *,
    urls: list[str],
    name: str = "SEOAuto Submit",
    dripfeed: int = 1,
    api_key: str | None = None,
) -> dict[str, Any]:
    key = (api_key or "").strip() or resolve_api_key(db)
    if not key:
        return {
            "ok": False,
            "error": "missing_api_key",
            "message": "Chưa cấu hình API key Sinbyte.",
        }

    clean_urls = [u.strip() for u in urls if u and u.strip()]
    if not clean_urls:
        return {"ok": False, "error": "empty_urls", "message": "Danh sách URL trống."}

    payload = {
        "apikey": key,
        "name": (name or "SEOAuto Submit")[:120],
        "dripfeed": int(dripfeed) if int(dripfeed) >= 0 else 1,
        "urls": clean_urls[:100],
    }

    try:
        resp = requests.post(
            SINBYTE_API_BASE,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=DEFAULT_TIMEOUT,
        )
        body: Any = None
        try:
            body = resp.json()
        except ValueError:
            body = None

        ok = 200 <= resp.status_code < 300
        message = "Đã gửi URL tới Sinbyte."
        if isinstance(body, dict):
            if body.get("message"):
                message = _sanitize_text(str(body.get("message")))
            elif body.get("error"):
                message = _sanitize_text(str(body.get("error")))

        if not ok:
            logger.warning("sinbyte_submit_failed status=%s", resp.status_code)
            return {
                "ok": False,
                "error": "sinbyte_error",
                "message": message or "Sinbyte từ chối yêu cầu submit.",
                "http_status": resp.status_code,
            }

        return {
            "ok": True,
            "message": message,
            "http_status": resp.status_code,
            "submitted_count": len(clean_urls),
            "response": body if isinstance(body, dict) else None,
        }
    except requests.Timeout:
        return {"ok": False, "error": "timeout", "message": "Hết thời gian chờ khi gửi Sinbyte."}
    except requests.RequestException as exc:
        logger.warning("sinbyte_submit_network: %s", type(exc).__name__)
        return {"ok": False, "error": "network", "message": "Lỗi mạng khi gửi Sinbyte."}
