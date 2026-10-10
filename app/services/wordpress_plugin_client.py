"""HTTP client: SEOAuto Celery worker → WordPress SEO Helper plugin (HMAC)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

import requests

from app.services.wordpress_plugin_hmac import build_headers, normalize_path
from app.services.wordpress_plugin_retry import (
    ErrorClassification,
    classify_exception,
    classify_http_response,
    is_requests_network_error,
)

_LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = int(__import__("os").getenv("WORDPRESS_PLUGIN_HTTP_TIMEOUT", "45"))


def _parse_json_response(resp: requests.Response) -> dict[str, Any] | None:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def plugin_post_json(
    *,
    site_url: str,
    site_id: str,
    connection_id: int,
    secret: str,
    path: str,
    payload: dict[str, Any],
    request_id: str,
    timeout: int | None = None,
) -> tuple[dict[str, Any] | None, ErrorClassification | None]:
    """
    Signed POST to plugin REST. Returns (result_dict, None) on success.
    On failure returns (None, classification).
    """
    base = (site_url or "").rstrip("/") + "/"
    api_path = normalize_path(path)
    url = urljoin(base, api_path.lstrip("/"))
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = build_headers(
        site_id=site_id,
        connection_id=int(connection_id),
        secret=secret,
        method="POST",
        url_or_path=api_path,
        body=body,
        request_id=request_id,
    )
    try:
        from app.services.url_safety import validate_public_http_url

        blocked = validate_public_http_url(url)
        if blocked:
            return None, ErrorClassification(
                retryable=False,
                blocked=True,
                error_code=blocked,
                message="Site URL blocked by SSRF policy",
                http_status=0,
            )
        resp = requests.post(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=timeout or DEFAULT_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return None, classify_exception(exc)

    parsed = _parse_json_response(resp)
    if resp.status_code >= 400:
        return None, classify_http_response(
            resp.status_code,
            parsed,
            raw_text=resp.text[:2000],
            endpoint=api_path,
        )

    if parsed is None:
        return None, ErrorClassification(
            retryable=False,
            blocked=False,
            error_code="invalid_response",
            message="Plugin response is not JSON",
            http_status=resp.status_code,
        )

    return parsed, None


def plugin_get_json(
    *,
    site_url: str,
    site_id: str,
    connection_id: int,
    secret: str,
    path: str,
    request_id: str,
    timeout: int | None = None,
) -> tuple[dict[str, Any] | None, ErrorClassification | None]:
    """Signed GET to plugin REST (e.g. /wp-json/seoauto/v1/status)."""
    base = (site_url or "").rstrip("/") + "/"
    api_path = normalize_path(path)
    url = urljoin(base, api_path.lstrip("/"))
    headers = build_headers(
        site_id=site_id,
        connection_id=int(connection_id),
        secret=secret,
        method="GET",
        url_or_path=api_path,
        body="",
        request_id=request_id,
    )
    try:
        from app.services.url_safety import safe_requests_get, validate_public_http_url

        blocked = validate_public_http_url(url)
        if blocked:
            return None, ErrorClassification(
                retryable=False,
                blocked=True,
                error_code=blocked,
                message="Site URL blocked by SSRF policy",
                http_status=0,
            )
        resp = safe_requests_get(url, headers=headers, timeout=float(timeout or DEFAULT_TIMEOUT))
    except requests.RequestException as exc:
        return None, classify_exception(exc)
    except ValueError as exc:
        return None, ErrorClassification(
            retryable=False,
            blocked=True,
            error_code=str(exc),
            message="Site URL blocked by SSRF policy",
            http_status=0,
        )

    parsed = _parse_json_response(resp)
    if resp.status_code >= 400:
        return None, classify_http_response(
            resp.status_code,
            parsed,
            raw_text=resp.text[:2000],
            endpoint=api_path,
        )
    if parsed is None:
        return None, ErrorClassification(
            retryable=False,
            blocked=False,
            error_code="invalid_response",
            message="Plugin response is not JSON",
            http_status=resp.status_code,
        )
    return parsed, None


def plugin_patch_json(
    *,
    site_url: str,
    site_id: str,
    connection_id: int,
    secret: str,
    path: str,
    payload: dict[str, Any],
    request_id: str,
    timeout: int | None = None,
) -> tuple[dict[str, Any] | None, ErrorClassification | None]:
    base = (site_url or "").rstrip("/") + "/"
    api_path = normalize_path(path)
    url = urljoin(base, api_path.lstrip("/"))
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = build_headers(
        site_id=site_id,
        connection_id=int(connection_id),
        secret=secret,
        method="PATCH",
        url_or_path=api_path,
        body=body,
        request_id=request_id,
    )
    try:
        resp = requests.patch(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=timeout or DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, classify_exception(exc)

    parsed = _parse_json_response(resp)
    if resp.status_code >= 400:
        return None, classify_http_response(
            resp.status_code,
            parsed,
            raw_text=resp.text[:2000],
            endpoint=api_path,
        )
    return parsed, None
