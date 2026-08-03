"""Style presets for AI Visual Content Studio (Content AI)."""

from __future__ import annotations

import re
from typing import Any

# Canonical preset ids (user-facing + API)
PRESET_SEO_3D_PREMIUM = "seo_3d_premium"
PRESET_FLAT_SAAS = "flat_saas"
PRESET_REALISTIC_BUSINESS = "realistic_business"
PRESET_YOUTUBE_THUMBNAIL = "youtube_thumbnail"
PRESET_FACEBOOK_ADS = "facebook_ads"
PRESET_COURSE_BANNER = "course_banner"

_STYLE_ALIASES: dict[str, str] = {
    "seo_3d": PRESET_SEO_3D_PREMIUM,
    "premium_3d_seo": PRESET_SEO_3D_PREMIUM,
    "3d": PRESET_SEO_3D_PREMIUM,
    "premium_3d": PRESET_SEO_3D_PREMIUM,
    "flat": PRESET_FLAT_SAAS,
    "flat_saas": PRESET_FLAT_SAAS,
    "flat_vector": PRESET_FLAT_SAAS,
    "vector": PRESET_FLAT_SAAS,
    "realistic": PRESET_REALISTIC_BUSINESS,
    "realistic_business": PRESET_REALISTIC_BUSINESS,
    "business": PRESET_REALISTIC_BUSINESS,
    "youtube": PRESET_YOUTUBE_THUMBNAIL,
    "youtube_thumbnail": PRESET_YOUTUBE_THUMBNAIL,
    "thumb": PRESET_YOUTUBE_THUMBNAIL,
    "facebook": PRESET_FACEBOOK_ADS,
    "facebook_ads": PRESET_FACEBOOK_ADS,
    "fb_ads": PRESET_FACEBOOK_ADS,
    "course": PRESET_COURSE_BANNER,
    "course_banner": PRESET_COURSE_BANNER,
    "banner": PRESET_COURSE_BANNER,
}

_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    PRESET_SEO_3D_PREMIUM: {
        "id": PRESET_SEO_3D_PREMIUM,
        "label_vi": "SEO 3D Premium",
        "description_vi": "Minh họa 3D cao cấp, workspace SaaS, phù hợp blog SEO kỹ thuật.",
        "rendering_en": (
            "High-end 3D illustration, soft global illumination, isometric or hero angle, "
            "modern SaaS marketing aesthetic, clean Vietnamese business context, sharp details, "
            "no clutter, no cartoon style."
        ),
        "default_aspect": "16:9",
        "allow_text_overlay": False,
    },
    PRESET_FLAT_SAAS: {
        "id": PRESET_FLAT_SAAS,
        "label_vi": "Flat SaaS",
        "description_vi": "Vector phẳng, icon rõ, palette hiện đại cho landing và blog.",
        "rendering_en": (
            "Clean flat vector illustration, simple geometric shapes, limited cohesive palette, "
            "editorial tech blog style, clear focal subject, generous negative space."
        ),
        "default_aspect": "16:9",
        "allow_text_overlay": False,
    },
    PRESET_REALISTIC_BUSINESS: {
        "id": PRESET_REALISTIC_BUSINESS,
        "label_vi": "Ảnh thật — Doanh nghiệp",
        "description_vi": "Photography phong cách corporate, ánh sáng tự nhiên.",
        "rendering_en": (
            "Photorealistic professional business photography, natural lighting, "
            "shallow depth of field, trustworthy corporate blog aesthetic, diverse professionals."
        ),
        "default_aspect": "16:9",
        "allow_text_overlay": False,
    },
    PRESET_YOUTUBE_THUMBNAIL: {
        "id": PRESET_YOUTUBE_THUMBNAIL,
        "label_vi": "YouTube Thumbnail",
        "description_vi": "Tương phản cao, một chủ thể, vùng trống cho tiêu đề (nếu bật chữ).",
        "rendering_en": (
            "Bold YouTube thumbnail composition, high contrast, single clear subject, "
            "dramatic lighting, saturated but professional colors, strong visual hierarchy, "
            "empty space on one side for title overlay when requested."
        ),
        "default_aspect": "16:9",
        "allow_text_overlay": True,
    },
    PRESET_FACEBOOK_ADS: {
        "id": PRESET_FACEBOOK_ADS,
        "label_vi": "Facebook Ads",
        "description_vi": "Creative quảng cáo, product/service focus, CTA-friendly layout.",
        "rendering_en": (
            "Facebook ad creative style, product or service hero, clean marketing layout, "
            "eye-catching color accents, mobile-first framing, professional brand-safe look."
        ),
        "default_aspect": "1:1",
        "allow_text_overlay": True,
    },
    PRESET_COURSE_BANNER: {
        "id": PRESET_COURSE_BANNER,
        "label_vi": "Course / Banner",
        "description_vi": "Banner khóa học, webinar, hero section website.",
        "rendering_en": (
            "Wide course or webinar hero banner, instructor or abstract learning motif, "
            "premium education marketing style, balanced composition for headline area."
        ),
        "default_aspect": "16:9",
        "allow_text_overlay": True,
    },
}


def normalize_style_preset(raw: str | None) -> str:
    key = re.sub(r"\s+", "_", str(raw or "").strip().lower())
    key = re.sub(r"[^a-z0-9_]", "", key)
    if key in _STYLE_PRESETS:
        return key
    return _STYLE_ALIASES.get(key, PRESET_SEO_3D_PREMIUM)


def get_style_preset(preset_id: str | None) -> dict[str, Any]:
    pid = normalize_style_preset(preset_id)
    return dict(_STYLE_PRESETS.get(pid) or _STYLE_PRESETS[PRESET_SEO_3D_PREMIUM])


def list_style_presets() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pid, meta in _STYLE_PRESETS.items():
        out.append(
            {
                "id": meta["id"],
                "label_vi": meta["label_vi"],
                "description_vi": meta["description_vi"],
                "default_aspect": meta.get("default_aspect") or "16:9",
                "allow_text_overlay": bool(meta.get("allow_text_overlay")),
            }
        )
    return out
