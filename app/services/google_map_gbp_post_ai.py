"""Google Map SEO — AI tạo bài đăng Google Map."""

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

POST_TYPES = frozenset({
    "service_update",
    "promotion",
    "event",
    "news",
    "case_study",
})

CTA_TYPES = frozenset({"call", "book", "learn_more", "message"})

POST_TYPE_LABELS = {
    "service_update": "Cập nhật dịch vụ",
    "promotion": "Khuyến mãi",
    "event": "Sự kiện",
    "news": "Tin tức doanh nghiệp",
    "case_study": "Case study ngắn",
}

CTA_LABELS = {
    "call": "Gọi ngay",
    "book": "Đặt lịch",
    "learn_more": "Xem thêm",
    "message": "Nhắn tin",
}

_TYPE_HINTS = {
    "service_update": "Giới thiệu/cập nhật dịch vụ mới hoặc cải tiến.",
    "promotion": "Ưu đãi có thời hạn — không bịa % giảm nếu user không cung cấp.",
    "event": "Sự kiện/workshop/open day — không bịa ngày giờ nếu không có trong input.",
    "news": "Tin tức doanh nghiệp, thông báo ngắn.",
    "case_study": "Kết quả ngắn gọn — chỉ dùng số liệu user cung cấp trong mục tiêu.",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _llm_complete(cfg: LlmConfig, *, system: str, user: str) -> str:
    if cfg.provider == "openai":
        return _openai_chat_completion(
            cfg=cfg,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=1400,
            timeout_sec=60,
        )
    return _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=1400, timeout_sec=60)


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
    return {}


def generate_map_post(
    *,
    user_id: int,
    post_type: str,
    inp: dict[str, Any],
    business: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ptype = str(post_type or "").strip().lower()
    if ptype not in POST_TYPES:
        raise ValueError(f"post_type không hợp lệ: {post_type}")

    cta = str(inp.get("cta_type") or "learn_more").strip().lower()
    if cta not in CTA_TYPES:
        cta = "learn_more"

    cfg = load_llm_config(user_id)
    if not cfg:
        raise RuntimeError("Chưa cấu hình AI (API key LLM).")

    biz = business or {}
    source = "\n".join(
        p
        for p in (
            f"TÊN_DN: {_clean(str(biz.get('name') or inp.get('business_name') or ''))}",
            f"TỪ_KHÓA/DỊCH_VỤ: {_clean(str(inp.get('keywords') or ''))}",
            f"KHU_VỰC: {_clean(str(inp.get('locality') or biz.get('address') or ''))}",
            f"MỤC_TIÊU: {_clean(str(inp.get('goal') or ''))}",
            f"CTA: {CTA_LABELS[cta]}",
            f"LOẠI_BÀI: {POST_TYPE_LABELS[ptype]} — {_TYPE_HINTS[ptype]}",
        )
        if p.split(": ", 1)[-1]
    )

    system = (
        "Bạn viết bài đăng Google Business Profile (Local Post) tiếng Việt.\n"
        "QUY TẮC:\n"
        "- Chỉ dùng thông tin trong DỮ LIỆU — không bịa giá, % giảm, ngày sự kiện, số liệu.\n"
        "- title tối đa 58 ký tự; content 80–220 từ, súc tích.\n"
        "- image_suggestions: 2–4 gợi ý ảnh minh họa (không URL).\n"
        "- Trả JSON: {\"title\":\"\",\"content\":\"\",\"cta_label\":\"\",\"image_suggestions\":[],\"warnings\":[]}"
    )
    user = f"DỮ LIỆU:\n{source or '(trống)'}"

    raw = _llm_complete(cfg, system=system, user=user)
    parsed = _parse_json(raw)
    title = _clean(str(parsed.get("title") or ""))[:58]
    content = str(parsed.get("content") or "").strip()
    if not title or not content:
        raise RuntimeError("AI không trả đủ tiêu đề/nội dung — thử lại.")

    suggestions = parsed.get("image_suggestions")
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = [_clean(str(x)) for x in suggestions if str(x).strip()][:4]

    warnings = parsed.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(w).strip() for w in warnings if str(w).strip()][:3]

    cta_label = _clean(str(parsed.get("cta_label") or CTA_LABELS[cta]))[:120]

    return {
        "post_type": ptype,
        "post_type_label": POST_TYPE_LABELS[ptype],
        "title": title,
        "content": content,
        "cta_type": cta,
        "cta_label": cta_label,
        "image_suggestions": suggestions,
        "warnings": warnings,
    }
