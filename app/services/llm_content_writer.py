from __future__ import annotations

import os
import re
import json
import html as py_html
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values

from app.services.content_draft_builder import (
    _looks_like_generic_template,
    content_ai_has_local_service_signal,
    detect_search_intent,
    extract_clean_html_fragment,
)


def _content_seo_checklist_snippet(*, max_chars: int = 4500) -> str:
    from app.services.content_seo_checklist import content_seo_checklist_snippet

    return content_seo_checklist_snippet(max_chars=max_chars)


def _anthropic_max_tokens_for_field(*, field: str, word_target: int | None) -> int:
    f = (field or "").strip().lower()
    if f != "content":
        return 1600
    w = int(word_target or 1200)
    w = max(400, min(w, 20000))
    est = int(w * 1.55) + 1800
    return max(4096, min(8192, est))


def _openai_max_tokens_for_field(*, field: str, word_target: int | None) -> int | None:
    f = (field or "").strip().lower()
    if f != "content":
        return None
    w = int(word_target or 1200)
    w = max(400, min(w, 20000))
    return min(16384, max(4096, int(w * 1.85) + 800))


def _read_env_local() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    if not env_file.exists():
        return {}
    raw = dotenv_values(env_file)
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if not k:
            continue
        out[str(k)] = str(v or "")
    return out


