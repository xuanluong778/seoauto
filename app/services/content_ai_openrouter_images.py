"""Content AI image generation via OpenRouter (Gemini Nano Banana models).

Uses OpenRouter Chat Completions with modalities=["image","text"] — the documented
path for Gemini image models. Legacy POST /api/v1/images is used only as fallback.
"""

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

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"  # legacy fallback

# Nano Banana catalog (UI + server validation + per-image credit).
# Labels kept short for selector; credits are per successfully generated image.
OPENROUTER_IMAGE_MODELS: list[dict[str, Any]] = [
    {
        "id": "google/gemini-2.5-flash-image",
        "label_vi": "Nano Banana gốc (2.5 Flash)",
        "credits_per_image": 52,
    },
    {
        "id": "google/gemini-3.1-flash-image-preview",
        "label_vi": "Nano Banana 2 (3.1 Flash Preview)",
        "credits_per_image": 53,
    },
    {
        "id": "google/gemini-3.1-flash-lite-image",
        "label_vi": "Nano Banana 2 Lite (3.1 Lite)",
        "credits_per_image": 50,
    },
    {
        "id": "google/gemini-3-pro-image",
        "label_vi": "Nano Banana Pro (3 Pro)",
        "credits_per_image": 55,
    },
]

# Aliases → canonical catalog id
_MODEL_ALIASES: dict[str, str] = {
    "google/gemini-3.1-flash-image": "google/gemini-3.1-flash-image-preview",
    "google/gemini-3-pro-image-preview": "google/gemini-3-pro-image",
    "nano-banana": "google/gemini-2.5-flash-image",
    "nano-banana-2": "google/gemini-3.1-flash-image-preview",
    "nano-banana-2-lite": "google/gemini-3.1-flash-lite-image",
    "nano-banana-pro": "google/gemini-3-pro-image",
}

_ALLOWED_MODEL_IDS = frozenset(m["id"] for m in OPENROUTER_IMAGE_MODELS)
_DEFAULT_MODEL = "google/gemini-2.5-flash-image"
_CREDITS_BY_MODEL = {str(m["id"]): int(m["credits_per_image"]) for m in OPENROUTER_IMAGE_MODELS}

_DATA_URL_RE = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)


@lru_cache(maxsize=1)
def _env_map() -> dict[str, str | None]:
    roots = [
        Path(__file__).resolve().parents[2] / "env.local",
        Path("/var/www/seoauto_vn_usr/data/www/shared/env.local"),
    ]
    merged: dict[str, str | None] = {}
    for env_file in roots:
        if env_file.is_file() or env_file.is_symlink():
            try:
                merged.update(dotenv_values(env_file) or {})
            except Exception:
                continue
    return merged


def _getenv(name: str, default: str = "") -> str:
    return str((os.getenv(name) or _env_map().get(name) or default)).strip()


def credits_per_image(model: str | None) -> int:
    mid = normalize_image_model(model)
    catalog = int(_CREDITS_BY_MODEL.get(mid) or 0)
    if catalog >= 50:
        return max(50, min(55, catalog))
    try:
        from app.services.credit_cost_registry import resolve_credit_cost

        base = int(resolve_credit_cost("content_ai", "ai_image") or 52)
    except Exception:
        base = 52
    return max(50, min(55, base))


def credit_cost_for_images(*, model: str | None, count: int) -> int:
    n = max(0, int(count or 0))
    return credits_per_image(model) * n


def default_image_model() -> str:
    raw = _getenv("OPENROUTER_IMAGE_MODEL", _DEFAULT_MODEL)
    raw = _MODEL_ALIASES.get(raw, raw)
    return raw if raw in _ALLOWED_MODEL_IDS else _DEFAULT_MODEL


def normalize_image_model(model: str | None) -> str:
    m = str(model or "").strip()
    m = _MODEL_ALIASES.get(m, m)
    if m in _ALLOWED_MODEL_IDS:
        return m
    env_default = default_image_model()
    if m and m not in _ALLOWED_MODEL_IDS:
        raise ValueError(
            f"Model ảnh «{m}» không được hỗ trợ. "
            f"Chọn Nano Banana: {', '.join(sorted(_ALLOWED_MODEL_IDS))}."
        )
    return env_default


