"""Google Map SEO — AI phản hồi review GBP."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm_content_writer import (
    LlmConfig,
    _anthropic_messages,
    _openai_chat_completion,
    load_llm_config,
)

REPLY_TONES = frozenset({"professional", "friendly", "apology", "thankful"})

TONE_INSTRUCTIONS = {
    "professional": "Giọng chuyên nghiệp, lịch sự, đáng tin cậy.",
    "friendly": "Giọng thân thiện, gần gũi nhưng vẫn lịch sự.",
    "apology": "Giọng xin lỗi chân thành và đề xuất xử lý khiếu nại — phù hợp review tiêu cực.",
    "thankful": "Giọng cảm ơn khách hàng, ghi nhận phản hồi tích cực.",
}


def _llm_complete(cfg: LlmConfig, *, system: str, user: str) -> str:
    if cfg.provider == "openai":
        return _openai_chat_completion(
            cfg=cfg,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=600,
            timeout_sec=45,
        )
    return _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=600, timeout_sec=45)


def _parse_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"reply": text}


def suggest_tone_for_stars(stars: int) -> str:
    if stars <= 2:
        return "apology"
    if stars >= 4:
        return "thankful"
    return "professional"


def generate_review_reply(
    *,
    user_id: int,
    review: dict[str, Any],
    business: dict[str, Any],
    tone: str,
) -> dict[str, Any]:
    tone_key = str(tone or "").strip().lower()
    if tone_key not in REPLY_TONES:
        tone_key = suggest_tone_for_stars(int(review.get("stars") or 0))

    cfg = load_llm_config(user_id)
    if not cfg:
        raise RuntimeError("Chưa cấu hình AI (API key LLM).")

    biz_name = str(business.get("name") or business.get("business_name") or "").strip()
    stars = int(review.get("stars") or 0)
    system = (
        "Bạn viết phản hồi công khai cho review Google Business Profile (tiếng Việt).\n"
        "QUY TẮC:\n"
        "- Không bịa ưu đãi, số điện thoại, email, giờ mở cửa nếu không có trong DỮ LIỆU.\n"
        "- Không tranh cãi, không đổ lỗi khách.\n"
        "- Tối đa 350 từ, không markdown.\n"
        "- Trả JSON: {\"reply\": \"...\", \"warnings\": [\"...\"]}"
    )
    user = (
        f"GIỌNG_VĂN: {TONE_INSTRUCTIONS[tone_key]}\n"
        f"DOANH_NGHIỆP: {biz_name or '(không rõ)'}\n"
        f"NGÀNH: {business.get('industry') or business.get('category') or ''}\n"
        f"KHU_VỰC: {business.get('locality') or business.get('address') or ''}\n"
        f"REVIEW_SAO: {stars}\n"
        f"TÁC_GIẢ: {review.get('author') or ''}\n"
        f"NỘI_DUNG_REVIEW:\n{review.get('text') or ''}"
    )
    raw = _llm_complete(cfg, system=system, user=user)
    parsed = _parse_json(raw)
    reply = str(parsed.get("reply") or "").strip()
    if not reply:
        raise RuntimeError("AI không trả phản hồi — thử lại.")
    if len(reply) > 4096:
        reply = reply[:4093].rstrip() + "…"
    warnings = parsed.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    if stars <= 2:
        warnings = list(dict.fromkeys([*warnings, "Review 1–2 sao — nên xử lý ưu tiên và mời khách liên hệ riêng."]))[:4]
    return {"reply": reply, "tone": tone_key, "warnings": warnings[:4]}
