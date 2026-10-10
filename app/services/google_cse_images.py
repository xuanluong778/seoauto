from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from dotenv import dotenv_values

from app.services.cost_control.executor import (
    CostControlBypassError,
    execute_guarded_external,
    guarded_requests_get,
)
from app.services.cost_control.settings import cost_control_enforced
from app.services.cost_control.types import ExternalApiProvider


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str | None]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    return dotenv_values(env_file) if env_file.exists() else {}


def _reload_env_local() -> None:
    try:
        from app.core.settings import refresh_env_local

        refresh_env_local()
    except Exception:
        pass
    _env_map.cache_clear()


def _getenv(name: str) -> str:
    return str((os.getenv(name) or _env_map().get(name) or "")).strip()


def _api_key_hint(key: str) -> str:
    k = str(key or "").strip()
    if len(k) <= 12:
        return "(chưa cấu hình)"
    return f"{k[:8]}...{k[-4:]}"


def infer_gcp_project_number_from_oauth() -> str:
    """Số project GCP từ GOOGLE_CLIENT_ID (phần trước dấu -)."""
    cid = _getenv("GOOGLE_CLIENT_ID")
    m = re.match(r"^(\d{8,})", cid)
    return m.group(1) if m else ""


def _gcp_console_urls(project_number: str) -> dict[str, str]:
    pn = str(project_number or "").strip()
    q = f"?project={pn}" if pn else ""
    return {
        "enable_custom_search_api": (
            "https://console.cloud.google.com/apis/library/customsearch.googleapis.com" + q
        ),
        "credentials": "https://console.cloud.google.com/apis/credentials" + q,
        "enabled_apis": "https://console.cloud.google.com/apis/dashboard" + q,
    }


def normalize_google_api_key(raw: str = "") -> str:
    key = str(raw or "").strip().strip('"').strip("'")
    return key


def normalize_google_cse_id(raw: str = "") -> str:
    """env.local hay bị dính dấu chấm cuối (vd. 24e955cc4951c417e.) → Google trả 400 invalid argument."""
    cx = str(raw or "").strip().strip('"').strip("'")
    cx = cx.rstrip(".,;:")
    if re.fullmatch(r"[a-zA-Z0-9_-]{8,40}", cx):
        return cx
    m = re.search(r"([a-fA-F0-9]{16,24})", cx)
    if m:
        return m.group(1)
    return cx


def _google_credentials() -> tuple[str, str]:
    _reload_env_local()
    api_key = normalize_google_api_key(_getenv("GOOGLE_CSE_API_KEY") or _getenv("GOOGLE_API_KEY"))
    cx = normalize_google_cse_id(
        _getenv("GOOGLE_CSE_ID")
        or _getenv("GOOGLE_SEARCH_ENGINE_ID")
        or _getenv("GOOGLE_CSE_CX")
    )
    if not api_key or not cx:
        raise ValueError(
            "Thiếu GOOGLE_API_KEY / GOOGLE_CSE_ID trong env.local. "
            "Kiểm tra GOOGLE_CSE_ID không có dấu chấm thừa ở cuối."
        )
    return api_key, cx


def _parse_google_cse_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error") or {}
        msg = str(err.get("message") or "").strip()
        if resp.status_code == 403:
            pn = infer_gcp_project_number_from_oauth()
            urls = _gcp_console_urls(pn)
            base = (
                "API key trong env.local KHÔNG thuộc project đã bật Custom Search API "
                "(hay bật nhầm project khác trên Google Cloud). "
            )
            if pn:
                base += (
                    f"OAuth app của bạn dùng project số {pn}. "
                    f"Bật API tại: {urls['enable_custom_search_api']} → Enable. "
                    f"Tạo API key MỚI tại: {urls['credentials']} → Create credentials → API key, "
                    f"dán vào GOOGLE_CSE_API_KEY (hoặc thay GOOGLE_API_KEY) trong env.local, rồi restart run.bat. "
                )
            else:
                base += (
                    "Vào Credentials → mở API key đang dùng → xem project → bật Custom Search API "
                    "trong ĐÚNG project đó. "
                )
            if "does not have the access" in msg.lower():
                base += (
                    "Lưu ý: programmablesearchengine.google.com chỉ cấu hình CSE; "
                    "bật API phải làm trên Google Cloud Console, không phải trang CSE."
                )
            return base
        if resp.status_code == 400 and "invalid argument" in msg.lower():
            return (
                "Tham số Google CSE không hợp lệ — thường do GOOGLE_CSE_ID sai (dấu chấm thừa cuối dòng) "
                "hoặc Search Engine chưa bật «Image search» tại programmablesearchengine.google.com."
            )
        if msg:
            return f"Google CSE HTTP {resp.status_code}: {msg}"
    except Exception:
        pass
    return f"Google CSE HTTP {resp.status_code}: {(resp.text or '')[:280]}"


