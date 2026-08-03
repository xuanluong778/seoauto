"""Content AI image generation via OpenRouter Image API (single provider for all flows)."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values

_LOG = logging.getLogger(__name__)

OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"

# Allowed models (UI + server validation).
OPENROUTER_IMAGE_MODELS: list[dict[str, str]] = [
    {"id": "google/gemini-3.1-flash-lite-image", "label_vi": "Gemini 3.1 Flash Lite Image"},
    {"id": "google/gemini-3.1-flash-image", "label_vi": "Gemini 3.1 Flash Image"},
    {"id": "google/gemini-2.5-flash-image", "label_vi": "Gemini 2.5 Flash Image"},
    {"id": "google/gemini-3-pro-image", "label_vi": "Gemini 3 Pro Image"},
    {"id": "google/gemini-3-pro-image-preview", "label_vi": "Gemini 3 Pro Image (Preview)"},
    {"id": "bytedance-seed/seedream-4.5", "label_vi": "Seedream 4.5"},
    {"id": "openai/gpt-image-2", "label_vi": "GPT Image 2"},
    {"id": "openai/gpt-5.4-image-2", "label_vi": "GPT 5.4 Image 2"},
    {"id": "x-ai/grok-imagine-image-quality", "label_vi": "Grok Imagine Image Quality"},
]

_ALLOWED_MODEL_IDS = frozenset(m["id"] for m in OPENROUTER_IMAGE_MODELS)
_DEFAULT_MODEL = "google/gemini-2.5-flash-image"


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str | None]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    return dotenv_values(env_file) if env_file.exists() else {}


def _getenv(name: str, default: str = "") -> str:
    return str((os.getenv(name) or _env_map().get(name) or default)).strip()


def default_image_model() -> str:
    raw = _getenv("OPENROUTER_IMAGE_MODEL", _DEFAULT_MODEL)
    return raw if raw in _ALLOWED_MODEL_IDS else _DEFAULT_MODEL


def normalize_image_model(model: str | None) -> str:
    m = str(model or "").strip()
    if m in _ALLOWED_MODEL_IDS:
        return m
    env_default = default_image_model()
    if m and m not in _ALLOWED_MODEL_IDS:
        raise ValueError(
            f"Model ảnh «{m}» không được hỗ trợ. "
            f"Chọn một trong: {', '.join(sorted(_ALLOWED_MODEL_IDS))}."
        )
    return env_default


def openrouter_image_headers() -> dict[str, str]:
    api_key = _getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "Thiếu OPENROUTER_API_KEY trong env.local. "
            "Thêm khóa OpenRouter để dùng tạo ảnh AI."
        )
    site = (_getenv("APP_BASE_URL") or "https://seoauto.vn").strip().rstrip("/")
    title = _getenv("OPENROUTER_APP_TITLE") or "SEOAuto"
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": site,
        "X-Title": title,
    }


def aspect_ratio_for_openrouter(aspect_ratio: str) -> str:
    ar = str(aspect_ratio or "16:9").strip().lower()
    if ar in ("1:1", "square"):
        return "1:1"
    if ar in ("9:16", "portrait", "vertical"):
        return "9:16"
    if ar in ("4:3", "4x3"):
        return "4:3"
    if ar in ("3:4",):
        return "3:4"
    if ar in ("3:2",):
        return "3:2"
    if ar in ("2:3",):
        return "2:3"
    if re.fullmatch(r"\d{2,4}x\d{2,4}", ar):
        return ar
    return "16:9"


def _parse_error_payload(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return err
        return data
    return {}


def format_openrouter_image_error(
    *,
    status_code: int,
    body: str,
    model: str = "",
) -> str:
    """Human-readable Vietnamese error for UI/logs."""
    err = _parse_error_payload(body)
    code = str(err.get("code") or err.get("type") or "").strip()
    msg = str(err.get("message") or err.get("detail") or "").strip()
    low = (body or "").lower()

    if status_code == 401 or "invalid api key" in low or "unauthorized" in low:
        return "OpenRouter từ chối (401): API key không hợp lệ hoặc thiếu OPENROUTER_API_KEY."
    if status_code == 403:
        return f"OpenRouter từ chối (403): không có quyền dùng model «{model or 'ảnh'}»."
    if status_code == 429 or "rate limit" in low or "quota" in low:
        return "OpenRouter hết quota / rate limit (429). Thử lại sau hoặc đổi model ảnh."
    if status_code == 400:
        hint = msg or (body or "")[:240]
        if "model" in low and ("not found" in low or "unsupported" in low or "does not support" in low):
            return (
                f"Model «{model}» không hỗ trợ tạo ảnh trên OpenRouter. "
                f"Chọn model khác trong tab Tùy chỉnh. Chi tiết: {hint}"
            )
        return f"OpenRouter payload sai (400): {hint}"
    if status_code == 404:
        return f"Model «{model}» không tồn tại trên OpenRouter (404)."
    if status_code >= 500:
        return f"OpenRouter lỗi máy chủ (HTTP {status_code}). Thử lại sau."
    if msg:
        return f"OpenRouter lỗi HTTP {status_code}: {msg}"
    if code:
        return f"OpenRouter lỗi HTTP {status_code} ({code})."
    return f"OpenRouter lỗi HTTP {status_code}: {(body or '')[:240]}"


def _extract_image_bytes(item: dict[str, Any]) -> bytes | None:
    b64 = str(item.get("b64_json") or "").strip()
    if b64:
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError):
            return None
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    try:
        img = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        raise ValueError(f"Không tải ảnh từ OpenRouter URL: {exc}") from exc
    if img.status_code != 200:
        raise ValueError(f"Không tải ảnh từ OpenRouter (HTTP {img.status_code}).")
    return img.content


def generate_images_batch(
    *,
    prompt: str,
    model: str | None = None,
    aspect_ratio: str = "16:9",
    custom_width: int | None = None,
    custom_height: int | None = None,
    size: str | None = None,
    n: int = 1,
    resolution: str = "1K",
    timeout: float = 150,
) -> list[bytes]:
    """
    Call OpenRouter POST /api/v1/images and return raw image bytes.
    Raises ValueError with clear message on failure.
    """
    p = str(prompt or "").strip()
    if not p:
        raise ValueError("Prompt ảnh trống.")
    model_id = normalize_image_model(model)
    count = max(1, min(int(n or 1), 4))

    body: dict[str, Any] = {
        "model": model_id,
        "prompt": p[:3900],
        "n": count,
    }
    ar = aspect_ratio_for_openrouter(aspect_ratio)
    if re.fullmatch(r"\d{2,4}x\d{2,4}", ar):
        body["size"] = ar
    elif str(aspect_ratio or "").strip().lower() in ("custom", "tu_chinh", "tùy chỉnh") and custom_width and custom_height:
        w = max(256, min(int(custom_width), 2048))
        h = max(256, min(int(custom_height), 2048))
        body["size"] = f"{w}x{h}"
    else:
        body["aspect_ratio"] = ar
        body["resolution"] = str(size or resolution or "1K").strip() or "1K"

    headers = openrouter_image_headers()
    _LOG.info(
        "openrouter_image_generate model=%s aspect=%s n=%d prompt_len=%d",
        model_id,
        body.get("aspect_ratio") or body.get("size"),
        count,
        len(p),
    )
    try:
        resp = requests.post(
            OPENROUTER_IMAGES_URL,
            headers=headers,
            json=body,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        _LOG.warning("openrouter_image timeout model=%s", model_id)
        raise ValueError("OpenRouter timeout — máy chủ không trả lời kịp. Thử lại hoặc đổi model.") from exc
    except requests.RequestException as exc:
        _LOG.warning("openrouter_image connect failed model=%s err=%s", model_id, exc)
        raise ValueError(f"Không kết nối được OpenRouter Images: {exc}") from exc

    raw = resp.text or ""
    if resp.status_code != 200:
        detail = format_openrouter_image_error(status_code=resp.status_code, body=raw, model=model_id)
        _LOG.warning(
            "openrouter_image failed http=%s model=%s body=%s",
            resp.status_code,
            model_id,
            raw[:500],
        )
        raise ValueError(detail)

    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError(f"OpenRouter trả JSON không hợp lệ: {raw[:200]}") from exc

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("OpenRouter không trả về ảnh (data rỗng).")

    out: list[bytes] = []
    for item in items[:count]:
        if not isinstance(item, dict):
            continue
        blob = _extract_image_bytes(item)
        if blob:
            out.append(blob)
    if not out:
        raise ValueError("OpenRouter không có dữ liệu ảnh hợp lệ (b64_json/url trống).")
    return out


def generate_image_bytes(
    *,
    prompt: str,
    model: str | None = None,
    aspect_ratio: str = "16:9",
    custom_width: int | None = None,
    custom_height: int | None = None,
    size: str | None = None,
) -> bytes:
    return generate_images_batch(
        prompt=prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        custom_width=custom_width,
        custom_height=custom_height,
        size=size,
        n=1,
    )[0]


def generate_image_variants(
    *,
    prompts: list[str],
    aspect_ratio: str = "16:9",
    stem: str = "studio",
    model: str | None = None,
    custom_width: int | None = None,
    custom_height: int | None = None,
    size: str | None = None,
    user_id: int | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generate one image per prompt; returns [{url, prompt, index, model}, ...]."""
    model_id = normalize_image_model(model)
    ar_label = str(aspect_ratio or "16:9")
    if custom_width and custom_height:
        ar_label = f"{custom_width}x{custom_height}"

    results: list[dict[str, Any]] = []
    for i, prompt in enumerate(prompts):
        p = str(prompt or "").strip()
        if not p:
            continue
        blobs = generate_images_batch(
            prompt=p,
            model=model_id,
            aspect_ratio=aspect_ratio,
            custom_width=custom_width,
            custom_height=custom_height,
            size=size,
            n=1,
        )
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "studio"
        url = _save_generated_image_bytes(
            blobs[0],
            stem=f"{safe_stem}-v{i + 1}",
            user_id=user_id,
            project_id=project_id,
        )
        results.append(
            {
                "url": url,
                "prompt": p,
                "index": i,
                "aspect_label": ar_label,
                "model": model_id,
            }
        )
    if not results:
        raise ValueError("Không tạo được ảnh preview — kiểm tra prompt và model ảnh OpenRouter.")
    return results


def _save_generated_image_bytes(
    data: bytes,
    *,
    stem: str = "ai-img",
    user_id: int | None = None,
    project_id: str | None = None,
) -> str:
    if user_id is not None and int(user_id) > 0:
        from app.services.media_storage import save_private_image

        saved = save_private_image(
            user_id=int(user_id),
            data=data,
            stem=stem,
            project_id=project_id,
        )
        return saved["url"]
    from app.services.media_storage import save_public_published_image

    return save_public_published_image(data=data).get("url", "")
