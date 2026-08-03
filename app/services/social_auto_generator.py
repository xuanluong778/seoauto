"""Social Auto — AI variant generation (Facebook, Zalo OA, Web 2.0)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm_content_writer import (
    _anthropic_messages,
    _openai_chat_completion,
    _try_parse_json_object,
    load_llm_config,
)


def _fallback_variants(
    *,
    source_title: str,
    source_content: str,
    keyword: str,
    target_url: str,
    tone: str,
    cta: str,
) -> dict[str, dict[str, str]]:
    """Rule-based fallback when LLM is unavailable."""
    title = source_title or keyword or "Bài viết mới"
    snippet = (source_content or "")[:280].strip()
    if not snippet:
        snippet = f"Chia sẻ nhanh về {keyword or title}."
    link = target_url or ""
    cta_txt = cta or "Xem thêm chi tiết tại bài viết gốc."

    return {
        "facebook": {
            "title": title[:120],
            "content": (
                f"{snippet}\n\n"
                f"{cta_txt}"
                + (f"\n\n🔗 {link}" if link else "")
            ).strip(),
            "hashtags": f"#{re.sub(r'\\W+', '', keyword or 'SEO')[:30]} #SEOAuto",
            "cta": cta_txt,
        },
        "zalo": {
            "title": title[:80],
            "content": (
                f"Xin chào! {title}\n"
                f"{snippet[:180]}\n"
                f"{cta_txt}"
                + (f" → {link}" if link else "")
            ).strip(),
            "hashtags": "",
            "cta": cta_txt,
        },
        "web20": {
            "title": f"{title} — góc nhìn ngắn",
            "content": (
                f"Chủ đề hôm nay: {keyword or title}.\n\n"
                f"{snippet}\n\n"
                f"Điểm khác với bài gốc: tập trung góc nhìn thực hành, không lặp nguyên văn.\n\n"
                f"{cta_txt}"
                + (f"\n\nTham khảo: {link}" if link else "")
            ).strip(),
            "hashtags": keyword or "",
            "cta": cta_txt,
        },
    }


def generate_facebook_variant(
    *,
    user_id: int,
    source_title: str,
    source_content: str,
    keyword: str,
    target_url: str,
    tone: str = "chuyên gia",
    cta: str = "",
) -> dict[str, str]:
    """Chỉ tạo biến thể Facebook Fanpage."""
    all_variants = generate_social_variants(
        user_id=user_id,
        source_title=source_title,
        source_content=source_content,
        keyword=keyword,
        target_url=target_url,
        tone=tone,
        cta=cta,
    )
    return all_variants.get("facebook") or {}


def generate_social_variants(
    *,
    user_id: int,
    source_title: str,
    source_content: str,
    keyword: str,
    target_url: str,
    tone: str = "chuyên gia",
    cta: str = "",
) -> dict[str, dict[str, str]]:
    """
    Return 3 platform variants: facebook, zalo, web20.
    Each: title, content, hashtags, cta.
    """
    cfg = load_llm_config(user_id)
    if not cfg:
        return _fallback_variants(
            source_title=source_title,
            source_content=source_content,
            keyword=keyword,
            target_url=target_url,
            tone=tone,
            cta=cta,
        )

    src = (source_content or "")[:6000].strip()
    system = (
        "Bạn là copywriter social media tiếng Việt cho SEOAuto. "
        "Tạo biến thể bài đăng từ nội dung gốc — tự nhiên, không spam link, không nhồi từ khóa."
    )
    user = (
        f"TIÊU ĐỀ GỐC: {source_title}\n"
        f"TỪ KHÓA: {keyword}\n"
        f"URL BÀI CHÍNH (chỉ nhắc 1 lần, không spam): {target_url}\n"
        f"GIỌNG VĂN: {tone}\n"
        f"CTA GỢI Ý: {cta}\n\n"
        f"NỘI DUNG GỐC:\n{src}\n\n"
        "Yêu cầu từng kênh:\n"
        "- facebook: giọng tự nhiên, 2–4 đoạn ngắn, emoji vừa phải, hashtag 2–4.\n"
        "- zalo: ngắn gọn, thân thiện, ≤ 400 ký tự nội dung chính.\n"
        "- web20: viết lại khác bài gốc (spin), 2–3 đoạn, không copy nguyên văn.\n\n"
        "Trả về ĐÚNG 1 JSON object:\n"
        "{\n"
        '  "facebook": {"title":"...","content":"...","hashtags":"...","cta":"..."},\n'
        '  "zalo": {"title":"...","content":"...","hashtags":"...","cta":"..."},\n'
        '  "web20": {"title":"...","content":"...","hashtags":"...","cta":"..."}\n'
        "}\n"
        "Không thêm markdown hay giải thích."
    )

    try:
        if cfg.provider == "openai":
            out = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=2000,
                timeout_sec=60,
            )
        else:
            out = _anthropic_messages(cfg=cfg, system=system, user=user)
        obj = _try_parse_json_object(out)
        if not obj:
            raise RuntimeError("invalid json")
        result: dict[str, dict[str, str]] = {}
        for plat in ("facebook", "zalo", "web20"):
            block = obj.get(plat) if isinstance(obj.get(plat), dict) else {}
            result[plat] = {
                "title": str(block.get("title") or source_title or "")[:500],
                "content": str(block.get("content") or "")[:20000],
                "hashtags": str(block.get("hashtags") or "")[:500],
                "cta": str(block.get("cta") or cta or "")[:1000],
            }
        if not any(v.get("content") for v in result.values()):
            raise RuntimeError("empty variants")
        return result
    except Exception:
        return _fallback_variants(
            source_title=source_title,
            source_content=source_content,
            keyword=keyword,
            target_url=target_url,
            tone=tone,
            cta=cta,
        )


def generate_web20_article(
    *,
    user_id: int,
    source_title: str,
    source_content: str,
    keyword: str,
    target_url: str,
    main_site_url: str = "",
    tone: str = "chuyên gia",
) -> dict[str, Any]:
    """Phiên bản Web 2.0 HTML — viết lại, không copy 100% bài gốc."""
    main_link = (main_site_url or target_url or "").strip()
    variants = generate_social_variants(
        user_id=user_id,
        source_title=source_title,
        source_content=source_content,
        keyword=keyword,
        target_url=target_url,
        tone=tone,
        cta="",
    )
    block = variants.get("web20") or {}
    plain = str(block.get("content") or "")
    title = str(block.get("title") or source_title or keyword or "Bài viết Web 2.0")[:500]
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:200] or "bai-viet-web20"
    excerpt = plain[:280].strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", plain) if p.strip()]
    if not paragraphs:
        paragraphs = [plain or f"Chủ đề: {keyword or title}"]
    html_parts = [f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs[:12]]
    link_count = 0
    if main_link and link_count < 2:
        html_parts.append(f'<p><a href="{main_link}" rel="nofollow noopener">Xem thêm tại website chính</a></p>')
        link_count += 1
    html_content = "\n".join(html_parts)
    tags_raw = str(block.get("hashtags") or keyword or "")
    tags = [t.strip().lstrip("#") for t in re.split(r"[,#\s]+", tags_raw) if t.strip()][:8]
    if keyword and keyword not in tags:
        tags.insert(0, keyword.strip()[:40])
    return {
        "title": title,
        "slug": slug,
        "excerpt": excerpt,
        "html_content": html_content,
        "tags": tags[:8],
        "category": "",
        "wp_status": "draft",
        "main_site_url": main_link,
    }