def _cse_image_request(*, api_key: str, cx: str, q: str, num: int, extra: dict[str, Any]) -> requests.Response:
    params: dict[str, Any] = {
        "key": api_key,
        "cx": cx,
        "q": q,
        "searchType": "image",
        "num": num,
    }
    params.update(extra)

    def _call() -> requests.Response:
        if cost_control_enforced():
            return guarded_requests_get(
                ExternalApiProvider.GOOGLE_CSE,
                "image_search",
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=25,
            )
        return requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=25)

    try:
        return execute_guarded_external(ExternalApiProvider.GOOGLE_CSE, "image_search", _call)
    except CostControlBypassError as exc:
        raise ValueError("Google CSE image search blocked by cost control.") from exc


def google_cse_probe(*, test_query: str = "technology") -> dict[str, Any]:
    """Kiểm tra nhanh GOOGLE_API_KEY + GOOGLE_CSE_ID (dùng cho debug)."""
    _reload_env_local()
    try:
        api_key, cx = _google_credentials()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    pn = infer_gcp_project_number_from_oauth()
    urls = _gcp_console_urls(pn)
    qq = re.sub(r"\s+", " ", (test_query or "technology").strip())[:80] or "technology"
    try:
        r = _cse_image_request(api_key=api_key, cx=cx, q=qq, num=1, extra={})
    except Exception as exc:
        return {
            "ok": False,
            "cx": cx,
            "api_key_hint": _api_key_hint(api_key),
            "uses_key": "GOOGLE_CSE_API_KEY" if _getenv("GOOGLE_CSE_API_KEY") else "GOOGLE_API_KEY",
            "oauth_project_number": pn or None,
            "console_urls": urls,
            "error": f"Request failed: {exc}",
        }
    out: dict[str, Any] = {
        "ok": r.status_code == 200,
        "http_status": r.status_code,
        "cx": cx,
        "api_key_hint": _api_key_hint(api_key),
        "uses_key": "GOOGLE_CSE_API_KEY" if _getenv("GOOGLE_CSE_API_KEY") else "GOOGLE_API_KEY",
        "oauth_project_number": pn or None,
        "console_urls": urls,
        "test_query": qq,
    }
    if r.status_code == 200:
        data = r.json() if r.content else {}
        out["items_found"] = len(data.get("items") or [])
        return out
    try:
        body = r.json()
        out["google_error"] = (body.get("error") or {}).get("message")
    except Exception:
        out["google_error"] = (r.text or "")[:200]
    out["error"] = _parse_google_cse_error(r)
    return out


def google_cse_image_search(*, q: str, num: int = 8) -> list[dict[str, Any]]:
    api_key, cx = _google_credentials()
    qq = re.sub(r"\s+", " ", (q or "").strip())
    if not qq:
        return []
    if len(qq) > 200:
        qq = qq[:200].rsplit(" ", 1)[0] or qq[:200]
    n = max(1, min(int(num or 8), 10))

    attempts: list[dict[str, Any]] = [
        {"safe": "active"},
        {},
    ]
    last_err = ""
    data: dict[str, Any] = {}
    for extra in attempts:
        try:
            r = _cse_image_request(api_key=api_key, cx=cx, q=qq, num=n, extra=extra)
        except Exception as exc:
            last_err = f"Google CSE request failed: {exc}"
            continue
        if r.status_code == 200:
            data = r.json() if r.content else {}
            break
        last_err = _parse_google_cse_error(r)
        if r.status_code != 400:
            break
    else:
        raise ValueError(last_err or "Google CSE image search failed.")

    if not data and last_err:
        raise ValueError(last_err)

    out: list[dict[str, Any]] = []
    for it in (data.get("items") or [])[:n]:
        link = str(it.get("link") or "").strip()
        title = str(it.get("title") or "").strip()
        image = it.get("image") or {}
        thumb = str(image.get("thumbnailLink") or "").strip()
        ctx = str(image.get("contextLink") or it.get("displayLink") or "").strip()
        if not link:
            continue
        out.append(
            {
                "link": link,
                "title": title,
                "thumbnail": thumb or link,
                "context": ctx,
            }
        )
    return out


