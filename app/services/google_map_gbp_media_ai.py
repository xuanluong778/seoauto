"""Google Map SEO — AI caption & tên file ảnh SEO local."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.services.llm_content_writer import (
    LlmConfig,
    _anthropic_messages,
    _openai_chat_completion,
    load_llm_config,
)

MEDIA_TYPES = frozenset({
    "logo",
    "cover",
    "storefront",
    "interior",
    "product_service",
    "team",
    "customer_case",
})

MEDIA_TYPE_LABELS = {
    "logo": "Logo",
    "cover": "Ảnh bìa",
    "storefront": "Ảnh mặt tiền",
    "interior": "Ảnh nội thất",
    "product_service": "Ảnh sản phẩm/dịch vụ",
    "team": "Ảnh đội ngũ",
    "customer_case": "Ảnh khách hàng/case thực tế",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _slug_part(text: str) -> str:
    s = unicodedata.normalize("NFD", str(text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:48] or "anh"


def suggest_seo_filename(
    *,
    media_type: str,
    keywords: str,
    locality: str,
    ext: str = ".jpg",
) -> str:
    ptype = str(media_type or "product_service").strip().lower()
    kw = _slug_part(keywords or MEDIA_TYPE_LABELS.get(ptype, "dich-vu"))
    loc = _slug_part(locality or "dia-phuong")
    type_part = _slug_part(MEDIA_TYPE_LABELS.get(ptype, ptype))
    suffix = ext if ext.startswith(".") else f".{ext}"
    return f"{kw}-{loc}-{type_part}{suffix}"


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
    return {}


def generate_media_caption(
    *,
    user_id: int,
    media_type: str,
    inp: dict[str, Any],
    business: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mtype = str(media_type or "").strip().lower()
    if mtype not in MEDIA_TYPES:
        raise ValueError(f"media_type không hợp lệ: {media_type}")

    cfg = load_llm_config(user_id)
    if not cfg:
        raise RuntimeError("Chưa cấu hình AI (API key LLM).")

    biz = business or {}
    source = "\n".join(
        p
        for p in (
            f"TÊN_DN: {_clean(str(biz.get('name') or inp.get('business_name') or ''))}",
            f"TỪ_KHÓA: {_clean(str(inp.get('keywords') or ''))}",
            f"KHU_VỰC: {_clean(str(inp.get('locality') or biz.get('address') or ''))}",
            f"LOẠI_ẢNH: {MEDIA_TYPE_LABELS[mtype]}",
            f"GHI_CHÚ: {_clean(str(inp.get('note') or ''))}",
        )
        if p.split(": ", 1)[-1]
    )

    system = (
        "Bạn viết caption/mô tả ảnh Google Business Profile tiếng Việt.\n"
        "QUY TẮC:\n"
        "- 1–2 câu, tối đa 120 từ; có từ khóa địa phương tự nhiên.\n"
        "- Không bịa giá, cam kết, số liệu không có trong dữ liệu.\n"
        "- Trả JSON: {\"caption\":\"\",\"warnings\":[]}"
    )
    raw = _llm_complete(cfg, system=system, user=f"DỮ LIỆU:\n{source or '(trống)'}")
    parsed = _parse_json(raw)
    caption = str(parsed.get("caption") or "").strip()
    if not caption:
        raise RuntimeError("AI không trả caption — thử lại.")

    warnings = parsed.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(w).strip() for w in warnings if str(w).strip()][:3]

    ext = str(inp.get("ext") or ".jpg")
    filename = suggest_seo_filename(
        media_type=mtype,
        keywords=str(inp.get("keywords") or ""),
        locality=str(inp.get("locality") or biz.get("address") or ""),
        ext=ext,
    )

    return {
        "media_type": mtype,
        "media_type_label": MEDIA_TYPE_LABELS[mtype],
        "caption": caption,
        "suggested_filename": filename,
        "warnings": warnings,
    }