def resolve_openrouter_api_key() -> str:
    """Env first, then OpenRouter key from admin/platform API key pool if available."""
    key = _getenv("OPENROUTER_API_KEY")
    if key:
        return key
    # Explicit platform env aliases
    for name in ("OPENROUTER_KEY", "SEOAUTO_OPENROUTER_API_KEY"):
        key = _getenv(name)
        if key:
            return key
    try:
        from app.services.llm_content_writer import load_llm_config_admin

        cfg = load_llm_config_admin()
        if cfg and str(getattr(cfg, "api_key", "") or "").strip():
            base = str(getattr(cfg, "api_base_url", "") or "")
            logical = str(getattr(cfg, "logical_provider", "") or "").lower()
            provider = str(getattr(cfg, "provider", "") or "").lower()
            if "openrouter" in base.lower() or logical == "openrouter" or provider == "openrouter":
                return str(cfg.api_key).strip()
    except Exception:
        _LOG.debug("openrouter key pool fallback failed", exc_info=True)
    # Admin user_id=1 keys (common bootstrap) — openrouter provider only
    try:
        from app.services.api_keys_store import list_enabled_keys_for_user

        for uid in (1,):
            for row in list_enabled_keys_for_user(uid) or []:
                if str(row.get("provider") or "").lower() != "openrouter":
                    continue
                k = str(row.get("api_key") or row.get("key") or "").strip()
                if k:
                    return k
    except Exception:
        pass
    # Request-scoped user openrouter keys
    try:
        from app.core.user_context import get_request_user_id
        from app.services.api_keys_store import list_enabled_keys_for_user

        uid = get_request_user_id()
        if uid:
            for row in list_enabled_keys_for_user(int(uid)) or []:
                if str(row.get("provider") or "").lower() != "openrouter":
                    continue
                k = str(row.get("api_key") or row.get("key") or "").strip()
                if k:
                    return k
    except Exception:
        pass
    return ""


