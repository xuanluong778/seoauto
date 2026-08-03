"""
SEO content prompt blocks for Content AI (LLM field instructions).

Centralizes output requirements: title, meta, outline, full HTML article.
"""

from __future__ import annotations

from typing import Any

from app.services.content_draft_builder import (
    content_ai_has_local_service_signal,
    detect_search_intent,
)


def _common_rules_block(*, detected_intent: str, local_line: str) -> str:
    return (
        "Bạn PHẢI tuân thủ các quy tắc:\n"
        "- Chỉ dùng SOURCE; không bịa giá, số liệu, case study, cam kết riêng nếu SOURCE không có.\n"
        "- Thiếu dữ liệu cụ thể: ghi rõ «Cần bổ sung dữ liệu» (một cụm ngắn), không dùng [TODO]/[CẦN XÁC NHẬN].\n"
        "- Không nhồi từ khóa; không viết chung chung; ưu tiên Helpful Content + E-E-A-T.\n"
        "- Viết tiếng Việt tự nhiên; ngôi «Tôi»/«Chúng tôi» khi phù hợp; có ví dụ thực tế minh họa (không bịa số).\n"
        "- Không giải thích SEO meta; không nhắc «service page»; không mở bài kiểu «trong bài viết này».\n"
        f"- Search intent (nội bộ): {detected_intent}. Chọn một: transactional | commercial investigation | informational | navigational.\n"
        "- Keyword có địa phương → ưu tiên transactional.\n"
        + local_line
    )


def build_title_field_instructions() -> str:
    return (
        "Nhiệm vụ: 1 SEO title (hiển thị SERP).\n"
        "Ràng buộc:\n"
        "- Dưới 60 ký tự (tối đa 60; ưu tiên 48–58).\n"
        "- Từ khóa chính đúng 1 lần, ưu tiên đầu tiêu đề.\n"
        "- Đúng intent, có lợi ích rõ; không giật tít.\n"
        "Trả về đúng 1 dòng, không giải thích."
    )


def build_meta_field_instructions() -> str:
    return (
        "Nhiệm vụ: 1 meta description.\n"
        "Ràng buộc:\n"
        "- 140–160 ký tự (bắt buộc trong khoảng này nếu có thể).\n"
        "- Từ khóa chính đúng 1 lần + 1 biến thể/LSI tự nhiên.\n"
        "- Nêu lợi ích + đối tượng; không hứa quá mức.\n"
        "Trả về đúng 1 dòng."
    )


def build_outline_field_instructions(*, knowledge: dict[str, Any] | None = None) -> str:
    base = (
        "Nhiệm vụ: dàn ý HTML (<h1>, <h2>, <h3>) hoặc Markdown (# H1, ## H2, ### H3).\n"
        "Ràng buộc:\n"
        "- 1 H1; ≥6 H2 có ý nghĩa dịch vụ (không chỉ «định nghĩa / lợi ích / tiêu chí lựa chọn»).\n"
        "- Mỗi H2 có 2–5 H3 cụ thể (triệu chứng, quy trình, giá/yếu tố chi phí, FAQ, CTA…).\n"
        "- H2 đầu có từ khóa chính/biến thể; bám KNOWLEDGE_BASE nếu có trong SOURCE.\n"
        "- Bắt buộc có FAQ và CTA liên hệ cuối dàn ý.\n"
        "Chỉ trả dàn ý."
    )
    if not knowledge or not knowledge.get("found"):
        return base
    ot = str(knowledge.get("outline_type") or "general")
    brand = str(knowledge.get("brand_name") or "").strip()
    lines = [
        base,
        f"\n=== OUTLINE (Knowledge Base, type={ot}) ===\n",
        "- Ưu tiên mẫu OUTLINE PATTERN và các section trong KNOWLEDGE_BASE SOURCE.\n",
        "- Không bịa giá cố định, bảo hành, % cam kết nếu KB không nêu.\n",
    ]
    if brand:
        lines.append(f"- Thương hiệu: {brand}.\n")
    req = knowledge.get("required_outline_h2") or []
    if req:
        lines.append("- Các H2 bắt buộc (có thể đặt tên tự nhiên, giữ đúng ý):\n")
        for h2 in req:
            lines.append(f"  • {h2}\n")
    if ot == "local_service":
        lines.append(
            "- Local: phải có khu vực phục vụ, lỗi thường gặp, dịch vụ cụ thể, quy trình, "
            "yếu tố ảnh hưởng giá, bảo hành/cam kết (chỉ nếu KB có), FAQ, CTA.\n"
        )
    elif ot == "service":
        lines.append(
            "- Dịch vụ: ai nên dùng, hạng mục, lợi ích, quy trình, giá/báo giá, lý do chọn đơn vị, FAQ, CTA.\n"
        )
    return "".join(lines)