def _getenv(name: str, env_local: dict[str, str]) -> str:
    return str((os.getenv(name) or env_local.get(name) or "")).strip()


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _sanitize_mixed_style_phrases(text: str) -> str:
    out = str(text or "")
    substitutions = [
        (r"(?i)\bin this article we will\b", "Thông tin bên dưới tập trung trực tiếp vào nhu cầu dịch vụ"),
        (r"(?i)\btrong bài viết này\b", "Trong nội dung dịch vụ này"),
        (r"(?i)\btrong trải nghiệm của mình\b", "Theo dữ liệu vận hành thực tế"),
        (r"(?i)\bcác bước làm\b", "quy trình xử lý"),
        (r"(?i)\blocal service page\b", ""),
        (r"(?i)\bservice page\b", ""),
        (r"(?i)\btrang dịch vụ địa phương\b", ""),
        (r"(?i)\blà trang dịch vụ địa phương\b", "phục vụ tại khu vực này"),
    ]
    for pattern, repl in substitutions:
        out = re.sub(pattern, repl, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return out.strip()


def _strip_bracket_placeholders(html: str) -> str:
    """Remove editorial placeholders the model must never emit (best-effort)."""
    s = str(html or "")
    s = re.sub(r"\[\s*CẦN\s+XÁC\s+NHẬN\s*\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[\s*TODO\s*\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[\s*TBD\s*\]", "", s, flags=re.IGNORECASE)
    return s


def _transactional_gaps(html_text: str) -> list[str]:
    s = str(html_text or "").lower()
    gaps: list[str] = []
    if not any(x in s for x in ("dịch vụ", "dich vu", "hỗ trợ", "ho tro")):
        gaps.append("Thiếu mô tả rõ dịch vụ cung cấp.")
    if not any(x in s for x in ("kinh nghiệm", "kinh nghiem", "khách hàng", "khach hang", "bảo hành", "bao hanh")):
        gaps.append("Thiếu dấu hiệu tin cậy (kinh nghiệm/khách hàng/bảo hành).")
    if not any(x in s for x in ("bao gồm", "bao gom", "hạng mục", "hang muc")):
        gaps.append("Thiếu phần hạng mục bao gồm.")
    if not any(x in s for x in ("chi phí", "chi phi", "bảng giá", "bang gia", "giá", "gia")):
        gaps.append("Thiếu phần chi phí/bảng giá.")
    if not any(x in s for x in ("liên hệ", "lien he", "hotline", "zalo", "đặt lịch", "dat lich", "booking")):
        gaps.append("Thiếu CTA liên hệ ngay.")
    return gaps


def _first_line(s: str) -> str:
    raw = str(s or "").replace("\r", "")
    parts = [x.strip() for x in raw.split("\n") if x.strip()]
    return parts[0] if parts else str(s or "").strip()


def _plain_text_to_html_fragment(*, text: str, title: str = "", primary_keyword: str = "") -> str:
    raw = _clean_ws(text)
    if not raw:
        return ""
    lines = [re.sub(r"\s+", " ", x).strip() for x in raw.replace("\r", "\n").split("\n") if x.strip()]
    if not lines:
        return ""
    h1 = _clean_ws(title) or _clean_ws(primary_keyword) or lines[0]
    body: list[str] = [f"<h1>{h1}</h1>"]
    bullets: list[str] = []

    def _flush_bullets() -> None:
        nonlocal bullets
        if not bullets:
            return
        body.append("<ul>")
        for item in bullets:
            body.append(f"<li>{item}</li>")
        body.append("</ul>")
        bullets = []

    for ln in lines:
        if ln == h1:
            continue
        if re.match(r"^[-*•]\s+", ln):
            bullets.append(re.sub(r"^[-*•]\s+", "", ln).strip())
            continue
        _flush_bullets()
        body.append(f"<p>{ln}</p>")
    _flush_bullets()
    return "\n".join(body).strip()


def _decode_html_entities_text(text: str) -> str:
    s = str(text or "")
    if not s:
        return ""
    # Decode entities twice to handle nested escaping (&amp;agrave; -> &agrave; -> à).
    once = py_html.unescape(s)
    twice = py_html.unescape(once)
    return twice


def _count_words_vi(text: str) -> int:
    """
    Rough Vietnamese-friendly word count.
    Count "words" as sequences of letters/digits (including Vietnamese diacritics).
    """
    t = str(text or "").strip()
    if not t:
        return 0
    words = re.findall(r"[\wà-ỹÀ-Ỹ]+", t, flags=re.I)
    return len(words)


def _count_words_html(html: str) -> int:
    raw = str(html or "").strip()
    if not raw:
        return 0
    try:
        soup = BeautifulSoup(raw, "html.parser")
        text = soup.get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
    return _count_words_vi(text)


def _take_first_words(text: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if limit <= 0 or not s:
        return ""
    words = re.findall(r"\S+", s)
    if len(words) <= limit:
        return s
    return " ".join(words[:limit]).strip()


def _trim_html_to_max_words(html: str, max_words: int) -> str:
    """
    Deterministic hard cap for HTML word count.
    Keeps document structure as much as possible and truncates the tail.
    """
    raw = str(html or "").strip()
    if not raw or max_words <= 0:
        return ""
    if _count_words_html(raw) <= max_words:
        return raw
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return _take_first_words(raw, max_words)

    consumed = 0
    hit_limit = False
    block_text_tags = {"p", "li", "blockquote", "td", "th", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6"}

    def _trim_tag_text(tag: Any, remain: int) -> None:
        txt = tag.get_text(" ", strip=True)
        trimmed = _take_first_words(txt, remain)
        tag.clear()
        if trimmed:
            tag.append(trimmed)

    for tag in soup.find_all(True):
        if hit_limit:
            tag.decompose()
            continue
        name = str(tag.name or "").lower()
        if name not in block_text_tags:
            continue
        txt = tag.get_text(" ", strip=True)
        w = _count_words_vi(txt)
        if w <= 0:
            continue
        if consumed + w <= max_words:
            consumed += w
            continue
        remain = max_words - consumed
        if remain > 0:
            _trim_tag_text(tag, remain)
            consumed = max_words
        else:
            tag.decompose()
        hit_limit = True

    body = soup.body
    out = "".join(str(x) for x in (body.contents if body else soup.contents)).strip()
    return out or _take_first_words(raw, max_words)


def _ensure_min_words_html(*, html: str, min_words: int, keyword: str, title: str) -> str:
    raw = str(html or "").strip()
    if not raw:
        raw = f"<h1>{_clean_ws(title) or _clean_ws(keyword) or 'Nội dung dịch vụ'}</h1>"
    if _count_words_html(raw) >= min_words:
        return raw
    need = max(0, min_words - _count_words_html(raw))
    topic = _clean_ws(keyword) or _clean_ws(title) or "dịch vụ"
    blocks: list[str] = []
    i = 1
    while need > 0 and i <= 32:
        blocks.append(
            f"<p>Kinh nghiệm thực tế #{i}: với nhu cầu {topic}, chúng tôi ưu tiên kiểm tra nguyên nhân gốc, "
            "giải thích rõ từng bước xử lý và đề xuất phương án phù hợp ngân sách để khách dễ quyết định.</p>"
        )
        blocks.append(
            "<p>Trong quá trình triển khai, kỹ thuật viên xác nhận hạng mục trước khi làm, cập nhật tiến độ minh bạch, "
            "và nghiệm thu theo checklist nhằm hạn chế lỗi lặp lại sau sửa chữa.</p>"
        )
        need -= 65
        i += 1
    addon = "<h2>Mẹo sử dụng và bảo trì sau xử lý</h2>" + "".join(blocks)
    return (raw + "\n" + addon).strip()


def _fetch_source_text(url: str) -> tuple[str, str]:
    """
    Fetch a URL and return (final_url, extracted_text).
    Best-effort: strips scripts/styles, keeps visible text.
    """
    raw_url = str(url or "").strip()
    if not raw_url:
        return "", ""
    if not raw_url.lower().startswith(("http://", "https://")):
        raw_url = "https://" + raw_url.lstrip("/")
    try:
        resp = requests.get(
            raw_url,
            timeout=18,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
                )
            },
        )
    except Exception:
        return raw_url, ""
    final_url = str(resp.url or raw_url)
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return final_url, text


def _fetch_related_posts_for_internal_links(target_website: str, keyword: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Best-effort crawl related posts from WP REST for internal-link prompting."""
    raw = str(target_website or "").strip()
    if not raw:
        return []
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")
    try:
        p = requests.utils.urlparse(raw)
        if p.scheme not in {"http", "https"} or not p.netloc:
            return []
        base = f"{p.scheme}://{p.netloc}".rstrip("/")
    except Exception:
        return []

    api = f"{base}/wp-json/wp/v2/posts"
    params: dict[str, Any] = {
        "per_page": max(3, min(int(limit or 8), 20)),
        "_fields": "link,title.rendered",
        "orderby": "date",
        "order": "desc",
    }
    kw = str(keyword or "").strip()
    if kw:
        params["search"] = kw
    try:
        r = requests.get(api, params=params, timeout=18, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code >= 400:
            return []
        data = r.json() if r.content else []
    except Exception:
        return []
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for it in data:
        if not isinstance(it, dict):
            continue
        link = str(it.get("link") or "").strip()
        title_obj = it.get("title") or {}
        title_html = str((title_obj.get("rendered") if isinstance(title_obj, dict) else "") or "").strip()
        title = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        if link and title:
            out.append({"title": title, "url": link})
    return out


def _truncate_text(text: str, *, max_chars: int) -> str:
    t = str(text or "").strip()
    if len(t) <= max_chars:
        return t
    # keep head + tail for some context
    head = t[: max(0, int(max_chars * 0.75))]
    tail = t[-max(0, int(max_chars * 0.20)) :]
    return (head + "\n...\n" + tail).strip()


@dataclass(frozen=True)
class LlmConfig:
    provider: str  # "openai" | "anthropic"
    api_key: str
    model: str
    temperature: float
    api_base_url: str | None = None


_OPENAI_KEY_PROVIDERS = frozenset({"openai", "custom_openai", "openrouter"})
_ANTHROPIC_KEY_PROVIDERS = frozenset({"custom_anthropic"})


def _llm_temperature(env_local: dict[str, str]) -> float:
    temp_raw = _getenv("LLM_TEMPERATURE", env_local) or "0.3"
    try:
        temperature = float(temp_raw)
    except ValueError:
        temperature = 0.3
    return max(0.0, min(1.0, temperature))


def _load_llm_config_from_env() -> LlmConfig | None:
    env_local = _read_env_local()
    provider_raw = (_getenv("LLM_PROVIDER", env_local) or "").strip().lower()
    openai_key = _getenv("OPENAI_API_KEY", env_local)
    anthropic_key = _getenv("ANTHROPIC_API_KEY", env_local)

    if provider_raw in {"openai", "anthropic"}:
        provider = provider_raw
    else:
        provider = "anthropic" if anthropic_key else ("openai" if openai_key else "openai")

    api_base_url: str | None = None
    if provider == "openai":
        api_key = openai_key
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
        base = _getenv("OPENAI_BASE_URL", env_local)
        if base:
            api_base_url = base.rstrip("/")
    else:
        api_key = anthropic_key
        model = _getenv("ANTHROPIC_MODEL", env_local) or "claude-3-5-sonnet-20241022"

    if not api_key:
        return None

    return LlmConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        temperature=_llm_temperature(env_local),
        api_base_url=api_base_url,
    )


def _load_llm_config_from_user_keys(user_id: int) -> LlmConfig | None:
    from app.services.api_keys_store import list_enabled_keys_for_user

    keys = list_enabled_keys_for_user(user_id)
    if not keys:
        return None

    env_local = _read_env_local()
    provider_pref = (_getenv("LLM_PROVIDER", env_local) or "").strip().lower()

    openai_keys = [k for k in keys if k["provider"] in _OPENAI_KEY_PROVIDERS]
    anthropic_keys = [k for k in keys if k["provider"] in _ANTHROPIC_KEY_PROVIDERS]

    pick: dict[str, Any] | None = None
    llm_provider: str | None = None

    if provider_pref == "openai" and openai_keys:
        pick, llm_provider = openai_keys[0], "openai"
    elif provider_pref == "anthropic" and anthropic_keys:
        pick, llm_provider = anthropic_keys[0], "anthropic"
    elif anthropic_keys:
        pick, llm_provider = anthropic_keys[0], "anthropic"
    elif openai_keys:
        pick, llm_provider = openai_keys[0], "openai"

    if not pick or not llm_provider:
        return None

    store_provider = str(pick.get("provider") or "")
    api_base_url: str | None = None
    if store_provider == "openrouter":
        api_base_url = "https://openrouter.ai/api/v1"
        model = _getenv("OPENROUTER_MODEL", env_local) or _getenv("OPENAI_MODEL", env_local) or "openai/gpt-4o-mini"
    elif store_provider == "custom_openai":
        base = _getenv("OPENAI_BASE_URL", env_local)
        api_base_url = base.rstrip("/") if base else None
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
    elif llm_provider == "openai":
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
    else:
        model = _getenv("ANTHROPIC_MODEL", env_local) or "claude-3-5-sonnet-20241022"

    api_key = str(pick.get("api_key") or "").strip()
    if not api_key:
        return None

    return LlmConfig(
        provider=llm_provider,
        api_key=api_key,
        model=model,
        temperature=_llm_temperature(env_local),
        api_base_url=api_base_url,
    )


def load_llm_config(user_id: int | None = None) -> LlmConfig | None:
    """
    Resolve LLM credentials for the current request.

    Logged-in users: own API keys first; if admin granted ``use_admin_api_pool``,
    fall back to env.local / admin keys. Requires ``api_access_enabled`` (except admin).
  """
    uid = user_id
    if uid is None:
        from app.core.user_context import get_request_user_id

        uid = get_request_user_id()
    if uid is not None:
        from app.db import SessionLocal
        from app.services.user_api_access import resolve_llm_config_for_user

        db = SessionLocal()
        try:
            return resolve_llm_config_for_user(db, int(uid))
        finally:
            db.close()
    return _load_llm_config_from_env()


def load_llm_config_admin() -> LlmConfig | None:
    """
    Khóa API hệ thống (env.local) — dùng cho chatbot, không dùng khóa từng user.
    """
    return _load_llm_config_from_env()


def _build_instructions(
    *,
    field: str,
    target_word_count: int | None = None,
    primary_keyword: str = "",
    llm_mode: str = "auto",
    user_outline_present: bool = False,
    knowledge: dict[str, Any] | None = None,
) -> str:
    """Delegate SEO field prompts to seo_content_prompt (Helpful Content + EEAT)."""
    from app.services.content_ai_knowledge_context import build_content_prompt_with_knowledge
    from app.services.seo_content_prompt import build_llm_field_instructions

    base = build_llm_field_instructions(
        field=field,
        target_word_count=target_word_count,
        primary_keyword=primary_keyword,
        llm_mode=llm_mode,
        user_outline_present=user_outline_present,
        knowledge=knowledge,
    )
    extra = build_content_prompt_with_knowledge(
        knowledge or {},
        field=field,
        primary_keyword=primary_keyword,
    )
    return base + extra if extra else base


def _openai_chat_completion(
    *,
    cfg: LlmConfig,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    timeout_sec: int = 45,
) -> str:
    base = (cfg.api_base_url or "https://api.openai.com").rstrip("/")
    url = f"{base}/v1/chat/completions" if not base.endswith("/chat/completions") else base
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    r = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:400]}")
    data = r.json() if r.content else {}
    try:
        msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return _clean_ws("\n".join(parts)).strip()
        return str(content or "").strip()
    except Exception as exc:
        raise RuntimeError("OpenAI response parse failed") from exc


def _anthropic_messages(
    *,
    cfg: LlmConfig,
    system: str,
    user: str,
    max_tokens: int = 1600,
    timeout_sec: int = 45,
) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    mt = max(256, min(8192, int(max_tokens)))
    payload: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": mt,
        "temperature": cfg.temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic HTTP {r.status_code}: {(r.text or '')[:400]}")
    data = r.json() if r.content else {}
    try:
        blocks = data.get("content") or []
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
        return _clean_ws("\n".join(parts)).strip()
    except Exception as exc:
        raise RuntimeError("Anthropic response parse failed") from exc


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def generate_seo_article_json(
    *,
    keyword: str,
    secondary_keywords: list[str] | None = None,
    intent: str = "",
    audience: str = "",
    brand_name: str = "",
    outline: str = "",
    context_data: str = "",
) -> dict[str, Any]:
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    kw = _clean_ws(keyword)
    if not kw:
        raise RuntimeError("keyword is required")
    lsi = secondary_keywords or []
    lsi_clean = [re.sub(r"\s+", " ", str(x or "").strip()) for x in lsi if str(x or "").strip()]
    lsi_clean = lsi_clean[:20]

    system = "Bạn là copywriter và biên tập. Ưu tiên chính xác, hữu ích cho độc giả; không dùng placeholder [CẦN XÁC NHẬN]."
    user = (
        "Bạn PHẢI trả về đúng 1 JSON object hợp lệ (không markdown, không code fence, không giải thích).\n"
        "\n"
        "Mục tiêu:\n"
        "- Bài có giá trị thực, đúng nhu cầu tìm kiếm; viết cho người đọc, không giải thích khái niệm SEO\n"
        "- Nội dung chính xác; thiếu dữ kiện thì trung tính hoặc minh họa, không placeholder\n"
        "- Văn phong human-like: ưu tiên “Tôi/Mình/Chúng tôi”, có trải nghiệm thực tế khi phù hợp\n"
        "- Cấu trúc rõ, dễ đọc, có lời kêu gọi phù hợp khi là chủ đề dịch vụ\n"
        "\n"
        "INPUT:\n"
        f"- Keyword chính: {kw}\n"
        f"- Keyword phụ (LSI): {', '.join(lsi_clean)}\n"
        f"- Search intent: {str(intent or '').strip()}\n"
        f"- Đối tượng đọc: {str(audience or '').strip()}\n"
        f"- Brand: {str(brand_name or '').strip()}\n"
        f"- Outline (nếu có): {str(outline or '').strip()}\n"
        f"- Context (crawl/top SERP nếu có): {str(context_data or '').strip()}\n"
        "\n"
        "NGUYÊN TẮC (BẮT BUỘC):\n"
        "1) Trả lời trực tiếp vấn đề trong 2 câu đầu.\n"
        "2) Không lan man; mỗi đoạn 2–3 câu, ≤ 3 dòng.\n"
        "3) 1 H1 duy nhất (chứa keyword chính), ≥ 3 H2; H2 đầu tiên chứa keyword chính/biến thể.\n"
        "4) Keyword chính: có trong H1, trong ~100 ký tự đầu, và H2 đầu tiên; mật độ ~1%, không spam.\n"
        "5) TITLE: 50–60 ký tự, keyword ở đầu, không giật tít.\n"
        "6) META: 150–160 ký tự, có keyword chính + brand.\n"
        "7) UX: có bullet list, có bảng, có blockquote, có in đậm ý quan trọng.\n"
        "8) Media: CẤM thẻ <img> với src bịa/placeholder — ảnh do hệ thống chèn sau (nút Chèn ảnh). "
        "Có thể ghi <!-- ảnh: mô tả ngắn --> tại H2 nếu cần gợi ý vị trí.\n"
        "9) Link: có internal link placeholder + 1 external link uy tín (Wikipedia hoặc site uy tín) nếu phù hợp.\n"
        "10) E-E-A-T: có author thật + bio cuối bài (nếu thiếu dữ kiện thì viết trung tính).\n"
        "\n"
        "OUTPUT FORMAT (JSON):\n"
        "{\n"
        '  \"title\": \"...\",\n'
        '  \"meta_description\": \"...\",\n'
        '  \"slug\": \"...\",\n'
        '  \"content_html\": \"...\",\n'
        '  \"tags\": [\"...\"],\n'
        '  \"excerpt\": \"...\",\n'
        '  \"schema\": { \"article\": \"...\", \"author\": \"...\", \"faq\": \"...\" }\n'
        "}\n"
        "\n"
        "Ràng buộc output:\n"
        "- content_html phải là HTML hợp lệ (có <h1>...)</n"
        "- schema.* là JSON-LD string (mỗi field là 1 chuỗi chứa JSON-LD)\n"
        "- Không được trả về null; thiếu thì dùng chuỗi rỗng hoặc mảng rỗng.\n"
    ).strip()

    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user)

    obj = _try_parse_json_object(out)
    if obj is None:
        fixer = (
            "Bạn đã tạo output nhưng nó chưa phải JSON object hợp lệ.\n"
            "Hãy CHỈ trả về 1 JSON object hợp lệ đúng schema yêu cầu, không thêm chữ nào khác.\n"
            "\n"
            "=== OUTPUT CẦN SỬA ===\n"
            f"{out}\n"
            "\n"
            "=== JSON HỢP LỆ ===\n"
        )
        if cfg.provider == "openai":
            out2 = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": fixer}],
            )
        else:
            out2 = _anthropic_messages(cfg=cfg, system=system, user=fixer)
        obj = _try_parse_json_object(out2)
        if obj is None:
            raise RuntimeError("Model did not return valid JSON.")

    def _s(x: Any) -> str:
        return str(x or "").strip()

    tags_val = obj.get("tags")
    tags_out: list[str] = []
    if isinstance(tags_val, list):
        for t in tags_val[:20]:
            tt = re.sub(r"\s+", " ", str(t or "").strip())
            if tt:
                tags_out.append(tt)

    schema_val = obj.get("schema") if isinstance(obj.get("schema"), dict) else {}
    schema_out = {
        "article": _s((schema_val or {}).get("article")),
        "author": _s((schema_val or {}).get("author")),
        "faq": _s((schema_val or {}).get("faq")),
    }

    html_body = _sanitize_mixed_style_phrases(_strip_bracket_placeholders(_s(obj.get("content_html"))))
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes

    from app.services.content_ai_publish_checklist import strip_publish_checklist_from_html
    from app.services.content_table_format import enhance_tables_in_html

    html_body = enhance_tables_in_html(
        strip_publish_checklist_from_html(postprocess_content_blockquotes(html_body))
    )
    from app.services.content_ai_content_images import sanitize_invalid_content_images

    html_body, _ = sanitize_invalid_content_images(html_body)
    return {
        "title": _s(obj.get("title")),
        "meta_description": _s(obj.get("meta_description")),
        "slug": _s(obj.get("slug")),
        "content_html": html_body,
        "tags": tags_out,
        "excerpt": _s(obj.get("excerpt")),
        "schema": schema_out,
    }


def optimize_seo_content_html(*, content_html: str) -> str:
    """
    SEO Editor: rewrite existing HTML to be clearer, accurate, human-like and SEO-friendly.
    Must return clean HTML (no markdown / no code fences).
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    html = str(content_html or "").strip()
    if not html:
        return ""
    # Guard cost / latency.
    html = html[:18000]

    system = "Bạn là biên tập nội dung. Ưu tiên chính xác, rõ ràng, tự nhiên. Không bịa; xóa placeholder [CẦN XÁC NHẬN] bằng câu hoàn chỉnh."
    user = (
        "Nhiệm vụ: Tối ưu lại content cho dễ đọc, mạch lạc:\n"
        "- Logic rõ ràng\n"
        "- Không sai fact\n"
        "- Không lan man\n"
        "- Giọng tự nhiên, vì người đọc (không meta-bình về SEO hay service page)\n"
        "\n"
        "FIX:\n"
        "1) Sửa sai logic, câu khó hiểu, nội dung vô nghĩa.\n"
        "2) Tối ưu: ngắn gọn hơn, tăng readability, thêm trải nghiệm cá nhân nếu thiếu (nhưng không bịa).\n"
        "3) Loại bỏ: AI tone, lặp ý, keyword stuffing.\n"
        "\n"
        "Ràng buộc bắt buộc:\n"
        "- Trả về HTML sạch.\n"
        "- Giữ nguyên cấu trúc heading hiện có (giữ 1 H1 nếu có, giữ hệ H2/H3; không phá cấp heading).\n"
        "- Không thêm claim/số liệu mới nếu không có trong bài.\n"
        "- Không trả về markdown, không code fence.\n"
        "\n"
        "INPUT (HTML):\n"
        f"{html}\n"
        "\n"
        "OUTPUT (HTML sạch):\n"
    ).strip()

    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user)

    cleaned = str(out or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    cleaned = _strip_bracket_placeholders(cleaned)
    return _sanitize_mixed_style_phrases(cleaned)


def suggest_internal_link_row_keywords(
    *,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    target_post_title: str = "",
    target_post_url: str = "",
    target_categories: str = "",
    target_tags: str = "",
    content_snippet: str = "",
) -> dict[str, str]:
    """
    Gợi ý từ khóa (chính/phụ) + một anchor ngắn cho một URL đích — trả JSON object.
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")
    system = (
        "Bạn là chuyên gia SEO nội dung. Trả về đúng 1 JSON object (không markdown, không code fence).\n"
        "Các key bắt buộc: primary_keyword (string), secondary_keywords (string, có thể nhiều từ cách nhau dấu phẩy), "
        "anchor_suggestion (string, 2–8 từ tiếng Việt, tự nhiên, mô tả đúng bài đích, phù hợp làm anchor internal link).\n"
        "anchor_suggestion phải ngắn gọn, không clickbait, không 'tại đây'."
    )
    user = (
        "Bài đang viết (ngữ cảnh):\n"
        f"- Từ khóa chính bài hiện tại: { _clean_ws(article_primary_keyword) }\n"
        f"- Từ khóa phụ bài hiện tại: { _clean_ws(article_secondary_keywords) }\n"
        f"- Đoạn trích content hiện tại (có thể rút): {_truncate_text(_clean_ws(content_snippet), max_chars=2200)}\n\n"
        "Bài viết đích cần trỏ internal link:\n"
        f"- Tiêu đề: {_clean_ws(target_post_title)}\n"
        f"- URL: {_clean_ws(target_post_url)}\n"
        f"- Chuyên mục (nếu có): {_clean_ws(target_categories)}\n"
        f"- Tag (nếu có): {_clean_ws(target_tags)}\n\n"
        "Nhiệm vụ:\n"
        "- primary_keyword: 1 cụm từ khóa chính mô tả đúng chủ đề bài ĐÍCH (có thể khác từ khóa bài đang viết).\n"
        "- secondary_keywords: 3–8 từ/cụm phụ liên quan bài đích (LSI), cách nhau bởi dấu phẩy.\n"
        "- anchor_suggestion: 1 anchor text đề xuất (có thể trùng hoặc gần với primary_keyword).\n"
    ).strip()
    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=400,
            timeout_sec=45,
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=500, timeout_sec=45)
    parsed = _try_parse_json_object(out) or {}
    return {
        "primary_keyword": str(parsed.get("primary_keyword") or "").strip(),
        "secondary_keywords": str(parsed.get("secondary_keywords") or "").strip(),
        "anchor_suggestion": str(parsed.get("anchor_suggestion") or "").strip(),
    }


def rewrite_html_insert_internal_links(
    *,
    content_html: str,
    link_jobs: list[dict[str, str]],
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    minimal: bool = False,
    placement_hints: list[dict[str, Any]] | None = None,
) -> str:
    """
    Chèn internal link vào HTML bài đang soạn.
    minimal=True: giữ nguyên bài, chỉ thêm đoạn/câu ngắn (tiết kiệm token, không viết lại cả bài).
    link_jobs: [{"url", "title", "anchor_text"}] — anchor_text bắt buộc (đã chọn/điền).
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")
    html = str(content_html or "").strip()
    if not html:
        return ""
    html = html[:56000]
    jobs = []
    for it in link_jobs or []:
        if not isinstance(it, dict):
            continue
        u = str(it.get("url") or "").strip()
        t = str(it.get("title") or "").strip()
        a = str(it.get("anchor_text") or "").strip() or t
        if u and t:
            jobs.append({"url": u, "title": t, "anchor_text": a})
    if not jobs:
        return content_html

    jobs_json = json.dumps(jobs, ensure_ascii=False)
    placement_json = ""
    if placement_hints:
        ph = []
        for pl in placement_hints:
            job = pl.get("job") if isinstance(pl.get("job"), dict) else pl
            if not isinstance(job, dict):
                continue
            ph.append(
                {
                    "url": str(job.get("target_url") or job.get("url") or "").strip(),
                    "anchor_text": str(job.get("anchor_text") or "").strip(),
                    "title": str(job.get("title") or "").strip(),
                    "section_heading": str(pl.get("section_heading") or ""),
                    "paragraph_snippet": str(pl.get("paragraph_snippet") or "")[:200],
                    "prefer_inline": bool(pl.get("anchor_inline")),
                }
            )
        if ph:
            placement_json = json.dumps(ph, ensure_ascii=False)

    _strict_rules = (
        "- CHỈ dùng URL trong LINKS_JSON — CẤM sinh URL khác.\n"
        "- Mỗi URL trong LINKS_JSON chèn ĐÚNG 1 lần; mỗi đoạn <p> TỐI ĐA 1 internal link.\n"
        "- Rải link đều theo PLACEMENT_JSON; CẤM gom link vào cuối bài hoặc hai <p> liên tiếp.\n"
        "- Không có ngữ cảnh phù hợp → BỎ QUA link đó (không ép chèn).\n"
        "- CẤM chèn trong H1/H2/H3, FAQ, CTA, đoạn liên hệ/hỗ trợ, đoạn < 48 ký tự.\n"
        "- CẤM TUYỆT ĐỐI câu dẫn: «Bạn có thể tham khảo thêm», «Xem thêm», «Tìm hiểu thêm», "
        "«để biết thêm thông tin chi tiết», «click vào đây», «Trong phần … bạn có thể đọc thêm».\n"
        "- Link PHẢI nằm TRONG câu đang nói đúng chủ đề (nhúng anchor vào luồng câu), "
        "hoặc viết lại nhẹ 1–2 câu trong cùng <p> rồi gắn <a> — không tách câu dẫn + link.\n"
        "- Ví dụ ĐÚNG: «…virus hoặc lỗi hệ điều hành; lúc này, dịch vụ <a href=URL>anchor</a> sẽ phù hợp…».\n"
        "- Không dùng anchor «tại đây», «xem thêm», «click here».\n"
        "- Trả về DUY NHẤT HTML, không giải thích.\n"
    )
    if minimal:
        system = (
            "Bạn là biên tập HTML tiếng Việt. Bài viết ĐÃ CHUẨN — chỉ chèn internal link, KHÔNG viết lại bài.\n"
            "Ràng buộc bắt buộc:\n"
            "- Trả về DUY NHẤT HTML hợp lệ (không markdown, không giải thích).\n"
            "- GIỮ NGUYÊN 100% mọi đoạn/câu/heading/ảnh đã có — không paraphrase, không xóa, không đổi thứ tự section.\n"
            "- Với MỖI link trong LINKS_JSON: chèn đúng 1 thẻ <a href=\"URL\">ANCHOR_TEXT</a> (đúng URL và anchor_text).\n"
            "- Nếu anchor_text đã có trong câu đúng ngữ cảnh: chỉ bọc cụm đó bằng <a>.\n"
            "- Nếu anchor chưa có: viết lại nhẹ hoặc thêm 1–2 câu TRONG cùng <p> (hoặc <p> mới ngay sau đoạn gợi ý) "
            "sao cho link là phần tự nhiên của luồng ý — CẤM <p> chỉ có câu dẫn + link.\n"
            f"{_strict_rules}"
        )
        user_parts = [
            f"Từ khóa chính: {_clean_ws(article_primary_keyword)}",
            f"Từ khóa phụ: {_clean_ws(article_secondary_keywords)}",
            "",
            "LINKS_JSON:",
            jobs_json,
        ]
        if placement_json:
            user_parts.extend(
                [
                    "",
                    "PLACEMENT_JSON (bắt buộc tuân thủ vị trí gợi ý — mỗi URL một vùng khác nhau):",
                    placement_json,
                ]
            )
        user_parts.extend(
            [
                "",
                "HTML_GỐC (chỉ được bổ sung tối thiểu, không rewrite toàn bài):",
                html,
                "",
                "Trả về HTML sau khi chèn link (có thể bỏ qua link không đủ ngữ cảnh).",
            ]
        )
        user = "\n".join(user_parts).strip()
        max_tok = 4500
        timeout = 90
    else:
        system = (
            "Bạn là biên tập viên HTML tiếng Việt. Nhiệm vụ: chỉnh sửa bài để chèn internal link tự nhiên, đúng ngữ cảnh.\n"
            "Ràng buộc:\n"
            "- Trả về DUY NHẤT HTML hợp lệ (không markdown, không code fence, không giải thích ngoài HTML).\n"
            "- Giữ nguyên ý chính và cấu trúc heading (H1/H2/H3) tương đương bản gốc; được phép thêm/cắt ngắn câu để neo link hợp lý.\n"
            "- Với MỖI mục trong LINKS_JSON: chèn đúng 1 thẻ <a href=\"URL\">ANCHOR_TEXT</a> dùng ĐÚNG URL và anchor_text.\n"
            "- Nếu anchor chưa có: chỉnh câu trong đoạn liên quan (PLACEMENT_JSON) để link hòa vào nội dung đang bàn.\n"
            f"{_strict_rules}"
            "- Không xóa ảnh/media có sẵn; không đổi URL ảnh.\n"
        )
        user_parts = [
            f"Từ khóa chính bài hiện tại: {_clean_ws(article_primary_keyword)}",
            f"Từ khóa phụ: {_clean_ws(article_secondary_keywords)}",
            "",
            "LINKS_JSON:",
            jobs_json,
        ]
        if placement_json:
            user_parts.extend(
                [
                    "",
                    "PLACEMENT_JSON:",
                    placement_json,
                ]
            )
        user_parts.extend(
            [
                "",
                "HTML_GỐC:",
                html,
                "",
                "Trả về HTML đã chèn link (bỏ qua link thiếu ngữ cảnh).",
            ]
        )
        user = "\n".join(user_parts).strip()
        max_tok = 12000
        timeout = 120
    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tok,
            timeout_sec=timeout,
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=max_tok, timeout_sec=timeout)
    cleaned = str(out or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    cleaned = _strip_bracket_placeholders(cleaned)
    return _sanitize_mixed_style_phrases(cleaned)


def generate_contextual_internal_link_paragraph(
    *,
    anchor_text: str,
    target_url: str,
    target_title: str = "",
    section_heading: str = "",
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    template_variant: int = 0,
) -> str:
    """
    Sinh một đoạn <p> (1–2 câu) có internal link — dùng khi không bọc được anchor inline.
    Trả về HTML fragment (thường một thẻ <p>).
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")
    anchor = _clean_ws(anchor_text)
    url = str(target_url or "").strip()
    title = _clean_ws(target_title) or anchor
    if not anchor or not url:
        raise ValueError("Thiếu anchor_text hoặc URL.")
    h2 = _clean_ws(section_heading)[:120]
    pk = _clean_ws(article_primary_keyword)
    system = (
        "Bạn là biên tập SEO tiếng Việt. Viết ĐÚNG MỘT đoạn <p> (1–2 câu) có internal link nhúng tự nhiên.\n"
        "Ràng buộc:\n"
        "- Trả về DUY NHẤT <p>...</p> — không markdown, không giải thích.\n"
        "- Đúng một <a href=\"URL\">ANCHOR</a> với URL và anchor_text đã cho.\n"
        "- Link là phần của câu đang giải thích vấn đề kỹ thuật/dịch vụ — KHÔNG câu dẫn tách rời.\n"
        "- CẤM: «Bạn có thể tham khảo thêm», «Xem thêm», «Tìm hiểu thêm», «để biết thêm chi tiết», "
        "«Nếu bạn cần thêm thông tin… tham khảo».\n"
        "- CẤM mở đầu «Trong phần … bạn có thể đọc thêm».\n"
        "- Không dùng anchor «tại đây», «xem thêm», «click here».\n"
    )
    style_hints = [
        "Mở đầu bằng lợi ích cụ thể cho độc giả.",
        "Mở đầu bằng so sánh / bổ sung nội dung section hiện tại.",
        "Mở đầu bằng hành động tiếp theo (triển khai, đặt lịch, tìm hiểu sâu).",
        "Mở đầu bằng địa phương / phạm vi dịch vụ nếu phù hợp anchor.",
    ]
    hint = style_hints[int(template_variant) % len(style_hints)]
    user = (
        f"Từ khóa bài: {pk}\n"
        f"Từ khóa phụ: {_clean_ws(article_secondary_keywords)}\n"
        f"Mục H2 gần đó: {h2 or '(không rõ)'}\n"
        f"Tiêu đề bài đích: {title}\n"
        f"anchor_text (bắt buộc dùng nguyên văn trong thẻ <a>): {anchor}\n"
        f"URL: {url}\n"
        f"Phong cách câu (bắt buộc): {hint}\n\n"
        "Viết một <p> duy nhất — khác hoàn toàn template «bạn có thể đọc thêm … để hiểu rõ hơn»."
    ).strip()
    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=400,
            timeout_sec=45,
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=400, timeout_sec=45)
    cleaned = str(out or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if not cleaned.lower().startswith("<p"):
        cleaned = f"<p>{cleaned}</p>"
    if "<a " not in cleaned.lower():
        topic = title or anchor
        cleaned = (
            f"<p>Khi gặp tình huống liên quan {py_html.escape(topic)}, "
            f"dịch vụ <a href=\"{py_html.escape(url, quote=True)}\">"
            f"{py_html.escape(anchor)}</a> hỗ trợ kiểm tra và xử lý theo quy trình phù hợp.</p>"
        )
    from app.services.wp_internal_link_postprocess import remove_template_link_sentences

    cleaned, _ = remove_template_link_sentences(cleaned)
    return _sanitize_mixed_style_phrases(cleaned)


def generate_content_ai_suggestion(
    *,
    field: str,
    title: str = "",
    content: str = "",
    target_website: str = "",
    slug: str = "",
    tags: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    target_word_count: int | None = None,
    content_brief: dict[str, Any] | None = None,
) -> str:
    """
    Lớp LLM (sinh nội dung / gợi ý theo field), tách khỏi rule-based trong `content_draft_builder`.

    Intent/signal địa phương lấy từ `detect_search_intent` / `content_ai_has_local_service_signal` (cùng nguồn với UI).
    Trả về một chuỗi tương thích API /content-ai/suggest.
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    env_local = _read_env_local()
    llm_mode = (_getenv("CONTENT_AI_LLM_MODE", env_local) or "auto").strip().lower()
    if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
        llm_mode = "auto"
    skip_rule_html = llm_mode == "auto"

    pk = _clean_ws(primary_keyword)
    sec = _clean_ws(secondary_keywords)
    t = str(title or "").strip()
    f0 = (field or "").strip().lower()
    outline = (outline_content or "").strip()
    if skip_rule_html and f0 == "content" and outline and _looks_like_generic_template(outline):
        outline = ""
    user_outline_present = bool(outline)

    wc_for_content: int | None = None
    if f0 == "content":
        try:
            wc_raw = int(target_word_count) if target_word_count is not None else None
        except Exception:
            wc_raw = None
        if wc_raw is None or wc_raw <= 0:
            wc_for_content = 1200
        else:
            wc_for_content = max(200, min(wc_raw, 20000))

    api_timeout = 120 if f0 == "content" else 45
    oai_mt = _openai_max_tokens_for_field(field=f0, word_target=wc_for_content)
    ant_mt = _anthropic_max_tokens_for_field(field=f0, word_target=wc_for_content)

    src_url = ""
    src_text = ""
    related_posts: list[dict[str, str]] = []
    if str(target_website or "").strip():
        src_url, src_text = _fetch_source_text(str(target_website or "").strip())
        src_text = _truncate_text(src_text, max_chars=9000)
        if f0 == "content":
            related_posts = _fetch_related_posts_for_internal_links(str(target_website or "").strip(), pk, limit=10)

    # Let user-provided notes be part of SOURCE too (but clearly labeled).
    notes = _truncate_text(_clean_ws(content), max_chars=3500) if content else ""
    outline_src = _truncate_text(outline, max_chars=4500) if outline else ""

    source_parts: list[str] = []
    if pk:
        source_parts.append(f"PRIMARY_KEYWORD: {pk}")
    if sec:
        source_parts.append(f"SECONDARY_KEYWORDS: {sec}")
    if t:
        source_parts.append(f"TITLE_DRAFT: {t}")
    if slug:
        source_parts.append(f"SLUG_DRAFT: {slug}")
    if tags:
        source_parts.append(f"TAGS_DRAFT: {tags}")
    if meta_description:
        source_parts.append(f"META_DESCRIPTION_DRAFT: {meta_description}")
    if outline_src:
        source_parts.append("OUTLINE_SOURCE:\n" + outline_src)
    if notes:
        source_parts.append("NOTES_SOURCE:\n" + notes)
    if src_text:
        source_parts.append(f"WEBSITE_SOURCE_URL: {src_url}")
        source_parts.append("WEBSITE_SOURCE_TEXT:\n" + src_text)
    if related_posts:
        rel_lines = []
        for i, item in enumerate(related_posts, start=1):
            t_rel = str(item.get("title") or "").strip()
            u_rel = str(item.get("url") or "").strip()
            if not t_rel or not u_rel:
                continue
            rel_lines.append(f"{i}. {t_rel} | {u_rel}")
        if rel_lines:
            source_parts.append("RELATED_ARTICLES:\n" + "\n".join(rel_lines))

    if content_brief and isinstance(content_brief, dict):
        try:
            from app.services.content_ai_brief import brief_to_llm_context

            brief_blob = brief_to_llm_context(content_brief)
            if brief_blob:
                source_parts.append("CONTENT_BRIEF (định hướng SEO, ưu tiên khi viết):\n" + brief_blob)
        except Exception:
            pass

    knowledge: dict[str, Any] | None = None
    if pk:
        try:
            from app.services.content_ai_knowledge_context import (
                build_outline_context_from_knowledge,
                get_relevant_knowledge_for_keyword,
            )

            knowledge = get_relevant_knowledge_for_keyword(
                pk,
                target_website=str(target_website or ""),
            )
            if knowledge and knowledge.get("found"):
                kb_ctx = build_outline_context_from_knowledge(knowledge)
                if kb_ctx:
                    source_parts.append("KNOWLEDGE_BASE:\n" + kb_ctx)
        except Exception:
            knowledge = None

    source_blob = "\n\n".join(source_parts).strip() or "SOURCE: (trống)"
    instructions = _build_instructions(
        field=field,
        target_word_count=wc_for_content if f0 == "content" else target_word_count,
        primary_keyword=pk,
        llm_mode=llm_mode,
        user_outline_present=user_outline_present,
        knowledge=knowledge,
    )

    f_early = (field or "").strip().lower()
    system = (
        "Bạn là trợ lý viết nội dung SEO tiếng Việt: chính xác, hữu ích (Helpful Content), E-E-A-T."
        " Chỉ dùng SOURCE; không bịa số liệu/giá; thiếu dữ liệu → «Cần bổ sung dữ liệu»."
        " Không nhồi từ khóa; không placeholder [CẦN XÁC NHẬN]."
    )
    if f_early == "content":
        system += (
            " Field content: chỉ HTML thuần (h1–h3, p, list, table, FAQ,"
            " gợi ý link nội/ngoài, JSON-LD schema); KHÔNG thêm section Checklist SEO trong bài;"
            " CẤM <img src=\"...\"> bịa — không chèn ảnh thật; dùng comment <!-- ảnh: mô tả --> nếu cần."
            " không markdown, không lời dẫn ngoài thẻ."
        )
    elif f_early in {"title", "meta_description", "slug", "outline_content"}:
        system += " Tuân thủ đúng giới hạn độ dài và định dạng field; trả về đúng 1 output, không giải thích."
    user = f"{instructions}\n\n=== SOURCE (chỉ dùng phần này) ===\n{source_blob}\n\n=== OUTPUT ==="

    if cfg.provider == "openai":
        msg = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        out = _openai_chat_completion(cfg=cfg, messages=msg, max_tokens=oai_mt, timeout_sec=api_timeout)
    else:
        out = _anthropic_messages(
            cfg=cfg, system=system, user=user, max_tokens=ant_mt, timeout_sec=api_timeout
        )
    if f0 == "content" and not str(out or "").strip():
        rescue_user = (
            "Bạn vừa trả output rỗng. Hãy trả về NGAY 1 bài HTML đầy đủ cho cùng SOURCE.\n"
            "Bắt buộc: 1 <h1>, ≥4 <h2>, keyword trong 100 từ đầu, FAQ,"
            " ít nhất 1 list/table, gợi ý internal/external link, JSON-LD schema. Không dùng thẻ <img> src giả."
            " Không thêm section Checklist SEO.\n"
            "Chỉ trả về HTML sạch, không markdown, không giải thích.\n"
            "\n=== SOURCE ===\n"
            f"{source_blob}\n"
            "\n=== OUTPUT (HTML) ==="
        )
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": rescue_user}],
                max_tokens=oai_mt,
                timeout_sec=api_timeout,
            )
        else:
            out = _anthropic_messages(
                cfg=cfg,
                system=system,
                user=rescue_user,
                max_tokens=ant_mt,
                timeout_sec=api_timeout,
            )

    # Enforce target word count for full content: if too short, ask the model to extend.
    # Best-effort; cap attempts to avoid runaway costs.
    f = (field or "").strip().lower()
    if f == "content" and wc_for_content is not None:
        wc = wc_for_content
        min_ok = int(wc * 0.95)
        max_ok = int(wc * 1.05)
        if _count_words_html(out) < min_ok:
            for _ in range(2):
                cur_words = _count_words_html(out)
                if cur_words >= min_ok:
                    break
                need = max(0, wc - cur_words)
                extender = (
                    "Bạn đã viết bài HTML ở dưới.\n"
                    f"Hiện khoảng {cur_words} từ, mục tiêu khoảng {wc} từ.\n"
                    f"Hãy MỞ RỘNG để thêm khoảng {need} từ (không cần chính xác tuyệt đối).\n"
                    "Ràng buộc bắt buộc:\n"
                    "- Không dùng [CẦN XÁC NHẬN] hay placeholder tương tự; không nhắc SEO/service page.\n"
                    "- Giữ nguyên nội dung đã có, CHỈ ĐƯỢC thêm tiếp vào cuối bài.\n"
                    "- Thêm tối thiểu: 1 H2 mới + 2 H3, 1 checklist chi tiết, và 1 FAQ (3–5 câu hỏi).\n"
                    "- Không lặp lại nguyên văn các đoạn đã viết.\n"
                    "- Trả về TOÀN BỘ HTML hoàn chỉnh (bao gồm cả phần cũ + phần mới); chỉ HTML, không markdown, không giải thích ngoài thẻ.\n"
                    "\n"
                    "=== BÀI HIỆN TẠI (HTML) ===\n"
                    f"{out}\n"
                    "\n"
                    "=== OUTPUT (HTML) ==="
                )
                if cfg.provider == "openai":
                    out = _openai_chat_completion(
                        cfg=cfg,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": extender},
                        ],
                        max_tokens=oai_mt,
                        timeout_sec=api_timeout,
                    )
                else:
                    out = _anthropic_messages(
                        cfg=cfg,
                        system=system,
                        user=extender,
                        max_tokens=ant_mt,
                        timeout_sec=api_timeout,
                    )
        # If too long, force concise rewrite first; then hard-cap trim as final guard.
        if _count_words_html(out) > max_ok:
            for _ in range(2):
                cur_words = _count_words_html(out)
                if cur_words <= max_ok:
                    break
                shrink_to = max(wc, max_ok - 20)
                compressor = (
                    "Bạn đã viết bài HTML ở dưới nhưng đang quá dài.\n"
                    f"Hiện khoảng {cur_words} từ; yêu cầu rút gọn còn khoảng {shrink_to} từ (không vượt quá {max_ok} từ).\n"
                    "Ràng buộc bắt buộc:\n"
                    "- Không dùng [CẦN XÁC NHẬN] hay placeholder; không nhắc SEO/service page.\n"
                    "- Giữ 1 H1 và hệ H2/H3 chính, giữ thông tin cốt lõi.\n"
                    "- Cắt bớt phần lặp, câu đệm, ví dụ thừa, đoạn quảng bá dài.\n"
                    "- Không thêm ý mới ngoài bài hiện tại.\n"
                    "- Trả về TOÀN BỘ HTML hoàn chỉnh sau khi rút gọn; chỉ HTML, không markdown, không giải thích ngoài thẻ.\n"
                    "\n"
                    "=== BÀI HIỆN TẠI (HTML) ===\n"
                    f"{out}\n"
                    "\n"
                    "=== OUTPUT (HTML) ==="
                )
                if cfg.provider == "openai":
                    out = _openai_chat_completion(
                        cfg=cfg,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": compressor},
                        ],
                        max_tokens=oai_mt,
                        timeout_sec=api_timeout,
                    )
                else:
                    out = _anthropic_messages(
                        cfg=cfg,
                        system=system,
                        user=compressor,
                        max_tokens=ant_mt,
                        timeout_sec=api_timeout,
                    )
            if _count_words_html(out) > max_ok:
                out = _trim_html_to_max_words(out, max_ok)

    if f == "content" and detect_search_intent(pk) == "transactional":
        # Validate transactional/actionability before finalizing; rewrite if needed.
        for _ in range(2):
            cur = extract_clean_html_fragment(_sanitize_mixed_style_phrases(str(out or "").strip()))
            gaps = _transactional_gaps(cur)
            if not gaps:
                out = cur
                break
            rewrite_user = (
                "Nội dung dưới đây CHƯA đạt intent transactional/action.\n"
                "Hãy viết lại TOÀN BỘ: thuyết phục khách đặt dịch vụ / liên hệ ngay (không giải thích SEO, không nhắc service page).\n"
                "BẮT BUỘC có đủ: (1) dịch vụ cung cấp, (2) dấu hiệu tin cậy, (3) hạng mục bao gồm, (4) chi phí/bảng giá, (5) liên hệ ngay.\n"
                "Không viết blog, không lý thuyết, không phản tư cá nhân; không dùng [CẦN XÁC NHẬN] hay placeholder.\n"
                "Chỉ trả về HTML sạch.\n"
                f"\nCác điểm thiếu:\n- " + "\n- ".join(gaps) + "\n"
                "\n=== HTML HIỆN TẠI ===\n"
                f"{cur}\n"
                "\n=== OUTPUT (HTML) ==="
            )
            if cfg.provider == "openai":
                out = _openai_chat_completion(
                    cfg=cfg,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": rewrite_user}],
                    max_tokens=oai_mt,
                    timeout_sec=api_timeout,
                )
            else:
                out = _anthropic_messages(
                    cfg=cfg,
                    system=system,
                    user=rewrite_user,
                    max_tokens=ant_mt,
                    timeout_sec=api_timeout,
                )

    if f == "content" and wc_for_content is not None:
        hard_min = max(300, int(wc_for_content * 0.75))
        cur_words = _count_words_html(out)
        if cur_words < hard_min:
            rewrite_long_user = (
                "Nội dung dưới đây đang quá ngắn so với mục tiêu.\n"
                f"Mục tiêu khoảng {wc_for_content} từ; bắt buộc viết lại đầy đủ tối thiểu {hard_min} từ.\n"
                "Ràng buộc bắt buộc:\n"
                "- Giữ đúng intent của từ khóa và bám OUTLINE_SOURCE nếu có.\n"
                "- Không viết dàn ý rỗng; mỗi H2 cần có phần thân bài cụ thể.\n"
                "- Bắt buộc có: sapo, >= 3 H2, có H3 phù hợp, 1 bảng, 1 checklist, 1 FAQ.\n"
                "- Chỉ trả về HTML sạch hoàn chỉnh, không markdown, không giải thích ngoài thẻ.\n"
                "\n=== HTML HIỆN TẠI ===\n"
                f"{out}\n"
                "\n=== OUTPUT (HTML) ==="
            )
            if cfg.provider == "openai":
                out = _openai_chat_completion(
                    cfg=cfg,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": rewrite_long_user}],
                    max_tokens=oai_mt,
                    timeout_sec=api_timeout,
                )
            else:
                out = _anthropic_messages(
                    cfg=cfg,
                    system=system,
                    user=rewrite_long_user,
                    max_tokens=ant_mt,
                    timeout_sec=api_timeout,
                )

    # Normalize single-line fields even if model outputs multiple lines.
    if f in {"title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords", "target_website"}:
        line = _first_line(out)
        if f in {"title", "meta_description"}:
            line = _strip_bracket_placeholders(line)
        return line
    out = str(out or "").strip()
    raw_out = out
    if f in {"content", "outline_content"}:
        out = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", out).strip()
        out = re.sub(r"\s*```\s*$", "", out).strip()
    if f == "content":
        out = _decode_html_entities_text(out)
        out_html = extract_clean_html_fragment(out)
        if not out_html and raw_out:
            out_html = _plain_text_to_html_fragment(
                text=_decode_html_entities_text(raw_out), title=t, primary_keyword=pk
            )
        if not out_html:
            seed = _clean_ws(notes or outline_src or t or pk)
            out_html = _plain_text_to_html_fragment(text=seed, title=t, primary_keyword=pk) if seed else ""
        out = out_html
        out = _strip_bracket_placeholders(out)
        out = _sanitize_mixed_style_phrases(out)
        if wc_for_content is not None:
            hard_min_final = max(300, int(wc_for_content * 0.95))
            hard_max_final = int(wc_for_content * 1.05)
            if _count_words_html(out) < hard_min_final:
                force_expand_user = (
                    "Bài HTML hiện tại còn quá ngắn so với mục tiêu.\n"
                    f"Yêu cầu viết lại TOÀN BỘ để đạt tối thiểu {hard_min_final} từ, mục tiêu khoảng {wc_for_content} từ.\n"
                    "Bắt buộc có sapo, các section H2/H3 đầy đủ nội dung, bảng, checklist và FAQ.\n"
                    "Chỉ trả về HTML sạch, không markdown, không giải thích.\n"
                    "\n=== HTML HIỆN TẠI ===\n"
                    f"{out}\n"
                    "\n=== OUTPUT (HTML) ==="
                )
                if cfg.provider == "openai":
                    out2 = _openai_chat_completion(
                        cfg=cfg,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": force_expand_user}],
                        max_tokens=oai_mt,
                        timeout_sec=api_timeout,
                    )
                else:
                    out2 = _anthropic_messages(
                        cfg=cfg,
                        system=system,
                        user=force_expand_user,
                        max_tokens=ant_mt,
                        timeout_sec=api_timeout,
                    )
                out2 = extract_clean_html_fragment(str(out2 or "").strip())
                if out2:
                    out = _sanitize_mixed_style_phrases(_strip_bracket_placeholders(out2))
            if _count_words_html(out) < hard_min_final:
                out = _ensure_min_words_html(
                    html=out,
                    min_words=hard_min_final,
                    keyword=pk,
                    title=t,
                )
            if _count_words_html(out) > hard_max_final:
                out = _trim_html_to_max_words(out, hard_max_final)
            from app.services.content_blockquote_postprocess import postprocess_content_blockquotes
            from app.services.content_ai_content_images import sanitize_invalid_content_images

            out = postprocess_content_blockquotes(out)
            out, _ = sanitize_invalid_content_images(out)
    elif f == "outline_content":
        out = _strip_bracket_placeholders(out)
    return out

