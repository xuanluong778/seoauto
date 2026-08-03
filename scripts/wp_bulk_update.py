from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.llm_content_writer import load_llm_config


def normalize_wp_base_url(wp_url: str) -> str:
    raw = (wp_url or "").strip()
    if not raw:
        raise ValueError("Missing wp_url")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid wp_url")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def build_wp_session(username: str, app_password: str, *, strip_spaces: bool) -> requests.Session:
    user = (username or "").strip()
    pwd = (app_password or "").strip()
    if strip_spaces:
        pwd = re.sub(r"\s+", "", pwd)
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    s = requests.Session()
    s.auth = (user, pwd)
    s.headers.update({"Accept": "application/json", "Authorization": f"Basic {token}"})
    return s


def wp_auth_check(*, session: requests.Session, wp_base: str) -> None:
    r = session.get(f"{wp_base}/wp-json/wp/v2/users/me", timeout=25)
    if r.status_code >= 400:
        raise RuntimeError(f"WP auth failed HTTP {r.status_code}: {(r.text or '')[:500]}")


def wp_list_posts(
    *,
    session: requests.Session,
    wp_base: str,
    post_type: str = "posts",
    status: str = "publish",
    per_page: int = 50,
    page: int = 1,
) -> tuple[list[dict[str, Any]], int | None]:
    per_page = max(1, min(int(per_page or 50), 100))
    page = max(1, int(page or 1))
    url = f"{wp_base}/wp-json/wp/v2/{post_type}"
    r = session.get(url, params={"status": status, "per_page": per_page, "page": page}, timeout=35)
    if r.status_code >= 400:
        raise RuntimeError(f"WP list failed HTTP {r.status_code}: {(r.text or '')[:800]}")
    items = r.json() if r.content else []
    total_pages = None
    try:
        total_pages = int(r.headers.get("X-WP-TotalPages") or 0) or None
    except Exception:
        total_pages = None
    if not isinstance(items, list):
        items = []
    return items, total_pages


def wp_update_post_content(
    *,
    session: requests.Session,
    wp_base: str,
    post_id: int,
    post_type: str = "posts",
    new_content_html: str,
) -> dict[str, Any]:
    url = f"{wp_base}/wp-json/wp/v2/{post_type}/{int(post_id)}"
    r = session.post(url, json={"content": new_content_html}, timeout=50)
    if r.status_code >= 400:
        raise RuntimeError(f"WP update failed HTTP {r.status_code}: {(r.text or '')[:1200]}")
    data = r.json() if r.content else {}
    return data if isinstance(data, dict) else {}


MARKER_START = "<!-- tooltechnical-ai-addon:start -->"
MARKER_END = "<!-- tooltechnical-ai-addon:end -->"


def has_marker(html: str) -> bool:
    s = str(html or "")
    return MARKER_START in s and MARKER_END in s


def wrap_marker(block_html: str) -> str:
    b = (block_html or "").strip()
    return f"\n\n{MARKER_START}\n{b}\n{MARKER_END}\n"


@dataclass(frozen=True)
class AddonSpec:
    goal: str
    tone: str = "chuyên gia, rõ ràng, tự nhiên"
    language: str = "vi"
    max_words: int = 350


def generate_addon_html(*, title: str, existing_html: str, spec: AddonSpec) -> str:
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    t = re.sub(r"\s+", " ", str(title or "").strip())
    existing = str(existing_html or "").strip()
    existing = existing[:12000]  # cost guard
    goal = re.sub(r"\s+", " ", str(spec.goal or "").strip()) or "Bổ sung FAQ + kết luận + CTA"
    tone = re.sub(r"\s+", " ", str(spec.tone or "").strip()) or "chuyên gia, rõ ràng, tự nhiên"
    max_words = max(120, min(int(spec.max_words or 350), 800))

    system = "Bạn là trợ lý biên tập nội dung WordPress. Ưu tiên chính xác, không bịa."
    user = (
        "Nhiệm vụ: tạo 1 KHỐI HTML NGẮN để CHÈN THÊM VÀO CUỐI BÀI.\n"
        "Ràng buộc bắt buộc:\n"
        f"- Viết tiếng {spec.language}.\n"
        f"- Giọng văn: {tone}.\n"
        f"- Mục tiêu: {goal}.\n"
        f"- Độ dài tối đa: khoảng {max_words} từ.\n"
        "- KHÔNG viết lại nội dung cũ, KHÔNG tạo <h1>.\n"
        "- Dùng các thẻ: <h2>, <h3>, <p>, <ul><li>.\n"
        "- Chỉ dùng thông tin có trong bài; thiếu dữ kiện thì viết trung tính hoặc gợi ý khách liên hệ đơn vị — không dùng placeholder kiểu [CẦN XÁC NHẬN].\n"
        "- Trả về CHỈ HTML (không markdown, không code fence).\n"
        "\n"
        f"TIÊU ĐỀ BÀI: {t}\n"
        "\n"
        "=== NỘI DUNG HIỆN TẠI (TRÍCH) ===\n"
        f"{existing}\n"
        "\n"
        "=== OUTPUT (HTML BLOCK) ===\n"
    )

    # Reuse internal HTTP calls in llm_content_writer without importing private helpers.
    # Minimal duplication: call OpenAI/Anthropic endpoints here.
    if cfg.provider == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:400]}")
        data = r.json() if r.content else {}
        out = str((((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "").strip()
        return out

    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload2: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": 1200,
        "temperature": cfg.temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    r2 = requests.post(url, headers=headers, json=payload2, timeout=60)
    if r2.status_code >= 400:
        raise RuntimeError(f"Anthropic HTTP {r2.status_code}: {(r2.text or '')[:400]}")
    data2 = r2.json() if r2.content else {}
    blocks = data2.get("content") or []
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text") or ""))
    return "\n".join(parts).strip()