def build_slug_field_instructions() -> str:
    return (
        "Nhiệm vụ: slug URL chuẩn SEO (chữ thường, dấu gạch ngang, không dấu tiếng Việt).\n"
        "Trả về đúng 1 slug, không domain, không slash đầu."
    )


def build_content_html_instructions(
    *,
    primary_keyword: str,
    target_word_count: int | None,
    llm_mode: str,
    user_outline_present: bool,
    knowledge: dict[str, Any] | None = None,
) -> str:
    pk = (primary_keyword or "").strip() or "(trống)"
    detected_intent = detect_search_intent(primary_keyword)
    has_location = content_ai_has_local_service_signal(primary_keyword)
    local_line = f"- Local signal: {'yes' if has_location else 'no'}.\n"

    wc = None
    if target_word_count is not None:
        try:
            wc = max(200, min(int(target_word_count), 20000))
        except (TypeError, ValueError):
            wc = None

    length_rule = ""
    if wc is not None:
        length_rule = (
            f"- Độ dài ~{wc} từ (cho phép {int(wc * 0.92)}–{int(wc * 1.05)}).\n"
        )

    outline_note = ""
    if llm_mode == "auto":
        if user_outline_present:
            outline_note = (
                "- Mở rộng đầy đủ mọi H2/H3 từ OUTLINE_SOURCE; không chỉ lặp tiêu đề.\n"
            )
        else:
            outline_note = "- Tự dựng cấu trúc H2/H3 logic từ keyword + intent.\n"

    from app.services.content_seo_checklist import content_seo_checklist_snippet

    seo_snip = content_seo_checklist_snippet(max_chars=3500)

    kb_note = ""
    if knowledge and knowledge.get("found"):
        kb_note = (
            "\n=== KNOWLEDGE BASE (ưu tiên trong SOURCE) ===\n"
            "- Viết đúng thương hiệu, dịch vụ, khu vực, CTA từ KNOWLEDGE_BASE.\n"
            "- FAQ: tham khảo FAQ trong KB; không bịa câu trả lời có số liệu/giá.\n"
        )

    return (
        "You are an expert SEO content writer for Vietnamese readers.\n\n"
        f"Primary keyword: {pk}\n"
        f"Detected intent: {detected_intent}\n"
        + local_line
        + "\n"
        "=== OUTPUT BÀI VIẾT (15 YÊU CẦU) ===\n"
        "1) SEO Title (trong <title> nếu có — thường do field riêng): <60 ký tự, keyword đầu.\n"
        "2) Meta description: field riêng 140–160 ký tự.\n"
        "3) Slug: field riêng.\n"
        "4) HTML: đúng 1 <h1> duy nhất (chứa keyword).\n"
        "5) Outline rõ: ≥4 <h2>, <h3> phân cấp hợp lý.\n"
        "6) Mở bài (<p> đầu): từ khóa chính trong 100 từ đầu (đếm text), tự nhiên.\n"
        "7) Thân bài giải quyết đúng search intent; không lạc đề.\n"
        "8) Rải từ khóa phụ/semantic (SECONDARY_KEYWORDS) tự nhiên trong các section.\n"
        "9) Có ít nhất 1 <ul> hoặc <ol> và 1 <table> khi phù hợp chủ đề.\n"
        "10) Có section <h2> Câu hỏi thường gặp (FAQ) với ≥3 cặp hỏi–đáp ngắn.\n"
        "11) Cuối bài: khối «Gợi ý Schema» — <script type=\"application/ld+json\"> Article + FAQPage (JSON hợp lệ).\n"
        "12) Gợi ý internal link: 2–4 chỗ dùng <!-- internal: anchor | slug-hint --> hoặc <a href=\"#internal-slug\"> nếu RELATED_ARTICLES có.\n"
        "13) 1 external link uy tín (<a href rel=\"noopener\">) — Wikipedia, Google Search Central, .gov/.edu khi phù hợp.\n"
        "14) Mỗi <h2> có <figure><img alt=\"...\" src=\"\" /><figcaption>...</figcaption></figure> — alt SEO, có keyword/biến thể tự nhiên.\n"
        "15) KHÔNG thêm section «Checklist SEO» hay danh sách kiểm tra vào cuối bài — checklist do hệ thống chạy riêng, không hiển thị cho người đọc.\n"
        "\n"
        "=== CHẤT LƯỢNG ===\n"
        "- Không keyword stuffing; không câu sáo rỗng AI.\n"
        "- Không bịa số liệu/giá; thiếu số → «Cần bổ sung dữ liệu».\n"
        "- E-E-A-T: kinh nghiệm thực tế, ví dụ cụ thể, tác giả/nguồn khi hợp lý.\n"
        "- Đoạn dài xen đoạn ngắn 2–3 câu; dễ đọc trên mobile.\n"
        + outline_note
        + length_rule
        + "\n"
        "=== CẤU TRÚC HTML ===\n"
        "- Chỉ HTML thuần: <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <table>, <blockquote>, <figure>, <a>, <script>.\n"
        "- Không markdown, không code fence, không text ngoài thẻ.\n"
        "- Technical SEO: dashboard audit, crawl, schema, CWV. Content SEO: viết bài, keyword research, outline.\n"
        "\n"
        + (
            "=== CHECKLIST dự án (Content-seo.txt) ===\n" + seo_snip + "\n"
            if seo_snip.strip()
            else ""
        )
        + kb_note
        + "\n"
        "Return ONLY the HTML article body.\n"
    )


