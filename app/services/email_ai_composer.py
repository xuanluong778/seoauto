"""AI Email Composer — subject/preheader/html/text. Does not alter Content AI writers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from app.services.email_html_sanitize import html_to_text, sanitize_email_html, validate_link_url

_LOG = logging.getLogger(__name__)

EMAIL_VARS = ("name", "plan", "expiry_date", "credit_balance", "email", "discount_code")

ComposeAction = Literal["generate", "rewrite", "shorter", "professional", "sales"]

TONES = frozenset({"friendly", "professional", "urgent", "warm", "sales"})


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise RuntimeError("AI không trả JSON hợp lệ.")
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise RuntimeError("AI không trả object JSON.")
    return data


def _cta_block(label: str, url: str) -> str:
    safe_label = label or "Mở ngay"
    try:
        href = validate_link_url(url) if url else "{{cta_url}}"
    except ValueError:
        href = "{{cta_url}}"
    return (
        f'<p style="margin:20px 0;text-align:center;">'
        f'<a href="{href}" style="display:inline-block;padding:12px 20px;'
        f'background:#16a34a;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;">'
        f"{safe_label}</a></p>"
    )


def compose_email(
    *,
    action: str = "generate",
    goal: str = "",
    segment: str = "active",
    tone: str = "professional",
    offer: str = "",
    cta_label: str = "Mở ngay",
    cta_url: str = "",
    current_subject: str = "",
    current_html: str = "",
    user_id: int | None = None,
) -> dict[str, str]:
    from app.services.llm_content_writer import _llm_chat_for_cfg, load_llm_config, load_llm_config_admin

    cfg = None
    if user_id:
        cfg = load_llm_config(user_id=int(user_id))
    if cfg is None:
        cfg = load_llm_config_admin()
    if cfg is None:
        raise RuntimeError("Chưa cấu hình LLM cho Email Composer.")

    act = str(action or "generate").strip().lower()
    if act not in {"generate", "rewrite", "shorter", "professional", "sales"}:
        act = "generate"
    tone_n = str(tone or "professional").strip().lower()
    if tone_n not in TONES:
        tone_n = "professional"

    vars_hint = ", ".join("{{" + v + "}}" for v in EMAIL_VARS)
    action_map = {
        "generate": "Viết email mới hoàn chỉnh.",
        "rewrite": "Viết lại email hiện tại, giữ ý chính, trau chuốt câu chữ.",
        "shorter": "Rút ngắn email hiện tại, còn khoảng 40–60% độ dài, giữ CTA.",
        "professional": "Viết lại theo giọng chuyên nghiệp, rõ ràng, ít cảm xúc.",
        "sales": "Viết lại thiên về bán hàng: lợi ích, urgency nhẹ, CTA mạnh.",
    }

    system = (
        "Bạn là email marketer của SEOAuto.vn (SaaS SEO). "
        "Chỉ trả về JSON thuần, không markdown. "
        "HTML email phải table-friendly, không script/iframe. "
        f"Được dùng biến: {vars_hint}. "
        "Luôn có đoạn mở đầu cá nhân hóa với {{name}}."
    )
    user = (
        f"Hành động: {action_map[act]}\n"
        f"Mục tiêu: {goal or 'nhắc gia hạn / giới thiệu tính năng SEOAuto'}\n"
        f"Segment: {segment}\n"
        f"Tone: {tone_n}\n"
        f"Ưu đãi: {offer or '(không)'}\n"
        f"CTA label: {cta_label or 'Mở ngay'}\n"
        f"CTA URL: {cta_url or 'https://seoauto.vn/account-billing'}\n"
        f"Subject hiện tại: {current_subject[:255]}\n"
        f"HTML hiện tại:\n{(current_html or '')[:6000]}\n\n"
        "JSON schema:\n"
        '{"subject":"...","preheader":"...","html_body":"<p>...</p>","text_body":"..."}\n'
        "subject <= 80 ký tự. preheader <= 120 ký tự. html_body là HTML fragment tiếng Việt."
    )

    raw = _llm_chat_for_cfg(
        cfg=cfg,
        system=system,
        user=user,
        max_tokens_oai=1200,
        max_tokens_ant=1200,
        timeout_sec=45,
    )
    data = _extract_json_object(raw)
    subject = str(data.get("subject") or "").strip()[:255]
    preheader = str(data.get("preheader") or "").strip()[:180]
    html_body = sanitize_email_html(str(data.get("html_body") or data.get("html") or ""))
    text_body = str(data.get("text_body") or data.get("text") or "").strip()
    if not html_body:
        html_body = sanitize_email_html(f"<p>{goal or 'Xin chào {{name}},'}</p>")
    if cta_label and "href=" not in html_body.lower():
        html_body += _cta_block(cta_label, cta_url)
    if not text_body:
        text_body = html_to_text(html_body)
    if not subject:
        subject = (goal or "Thông báo từ SEOAuto")[:80]
    if not preheader:
        preheader = text_body[:120]
    return {
        "subject": subject,
        "preheader": preheader,
        "html_body": html_body,
        "text_body": text_body[:4000],
        "provider": str(getattr(cfg, "logical_provider", None) or cfg.provider or "llm"),
    }
