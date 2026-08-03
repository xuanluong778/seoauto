"""AI agent — đề xuất chỉnh sửa SEO cho bài WordPress có sẵn (SEO Core 30)."""

from __future__ import annotations

import re
from typing import Any

_SEO_CORE_SYSTEM = (
    "Bạn là SEO Content Editor. Chỉ tối ưu bài viết theo SEO Core 30 yếu tố chưa đạt hoặc cảnh báo. "
    "Không viết lại theo cảm tính. Không thay đổi ý nghĩa chính. "
    "Không xóa shortcode, Gutenberg block, ảnh, link, schema, CTA. "
    "Giữ HTML sạch và hợp lệ. Bản mới phải có SEO Score cao hơn hoặc bằng bản cũ. "
    "CHỈ sửa phần liên quan tới yếu tố được liệt kê — không đụng phần đã đạt."
)


def _fallback_update(*, title: str, content: str, excerpt: str, keyword: str) -> dict[str, Any]:
    kw = (keyword or title or "").strip()
    new_title = title.strip()
    if kw and kw.lower() not in new_title.lower():
        new_title = f"{kw}: {new_title}"[:200]
    new_excerpt = excerpt or new_title[:160]
    return {
        "title": new_title,
        "content": content,
        "excerpt": new_excerpt,
        "meta_description": new_excerpt[:160],
        "summary": "Rule-based: chỉ tối ưu title/excerpt (LLM chưa cấu hình). Giữ nguyên HTML.",
        "notes": ["Giữ nguyên shortcode/block/ảnh/link/schema/CTA."],
    }


def _format_factor_list(factors: list[dict[str, Any]], heading: str) -> str:
    if not factors:
        return ""
    lines = [heading]
    for f in factors[:24]:
        fid = str(f.get("id") or "")
        label = str(f.get("label") or fid or "yếu tố")
        msg = str(f.get("message") or "")
        sug = str(f.get("suggestion") or "")
        hint = sug or msg
        lines.append(f"- [{fid}] {label}" + (f": {hint}" if hint else ""))
    return "\n".join(lines)


def generate_seo_update(
    *,
    user_id: int,
    title: str,
    content: str,
    excerpt: str = "",
    keyword: str = "",
    focus: str = "",
    seo_before: dict[str, Any] | None = None,
    failed_factors: list[dict[str, Any]] | None = None,
    warning_factors: list[dict[str, Any]] | None = None,
    use_system_llm: bool = False,
) -> dict[str, Any]:
    """
    Đề xuất title/content/excerpt — chỉ sửa yếu tố SEO Core failed/warning.
    """
    from app.services.llm_content_writer import (
        _anthropic_messages,
        _openai_chat_completion,
        _try_parse_json_object,
        load_llm_config,
        load_llm_config_admin,
    )

    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    failed = failed_factors or []
    warnings = warning_factors or []
    before_score = int((seo_before or {}).get("score") or 0)

    if not cfg:
        return _fallback_update(title=title, content=content, excerpt=excerpt, keyword=keyword)

    failed_txt = _format_factor_list(failed, "YẾU TỐ CHƯA ĐẠT (failed — bắt buộc sửa):")
    warn_txt = _format_factor_list(warnings, "YẾU TỐ CẢNH BÁO (warning — sửa nếu có thể, không phá nội dung):")

    user = (
        f"KEYWORD: {keyword}\n"
        f"FOCUS: {focus}\n"
        f"SEO_CORE_SCORE_TRƯỚC: {before_score}/100\n\n"
        f"{failed_txt}\n\n{warn_txt}\n\n"
        "Nếu không có yếu tố nào ở trên, KHÔNG sửa content — chỉ trả về bản gốc.\n\n"
        f"OLD_TITLE:\n{title}\n\nOLD_EXCERPT:\n{excerpt}\n\nOLD_CONTENT_HTML:\n{content[:14000]}\n\n"
        "Trả về JSON:\n"
        '{"title":"...","content":"...","excerpt":"...","meta_description":"...","summary":"...","notes":["..."]}\n'
        "summary: mô tả ngắn các yếu tố SEO Core đã sửa.\n"
        "content: HTML đầy đủ sau chỉnh sửa tối thiểu — giữ shortcode, <!-- wp: -->, img, a, schema, CTA."
    )

    try:
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": _SEO_CORE_SYSTEM}, {"role": "user", "content": user}],
                max_tokens=4000,
                timeout_sec=90,
            )
        else:
            out = _anthropic_messages(cfg=cfg, system=_SEO_CORE_SYSTEM, user=user)
        obj = _try_parse_json_object(out)
        if not obj:
            raise RuntimeError("invalid json")
        return {
            "title": str(obj.get("title") or title).strip(),
            "content": str(obj.get("content") or content).strip(),
            "excerpt": str(obj.get("excerpt") or excerpt).strip(),
            "meta_description": str(obj.get("meta_description") or excerpt or "")[:320],
            "summary": str(obj.get("summary") or "AI đã tối ưu theo SEO Core 30."),
            "notes": [str(x) for x in (obj.get("notes") or []) if str(x).strip()][:10],
        }
    except Exception:
        return _fallback_update(title=title, content=content, excerpt=excerpt, keyword=keyword)


def validate_preserved_markup(old_content: str, new_content: str) -> list[str]:
    """Cảnh báo nếu mất shortcode/block/ảnh/link/schema/CTA."""
    warnings: list[str] = []

    def count(pattern: str, text: str) -> int:
        return len(re.findall(pattern, text or "", flags=re.I | re.S))

    checks = (
        ("shortcode", r"\[[\w-]+"),
        ("wp-block", r"<!--\s*wp:"),
        ("img", r"<img\b"),
        ("link", r"<a\b"),
        ("schema", r'application/ld\+json|itemtype=|typeof=|"@type"'),
        ("cta", r'\bclass=["\'][^"\']*\b(cta|btn|button)\b'),
    )
    for label, pat in checks:
        o = count(pat, old_content)
        n = count(pat, new_content)
        if o > 0 and n < o:
            warnings.append(f"Có thể mất {label}: {o} → {n}")
    return warnings
