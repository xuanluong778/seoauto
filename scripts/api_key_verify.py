"""Verify API keys against provider endpoints (minimal request)."""

from __future__ import annotations

import requests

_OPENAI_FAMILY = frozenset({"openai", "custom_openai", "openrouter"})
_ANTHROPIC_FAMILY = frozenset({"custom_anthropic"})
_GEMINI_FAMILY = frozenset({"google_gemini"})


def verify_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    p = str(provider or "openai").strip().lower()
    key = str(api_key or "").strip()
    if len(key) < 8:
        return False, "API key quá ngắn."
    try:
        if p in _OPENAI_FAMILY:
            return _verify_openai_compatible(key, base_url=_openai_base_for_provider(p))
        if p in _ANTHROPIC_FAMILY:
            return _verify_anthropic(key)
        if p in _GEMINI_FAMILY:
            return _verify_gemini(key)
        if p == "openrouter":
            return _verify_openai_compatible(key, base_url="https://openrouter.ai/api/v1")
        # vertex / fal — format-only for trial activation
        if len(key) >= 12:
            return True, "Đã xác nhận định dạng khóa (chưa gọi API đầy đủ cho provider này)."
        return False, "Provider chưa hỗ trợ kiểm tra tự động."
    except requests.Timeout:
        return False, "Hết thời gian khi gọi API provider."
    except requests.RequestException as exc:
        return False, f"Lỗi kết nối: {str(exc)[:200]}"


def _openai_base_for_provider(provider: str) -> str:
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    return "https://api.openai.com/v1"


def _verify_openai_compatible(api_key: str, *, base_url: str) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/models"
    r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    if r.status_code == 200:
        return True, "API key OpenAI-compatible hợp lệ."
    if r.status_code in (401, 403):
        return False, "API key không hợp lệ hoặc bị từ chối."
    return False, f"Provider trả HTTP {r.status_code}: {(r.text or '')[:180]}"


def _verify_anthropic(api_key: str) -> tuple[bool, str]:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-3-5-haiku-20241022",
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "ping"}],
        },
        timeout=25,
    )
    if r.status_code in (200, 400):
        return True, "API key Anthropic hợp lệ."
    if r.status_code in (401, 403):
        return False, "API key Anthropic không hợp lệ."
    return False, f"Anthropic HTTP {r.status_code}: {(r.text or '')[:180]}"


def _verify_gemini(api_key: str) -> tuple[bool, str]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    r = requests.get(url, params={"key": api_key}, timeout=20)
    if r.status_code == 200:
        return True, "API key Gemini hợp lệ."
    if r.status_code in (400, 401, 403):
        return False, "API key Gemini không hợp lệ."
    return False, f"Gemini HTTP {r.status_code}: {(r.text or '')[:180]}"
