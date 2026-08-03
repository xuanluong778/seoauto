"""Google Map SEO — AI tối ưu hồ sơ GBP (grounded, không bịa thông tin)."""

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

CONTENT_TYPES = frozenset({
    "business_description",
    "main_services",
    "service_description",
    "faq",
    "local_intro",
})

TONE_LABELS = {
    "professional": "Chuyên nghiệp, đáng tin cậy",
    "friendly": "Thân thiện, gần gũi",
    "concise": "Ngắn gọn, súc tích",
    "enthusiastic": "Nhiệt tình, tích cực",
}

_TYPE_INSTRUCTIONS: dict[str, str] = {
    "business_description": (
        "Viết mô tả doanh nghiệp cho Google Business Profile, tối đa 750 ký tự, "
        "có từ khóa địa phương tự nhiên nếu có địa điểm trong dữ liệu."
    ),
    "main_services": (
        "Liệt kê 4–8 dịch vụ chính (mỗi dòng một dịch vụ, có dấu • hoặc -), "
        "chỉ dựa trên dịch vụ user cung cấp."
    ),
    "service_description": (
        "Viết mô tả chi tiết cho MỘT dịch vụ (80–180 từ), nêu lợi ích và phạm vi "
        "dựa trên tên dịch vụ và thông tin doanh nghiệp đã cho."
    ),
    "faq": (
        "Tạo 4–6 cặp FAQ (Câu hỏi / Trả lời ngắn) phù hợp ngành và khu vực, "
        "chỉ dùng thông tin đã cung cấp — không bịa giá, cam kết, số năm kinh nghiệm."
    ),
    "local_intro": (
        "Viết đoạn giới thiệu theo ngành + địa phương (120–220 từ), "
        "nhấn mạnh phục vụ tại khu vực đã cho."
    ),
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _build_source_blob(inp: dict[str, Any], *, from_gbp: dict[str, Any] | None = None) -> str:
    parts: list[str] = []
    mapping = [
        ("business_name", "TÊN_DOANH_NGHIỆP"),
        ("industry", "NGÀNH_NGHỀ"),
        ("locality", "KHU_VỰC"),
        ("website", "WEBSITE"),
        ("main_services", "DỊCH_VỤ_CHÍNH"),
        ("service_name", "TÊN_DỊCH_VỤ_CẦN_MÔ_TẢ"),
        ("tone", "GIỌNG_VĂN"),
    ]
    for key, label in mapping:
        val = _clean(str(inp.get(key) or ""))
        if val:
            parts.append(f"{label}: {val}")
    if from_gbp:
        gbp_parts: list[str] = []
        for k, label in (
            ("name", "Tên trên GBP"),
            ("category", "Danh mục GBP"),
            ("address", "Địa chỉ GBP"),
            ("website", "Website GBP"),
        ):
            v = _clean(str(from_gbp.get(k) or ""))
            if v:
                gbp_parts.append(f"{label}: {v}")
        if gbp_parts:
            parts.append("DỮ_LIỆU_ĐỒNG_BỘ_GBP:\n" + "\n".join(gbp_parts))
    return "\n".join(parts).strip() or "DỮ_LIỆU: (trống — chỉ viết khung chung, không bịa tên/giá/cam kết)"


def _llm_complete(cfg: LlmConfig, *, system: str, user: str, max_tokens: int = 1800) -> str:
    if cfg.provider == "openai":
        return _openai_chat_completion(
            cfg=cfg,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            timeout_sec=60,
        )
    return _anthropic_messages(
        cfg=cfg,
        system=system,
        user=user,
        max_tokens=max_tokens,
        timeout_sec=60,
    )


def _parse_json_response(raw: str) -> dict[str, Any]:
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
    return {"content": text, "warnings": []}


def generate_profile_content(
    *,
    content_type: str,
    inp: dict[str, Any],
    user_id: int,
    from_gbp: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctype = str(content_type or "").strip().lower()
    if ctype not in CONTENT_TYPES:
        raise ValueError(f"content_type không hợp lệ: {content_type}")

    if ctype == "service_description" and not _clean(str(inp.get("service_name") or "")):
        raise ValueError("Cần nhập tên dịch vụ để tạo mô tả.")

    cfg = load_llm_config(user_id)
    if not cfg:
        raise RuntimeError("Chưa cấu hình AI (API key LLM). Vào Tài khoản → API hoặc liên hệ admin.")

    tone_key = str(inp.get("tone") or "professional").strip().lower()
    tone_label = TONE_LABELS.get(tone_key, TONE_LABELS["professional"])
    inp = dict(inp)
    inp["tone"] = tone_label

    source = _build_source_blob(inp, from_gbp=from_gbp)
    task = _TYPE_INSTRUCTIONS[ctype]

    system = (
        "Bạn là chuyên gia Local SEO / Google Business Profile cho thị trường Việt Nam.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- CHỈ dùng thông tin trong khối DỮ LIỆU — không bịa tên, địa chỉ, giá, số năm kinh nghiệm, "
        "giải thưởng, số khách hàng, cam kết cụ thể.\n"
        "- Nếu thiếu dữ liệu, viết trung tính, không điền placeholder kiểu [Tên công ty].\n"
        "- Không dùng tiếng Anh trừ thuật ngữ ngành phổ biến.\n"
        "- Trả về JSON hợp lệ: {\"content\": \"...\", \"warnings\": [\"...\"]}\n"
        "- warnings: ghi chú phần nào thiếu dữ liệu (nếu có), tối đa 3 mục."
    )
    if ctype == "faq":
        system += (
            '\n- content là JSON string chứa mảng [{"q":"...","a":"..."}] — không markdown.'
        )
    user = f"LOẠI_NỘI_DUNG: {ctype}\nNHIỆM_VỤ: {task}\n\nDỮ LIỆU:\n{source}"

    raw = _llm_complete(cfg, system=system, user=user, max_tokens=2200 if ctype == "faq" else 1200)
    parsed = _parse_json_response(raw)
    content = str(parsed.get("content") or "").strip()
    if not content:
        raise RuntimeError("AI không trả nội dung — thử lại.")

    if ctype == "business_description" and len(content) > 750:
        content = content[:747].rstrip() + "…"

    warnings = parsed.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(w).strip() for w in warnings if str(w).strip()][:3]

    return {
        "content_type": ctype,
        "content": content,
        "warnings": warnings,
        "char_count": len(content),
    }