def build_llm_field_instructions(
    *,
    field: str,
    target_word_count: int | None = None,
    primary_keyword: str = "",
    llm_mode: str = "auto",
    user_outline_present: bool = False,
    knowledge: dict[str, Any] | None = None,
) -> str:
    """Instruction block for generate_content_ai_suggestion (per field)."""
    f = (field or "").strip().lower()
    detected_intent = detect_search_intent(primary_keyword)
    has_location = content_ai_has_local_service_signal(primary_keyword)
    local_line = f"- Local signal detected: {'yes' if has_location else 'no'}.\n"
    common = _common_rules_block(detected_intent=detected_intent, local_line=local_line)

    if f == "title":
        return common + build_title_field_instructions()
    if f == "meta_description":
        return common + build_meta_field_instructions()
    if f == "outline_content":
        return common + build_outline_field_instructions(knowledge=knowledge)
    if f == "slug":
        return common + build_slug_field_instructions()
    if f == "content":
        return common + build_content_html_instructions(
            primary_keyword=primary_keyword,
            target_word_count=target_word_count,
            llm_mode=llm_mode,
            user_outline_present=user_outline_present,
            knowledge=knowledge,
        )
    return common + "Nhiệm vụ: trả về nội dung ngắn gọn phù hợp field (tags/secondary_keywords…)."