def _sniff_image_ext(data: bytes) -> str | None:
    """Detect image format from magic bytes (ignore broken/missing Content-Type)."""
    if not data or len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    # JPEG SOI may appear later in rare truncated proxy wraps
    if b"\xff\xd8\xff" in data[:64]:
        return ".jpg"
    return None


def import_remote_image_url(
    src: str,
    *,
    stem: str = "google-image",
    user_id: int | None = None,
    project_id: str | None = None,
) -> str:
    """Download a remote image to server storage; returns app-relative URL path."""
    url = str(src or "").strip()
    if not url or not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL ảnh không hợp lệ.")
    from urllib.parse import urlparse

    from app.services.url_safety import safe_http_get_bytes, validate_public_http_url

    blocked = validate_public_http_url(url)
    if blocked:
        raise ValueError(f"URL ảnh không an toàn ({blocked}).")

    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
    header_variants = [
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer or "https://www.google.com/",
        },
    ]

    data = b""
    err: str | None = "fetch_error"
    meta: dict[str, Any] = {}
    last_err = ""
    for headers in header_variants:
        data, err, meta = safe_http_get_bytes(
            url,
            timeout_s=30,
            max_bytes=8 * 1024 * 1024,
            headers=headers,
        )
        if not err and data:
            break
        last_err = err or "empty_body"
        data = b""

    if err or not data:
        raise ValueError(f"Không tải được ảnh: {last_err or err or 'empty'}")

    ctype = str((meta or {}).get("content_type") or "").split(";")[0].strip().lower()
    sniff = _sniff_image_ext(data)
    if not sniff and "image" not in ctype and not re.search(
        r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.I
    ):
        # Some hosts return octet-stream / empty type; reject only if neither sniff nor type is image.
        raise ValueError(
            f"URL không trả về ảnh (content-type={ctype or 'unknown'}, size={len(data)})."
        )
    if not sniff and "image" not in ctype:
        # URL ends with image extension but body may still be HTML block page
        if data[:200].lstrip().lower().startswith((b"<!doctype", b"<html", b"<head")):
            raise ValueError("Máy chủ chặn hotlink — không tải được file ảnh.")
        raise ValueError("Nội dung tải về không phải file ảnh hợp lệ.")

    if len(data) < 400:
        raise ValueError("File ảnh tải về quá nhỏ hoặc không hợp lệ.")

    ext = sniff or ".jpg"
    if not sniff:
        if "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        elif "gif" in ctype:
            ext = ".gif"
        elif "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
        elif re.search(r"\.png(\?|$)", url, re.I):
            ext = ".png"
        elif re.search(r"\.webp(\?|$)", url, re.I):
            ext = ".webp"
        elif re.search(r"\.gif(\?|$)", url, re.I):
            ext = ".gif"

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "google-image"

    # Prefer private user storage when authenticated (matches AI studio previews).
    if user_id is not None and int(user_id) > 0:
        try:
            from app.services.media_storage import save_private_image

            saved = save_private_image(
                user_id=int(user_id),
                data=data,
                suffix=ext,
                stem=safe_stem,
                project_id=project_id,
            )
            if saved and saved.get("url"):
                return str(saved["url"])
        except Exception:
            pass

    target_name = f"{safe_stem}-{uuid4().hex[:8]}{ext}"
    target_dir = Path("static") / "uploads" / "content-ai"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / target_name).write_bytes(data)
    return f"/static/uploads/content-ai/{target_name}"