def openrouter_image_headers() -> dict[str, str]:
    api_key = resolve_openrouter_api_key()
    if not api_key:
        raise ValueError(
            "Thiếu OPENROUTER_API_KEY trong env.local (hoặc API key OpenRouter trên Settings). "
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
        # Map pixel sizes to nearest ratio for image_config
        try:
            w, h = ar.lower().split("x")
            ww, hh = int(w), int(h)
            if ww == hh:
                return "1:1"
            if abs(ww / hh - 16 / 9) < 0.15:
                return "16:9"
            if abs(ww / hh - 9 / 16) < 0.15:
                return "9:16"
            if abs(ww / hh - 4 / 3) < 0.15:
                return "4:3"
            if abs(ww / hh - 3 / 4) < 0.15:
                return "3:4"
        except Exception:
            pass
        return "16:9"
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
                f"Chọn model Nano Banana khác trong tab Tùy chỉnh. Chi tiết: {hint}"
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


def _decode_data_url(url: str) -> bytes | None:
    raw = str(url or "").strip()
    m = _DATA_URL_RE.match(raw)
    if not m:
        # bare base64
        if re.fullmatch(r"[A-Za-z0-9+/=\s]{200,}", raw):
            try:
                return base64.b64decode(raw)
            except Exception:
                return None
        return None
    try:
        return base64.b64decode(m.group(2))
    except Exception:
        return None


def _extract_image_bytes(item: dict[str, Any] | str) -> bytes | None:
    if isinstance(item, str):
        data = _decode_data_url(item)
        if data:
            return data
        if item.startswith("http"):
            return _fetch_url_bytes(item)
        return None

    if not isinstance(item, dict):
        return None

    # Common shapes
    for key in ("b64_json", "b64", "base64", "data"):
        b64 = str(item.get(key) or "").strip()
        if b64:
            try:
                if b64.startswith("data:image"):
                    decoded = _decode_data_url(b64)
                    if decoded:
                        return decoded
                return base64.b64decode(b64)
            except (ValueError, TypeError):
                continue

    # image_url: {url: data:...} or string
    for nest_key in ("image_url", "imageUrl", "image"):
        nest = item.get(nest_key)
        if isinstance(nest, str):
            data = _decode_data_url(nest)
            if data:
                return data
            if nest.startswith("http"):
                return _fetch_url_bytes(nest)
        if isinstance(nest, dict):
            url = str(nest.get("url") or nest.get("href") or "").strip()
            if url:
                data = _decode_data_url(url)
                if data:
                    return data
                if url.startswith("http"):
                    return _fetch_url_bytes(url)

    url = str(item.get("url") or "").strip()
    if url:
        data = _decode_data_url(url)
        if data:
            return data
        if url.startswith("http"):
            return _fetch_url_bytes(url)
    return None


def _fetch_url_bytes(url: str) -> bytes:
    from app.services.url_safety import safe_http_get_bytes, validate_public_http_url

    blocked = validate_public_http_url(url)
    if blocked:
        raise ValueError(f"OpenRouter image URL blocked: {blocked}")
    blob, err, _meta = safe_http_get_bytes(url, timeout_s=90, max_bytes=15 * 1024 * 1024)
    if err or not blob:
        raise ValueError(f"Không tải ảnh từ OpenRouter URL: {err or 'empty'}")
    return blob


def _parse_chat_images(data: dict[str, Any]) -> list[bytes]:
    """Extract image bytes from OpenRouter chat completions response."""
    out: list[bytes] = []
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list):
        return out
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        msg = choice.get("message") or {}
        if not isinstance(msg, dict):
            continue
        # message.images = [{type, image_url:{url: data:...}}]
        images = msg.get("images") or msg.get("image") or []
        if isinstance(images, dict):
            images = [images]
        if isinstance(images, list):
            for img in images:
                blob = _extract_image_bytes(img)
                if blob:
                    out.append(blob)
        # content parts (array of {type:image_url})
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "") in ("image_url", "image", "output_image"):
                    blob = _extract_image_bytes(part)
                    if blob:
                        out.append(blob)
                elif part.get("image_url") or part.get("b64_json"):
                    blob = _extract_image_bytes(part)
                    if blob:
                        out.append(blob)
        elif isinstance(content, str) and content.startswith("data:image"):
            blob = _decode_data_url(content)
            if blob:
                out.append(blob)
    return out


def _parse_legacy_images(data: dict[str, Any]) -> list[bytes]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[bytes] = []
    for item in items:
        blob = _extract_image_bytes(item)
        if blob:
            out.append(blob)
    return out


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
    Generate image bytes via OpenRouter chat completions (primary).
    One chat call returns typically 1 image; loop n times if needed.
    """
    p = str(prompt or "").strip()
    if not p:
        raise ValueError("Prompt ảnh trống.")
    model_id = normalize_image_model(model)
    count = max(1, min(int(n or 1), 4))
    ar = aspect_ratio_for_openrouter(aspect_ratio)
    if str(aspect_ratio or "").strip().lower() in ("custom", "tu_chinh", "tùy chỉnh") and custom_width and custom_height:
        # Prefer nearest standard ratio for Gemini image_config
        try:
            w = max(256, min(int(custom_width), 2048))
            h = max(256, min(int(custom_height), 2048))
            ar = aspect_ratio_for_openrouter(f"{w}x{h}")
        except Exception:
            pass
    res_label = str(size or resolution or "1K").strip() or "1K"
    if res_label.lower() not in ("0.5k", "1k", "2k", "4k"):
        res_label = "1K"
    else:
        res_label = res_label.upper().replace("K", "K")
        if res_label.endswith("k"):
            res_label = res_label[:-1] + "K"

    headers = openrouter_image_headers()
    out: list[bytes] = []
    last_err = ""

    for i in range(count):
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": p[:3900] if i == 0 else f"{p[:3700]}\n\nVariation {i + 1}: slightly different composition.",
                }
            ],
            "modalities": ["image", "text"],
            "stream": False,
            "image_config": {
                "aspect_ratio": ar,
            },
        }
        # Resolution when supported (3.1 flash preview etc.)
        if res_label:
            payload["image_config"]["image_size"] = res_label

        _LOG.info(
            "openrouter_image_chat model=%s aspect=%s res=%s n_index=%d/%d prompt_len=%d",
            model_id,
            ar,
            res_label,
            i + 1,
            count,
            len(p),
        )
        try:
            resp = requests.post(
                OPENROUTER_CHAT_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            last_err = "OpenRouter timeout — máy chủ không trả lời kịp. Thử lại hoặc đổi model."
            _LOG.warning("openrouter_image timeout model=%s", model_id)
            continue
        except requests.RequestException as exc:
            last_err = f"Không kết nối được OpenRouter: {exc}"
            _LOG.warning("openrouter_image connect failed model=%s err=%s", model_id, exc)
            continue

        raw = resp.text or ""
        if resp.status_code != 200:
            last_err = format_openrouter_image_error(
                status_code=resp.status_code, body=raw, model=model_id
            )
            _LOG.warning(
                "openrouter_image_chat failed http=%s model=%s body=%s",
                resp.status_code,
                model_id,
                raw[:500],
            )
            # fall through to try legacy once for first image if chat invalid endpoint
            if resp.status_code == 404 and i == 0:
                legacy = _generate_via_legacy_images_endpoint(
                    prompt=p,
                    model_id=model_id,
                    aspect_ratio=ar,
                    headers=headers,
                    timeout=timeout,
                )
                if legacy:
                    out.extend(legacy)
                    break
            continue

        try:
            data = resp.json()
        except ValueError:
            last_err = f"OpenRouter trả JSON không hợp lệ: {raw[:200]}"
            continue

        blobs = _parse_chat_images(data if isinstance(data, dict) else {})
        if not blobs:
            last_err = "OpenRouter không trả về ảnh (message.images trống)."
            _LOG.warning("openrouter_image empty images model=%s keys=%s", model_id, list(data.keys()) if isinstance(data, dict) else type(data))
            continue
        out.append(blobs[0])

    if not out:
        raise ValueError(last_err or "OpenRouter không tạo được ảnh.")
    return out[:count]


def _generate_via_legacy_images_endpoint(
    *,
    prompt: str,
    model_id: str,
    aspect_ratio: str,
    headers: dict[str, str],
    timeout: float,
) -> list[bytes]:
    body = {
        "model": model_id,
        "prompt": prompt[:3900],
        "n": 1,
        "aspect_ratio": aspect_ratio,
    }
    try:
        resp = requests.post(OPENROUTER_IMAGES_URL, headers=headers, json=body, timeout=timeout)
    except Exception as exc:
        _LOG.debug("legacy images endpoint failed: %s", exc)
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    return _parse_legacy_images(data if isinstance(data, dict) else {})


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
    errors: list[str] = []
    for i, prompt in enumerate(prompts):
        p = str(prompt or "").strip()
        if not p:
            continue
        try:
            blobs = generate_images_batch(
                prompt=p,
                model=model_id,
                aspect_ratio=aspect_ratio,
                custom_width=custom_width,
                custom_height=custom_height,
                size=size,
                n=1,
            )
        except ValueError as exc:
            errors.append(str(exc))
            _LOG.warning("variant %s failed: %s", i, exc)
            continue
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
                "credits_per_image": credits_per_image(model_id),
            }
        )
    if not results:
        msg = errors[0] if errors else "Không tạo được ảnh preview — kiểm tra prompt và model ảnh OpenRouter."
        raise ValueError(msg)
    return results


def _save_generated_image_bytes(
    data: bytes,
    *,
    stem: str = "ai-img",
    user_id: int | None = None,
    project_id: str | None = None,
) -> str:
    try:
        from app.services.content_ai_image_optimizer import save_optimized_image

        opt = save_optimized_image(
            data,
            stem=stem,
            orientation="any",
            prefer_landscape_crop=True,
            user_id=user_id,
            project_id=project_id,
        )
        if opt and getattr(opt, "local_url", None):
            return str(opt.local_url)
    except Exception:
        _LOG.debug("optimize skip, save raw", exc_info=True)

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
