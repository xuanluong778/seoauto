"""
SEO content prompt blocks for Content AI (LLM field instructions).

Centralizes output requirements: title, meta, outline, full HTML article.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.content_draft_builder import (
    classify_content_intent,
    content_ai_extract_geo_tail,
    content_ai_has_local_service_signal,
    detect_search_intent,
)

_PRICE_IN_KB_RE = re.compile(r"\d[\d.,\s]*(?:đ|vnđ|vnd)\b", re.I)


def _kb_pricing_in_knowledge(knowledge: dict[str, Any] | None) -> bool:
    if not knowledge or not knowledge.get("found"):
        return False
    if knowledge.get("has_pricing_numbers"):
        return True
    blob = str((knowledge.get("sections") or {}).get("pricing") or "")
    return bool(_PRICE_IN_KB_RE.search(blob))


def _common_rules_block(*, detected_intent: str, local_line: str) -> str:
    return (
        "Bạn PHẢI tuân thủ các quy tắc:\n"
        "- CHỈ viết dựa trên dữ liệu thật trong SOURCE (website crawl, KNOWLEDGE_BASE, brief/outline người dùng).\n"
        "- KHÔNG bịa số liệu, case study, thương hiệu, chứng nhận, giá, cam kết nếu SOURCE không có.\n"
        "- Nếu KNOWLEDGE_BASE có trong SOURCE: bắt buộc dùng giá/SĐT/thông tin công ty từ đó; không ghi «Cần bổ sung dữ liệu» khi KB đã có.\n"
        "- Chỉ ghi «Cần bổ sung dữ liệu» khi chi tiết cụ thể hoàn toàn không có trong SOURCE.\n"
        "- Nội dung phải đúng ngành, đúng dịch vụ/sản phẩm của website trong SOURCE.\n"
        "- Không nhồi từ khóa; không viết chung chung; ưu tiên Helpful Content + E-E-A-T.\n"
        "- Viết tiếng Việt tự nhiên; ngôi «Tôi»/«Chúng tôi» khi phù hợp SOURCE.\n"
        "- Không giải thích SEO meta; không mở bài kiểu «trong bài viết này».\n"
        f"- Search intent (nội bộ): {detected_intent}.\n"
        + local_line
    )


def _geo_fidelity_block(primary_keyword: str) -> str:
    geo = content_ai_extract_geo_tail(primary_keyword)
    pk = re.sub(r"\s+", " ", (primary_keyword or "").strip())
    pk_line = ""
    if pk:
        pk_line = (
            f"\n- PRIMARY_KEYWORD nguyên văn: «{pk}» — title/meta phải chứa cụm này "
            "(chỉ viết hoa chữ cái đầu), không thay đổi địa danh.\n"
        )
    if not geo:
        return pk_line
    return (
        pk_line
        + f"\n- Địa danh trong PRIMARY_KEYWORD: «{geo}» — BẮT BUỘC giữ nguyên chính tả/ý nghĩa.\n"
        "- KHÔNG thay bằng Thủ Dầu Một, Dĩ An hay khu vực khác nếu PRIMARY_KEYWORD không nêu.\n"
        f"- Output phải chứa «{geo}» hoặc toàn bộ PRIMARY_KEYWORD.\n"
    )


def build_title_field_instructions(*, primary_keyword: str = "") -> str:
    return (
        "Nhiệm vụ: 1 SEO title (hiển thị SERP).\n"
        "Ràng buộc:\n"
        "- Dưới 60 ký tự (tối đa 60; ưu tiên 48–58).\n"
        "- Từ khóa chính đúng 1 lần, ưu tiên đầu tiêu đề.\n"
        "- Đúng intent, có lợi ích rõ; không giật tít.\n"
        + _geo_fidelity_block(primary_keyword)
        + "Trả về đúng 1 dòng, không giải thích."
    )


def build_meta_field_instructions(*, primary_keyword: str = "") -> str:
    return (
        "Nhiệm vụ: 1 meta description.\n"
        "Ràng buộc:\n"
        "- 140–160 ký tự (bắt buộc trong khoảng này nếu có thể).\n"
        "- Từ khóa chính đúng 1 lần + 1 biến thể/LSI tự nhiên.\n"
        "- Nêu lợi ích + đối tượng; không hứa quá mức.\n"
        + _geo_fidelity_block(primary_keyword)
        + "Trả về đúng 1 dòng."
    )


def build_outline_field_instructions(
    *,
    knowledge: dict[str, Any] | None = None,
    primary_keyword: str = "",
    outline_diversity_extra: str = "",
) -> str:
    from app.services.content_ai_outline_engine import classify_article_type

    pk = re.sub(r"\s+", " ", (primary_keyword or "").strip())
    article_type = classify_article_type(pk, knowledge=knowledge)
    base = (
        "Nhiệm vụ: dàn ý HTML (<h1>, <h2>, <h3>) hoặc Markdown (# H1, ## H2, ### H3).\n"
        "Ràng buộc:\n"
        f"- Loại bài (outline engine): {article_type} — cấu trúc H2 phải khác nhau giữa các keyword.\n"
        "- 1 H1; ≥6 H2 có ý nghĩa (heading phải chứa keyword/dịch vụ/địa danh, không chung chung).\n"
        "- Mỗi H2 có 2–5 H3 cụ thể (triệu chứng, quy trình, giá/yếu tố chi phí, FAQ, CTA…).\n"
        "- H2 đầu có từ khóa chính/biến thể; bám KNOWLEDGE_BASE nếu có trong SOURCE.\n"
        "- Ưu tiên KB: dịch vụ, giá, địa chỉ/khu vực, hotline, CTA, FAQ — không bịa nếu KB không có.\n"
        "- Bắt buộc có FAQ và CTA liên hệ cuối dàn ý (chỉ khi KB/SOURCE có thông tin liên hệ).\n"
        "Chỉ trả dàn ý."
    )
    if outline_diversity_extra:
        base += outline_diversity_extra
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


def build_secondary_keywords_field_instructions(*, primary_keyword: str = "") -> str:
    geo = content_ai_extract_geo_tail(primary_keyword)
    geo_line = ""
    if geo:
        geo_line = (
            f"- Ít nhất một nửa cụm phải chứa địa danh «{geo}» hoặc PRIMARY_KEYWORD; "
            "không bỏ địa danh để chỉ còn cụm chung chung.\n"
        )
    return (
        "Nhiệm vụ: từ khóa phụ (LSI/semantic) — KHÔNG phải meta description, KHÔNG phải đoạn giới thiệu.\n"
        "Ràng buộc:\n"
        "- 6–12 cụm từ khóa ngắn (2–5 từ mỗi cụm), phân tách bằng dấu phẩy.\n"
        "- Mỗi cụm là keyword/phrase tìm kiếm; không viết câu hoàn chỉnh; không dấu chấm cuối.\n"
        "- Bám PRIMARY_KEYWORD và SOURCE; không copy nguyên đoạn marketing từ website.\n"
        + geo_line
        + "- KHÔNG CTA, KHÔNG mô tả dịch vụ dài, KHÔNG «chúng tôi», «đội ngũ», «cam kết».\n"
        "Ví dụ đúng: đào tạo SEO online, khóa học SEO cơ bản, học SEO cho doanh nghiệp\n"
        "Trả về đúng 1 dòng danh sách keyword, không giải thích."
    )


def build_tags_field_instructions() -> str:
    return (
        "Nhiệm vụ: tags/nhãn bài viết (WordPress) — KHÔNG phải meta description.\n"
        "Ràng buộc:\n"
        "- 5–10 tag ngắn (1–3 từ mỗi tag), phân tách bằng dấu phẩy.\n"
        "- Tag là nhãn chủ đề; không câu mô tả; không quá 35 ký tự mỗi tag.\n"
        "- Không dấu chấm; không copy đoạn văn marketing.\n"
        "Ví dụ đúng: đào tạo SEO, SEO marketing, khóa học SEO\n"
        "Trả về đúng 1 dòng tag, không giải thích."
    )


def build_content_html_instructions(
    *,
    primary_keyword: str,
    target_word_count: int | None,
    llm_mode: str,
    user_outline_present: bool,
    knowledge: dict[str, Any] | None = None,
    outline_h2_count: int = 0,
    outline_h3_count: int = 0,
) -> str:
    pk = (primary_keyword or "").strip() or "(trống)"
    detected_intent = detect_search_intent(primary_keyword)
    content_intent = classify_content_intent(primary_keyword)
    has_location = content_ai_has_local_service_signal(primary_keyword)
    local_line = f"- Local signal: {'yes' if has_location else 'no'}.\n"

    training_note = ""
    if content_intent == "training":
        training_note = (
            "\n=== INTENT: ĐÀO TẠO / KHÓA HỌC ===\n"
            "- Viết theo góc độ chương trình học: lộ trình, module, thực hành, đối tượng học viên.\n"
            "- KHÔNG viết như dịch vụ sửa chữa, bảng giá sửa máy, hay CTA đặt lịch kỹ thuật viên.\n"
            "- CTA phù hợp: đăng ký học, nhận syllabus, tư vấn khóa học.\n"
            "- Bảng (nếu có) mô tả module/lộ trình — không phải bảng giá sửa chữa.\n"
        )
    elif content_intent == "info":
        training_note = (
            "\n=== INTENT: THÔNG TIN / HƯỚNG DẪN ===\n"
            "- Giải thích khái niệm, quy trình, checklist thực hành; tránh tone bán dịch vụ sửa chữa.\n"
        )

    wc = None
    if target_word_count is not None:
        try:
            wc = max(200, min(int(target_word_count), 20000))
        except (TypeError, ValueError):
            wc = None

    length_rule = ""
    if wc is not None:
        length_rule = (
            f"- BẮT BUỘC viết khoảng {wc} từ; sai lệch tối đa ±10% "
            f"(tối thiểu {int(wc * 0.90)} – tối đa {int(wc * 1.10)} từ).\n"
            f"- KHÔNG kết thúc bài khi chưa đạt ít nhất {int(wc * 0.90)} từ; mở rộng đủ H2/H3, ví dụ, FAQ, bảng.\n"
        )

    outline_note = ""
    if llm_mode == "auto":
        if user_outline_present:
            outline_note = (
                "- Mở rộng đầy đủ mọi H2/H3 từ OUTLINE_SOURCE; không chỉ lặp tiêu đề.\n"
                "- BẮT BUỘC viết nội dung cho TẤT CẢ mục outline, đúng thứ tự; KHÔNG dừng giữa chừng.\n"
                "- Mỗi H3 cần ít nhất 1 đoạn <p> hoặc list/table ngắn; có thể súc tích nhưng không bỏ sót mục.\n"
            )
            if outline_h2_count > 0:
                outline_note += (
                    f"- OUTLINE_SOURCE có {outline_h2_count} mục H2"
                    + (f" và {outline_h3_count} mục H3" if outline_h3_count > 0 else "")
                    + " — phải phủ hết trước khi kết thúc bài.\n"
                )
        else:
            outline_note = "- Tự dựng cấu trúc H2/H3 logic từ keyword + intent.\n"

    from app.services.content_seo_checklist import content_seo_checklist_snippet

    seo_snip = content_seo_checklist_snippet(max_chars=3500)

    kb_note = ""
    pricing_rule = "- Không bịa số liệu/giá; thiếu số trong SOURCE → «Cần bổ sung dữ liệu».\n"
    if knowledge and knowledge.get("found"):
        kb_note = (
            "\n=== KNOWLEDGE BASE (ưu tiên trong SOURCE) ===\n"
            "- Viết đúng thương hiệu, dịch vụ, khu vực, CTA từ KNOWLEDGE_BASE.\n"
            "- FAQ: tham khảo FAQ trong KB; không bịa câu trả lời có số liệu/giá.\n"
        )
        if knowledge.get("has_pricing_numbers") or _kb_pricing_in_knowledge(knowledge):
            pricing_rule = (
                "- Bảng giá: BẮT BUỘC lấy giá VNĐ từ === PRICING === trong KNOWLEDGE_BASE;"
                " KHÔNG ghi «Cần bổ sung dữ liệu» cho dịch vụ đã có giá trong KB.\n"
            )

    return (
        "You are an expert SEO content writer for Vietnamese readers.\n\n"
        + f"Primary keyword: {pk}\n"
        + f"Detected intent: {detected_intent}\n"
        + local_line
        + "\n"
        + "=== OUTPUT BÀI VIẾT (15 YÊU CẦU) ===\n"
        + "1) SEO Title (trong <title> nếu có — thường do field riêng): <60 ký tự, keyword đầu.\n"
        + "2) Meta description: field riêng 140–160 ký tự.\n"
        + "3) Slug: field riêng.\n"
        + "4) HTML: đúng 1 <h1> duy nhất (chứa keyword).\n"
        + "5) Outline rõ: ≥4 <h2>, <h3> phân cấp hợp lý.\n"
        + "6) Mở bài (<p> đầu): từ khóa chính trong 100 từ đầu (đếm text), tự nhiên.\n"
        + "7) Thân bài giải quyết đúng search intent; không lạc đề.\n"
        + "8) Rải từ khóa phụ/semantic (SECONDARY_KEYWORDS) tự nhiên trong các section.\n"
        + "9) Có ít nhất 1 <ul> hoặc <ol> và 1 <table> khi phù hợp chủ đề.\n"
        + "10) FAQ (<h2> Câu hỏi thường gặp) chỉ khi SOURCE/KB có câu hỏi–trả lời thật; không bịa FAQ.\n"
        + "11) Cuối bài: JSON-LD hợp lệ — BẮT BUỘC bọc trong <script type=\"application/ld+json\">...</script>; "
        + "KHÔNG in JSON thô ra ngoài thẻ HTML.\n"
        + "12) Gợi ý internal link: 2–4 chỗ dùng <!-- internal: anchor | slug-hint --> hoặc <a href=\"#internal-slug\"> nếu RELATED_ARTICLES có.\n"
        + "13) 1 external link uy tín (<a href rel=\"noopener\">) — Wikipedia, Google Search Central, .gov/.edu khi phù hợp.\n"
        + "14) Mỗi <h2> có <figure><figcaption>...</figcaption></figure> — KHÔNG thêm thẻ <img> hay URL ảnh; hệ thống tự chèn ảnh sau khi viết.\n"
        + "15) KHÔNG thêm section «Checklist SEO» hay danh sách kiểm tra vào cuối bài — checklist do hệ thống chạy riêng, không hiển thị cho người đọc.\n"
        + "\n"
        + "=== CHẤT LƯỢNG ===\n"
        + "- Không keyword stuffing; không câu sáo rỗng AI.\n"
        + pricing_rule
        + "- E-E-A-T: kinh nghiệm thực tế, ví dụ cụ thể, tác giả/nguồn khi hợp lý.\n"
        + "- Đoạn dài xen đoạn ngắn 2–3 câu; dễ đọc trên mobile.\n"
        + outline_note
        + length_rule
        + "\n"
        + "=== CẤU TRÚC HTML ===\n"
        + "- Chỉ HTML thuần: <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <table>, <blockquote>, <figure>, <a>, <script>.\n"
        + "- Không markdown, không code fence, không text ngoài thẻ.\n"
        + "- Technical SEO: dashboard audit, crawl, schema, CWV. Content SEO: viết bài, keyword research, outline.\n"
        + "\n"
        + (
            "=== CHECKLIST dự án (Content-seo.txt) ===\n" + seo_snip + "\n"
            if seo_snip.strip()
            else ""
        )
        + kb_note
        + training_note
        + "\n"
        + "Return ONLY the HTML article body.\n"
    )


def build_llm_field_instructions(
    *,
    field: str,
    target_word_count: int | None = None,
    primary_keyword: str = "",
    llm_mode: str = "auto",
    user_outline_present: bool = False,
    knowledge: dict[str, Any] | None = None,
    outline_h2_count: int = 0,
    outline_h3_count: int = 0,
    outline_diversity_extra: str = "",
) -> str:
    """Instruction block for generate_content_ai_suggestion (per field)."""
    f = (field or "").strip().lower()
    detected_intent = detect_search_intent(primary_keyword)
    has_location = content_ai_has_local_service_signal(primary_keyword)
    local_line = f"- Local signal detected: {'yes' if has_location else 'no'}.\n"
    common = _common_rules_block(detected_intent=detected_intent, local_line=local_line)

    if f == "title":
        return common + build_title_field_instructions(primary_keyword=primary_keyword)
    if f == "meta_description":
        return common + build_meta_field_instructions(primary_keyword=primary_keyword)
    if f == "outline_content":
        return common + build_outline_field_instructions(
            knowledge=knowledge,
            primary_keyword=primary_keyword,
            outline_diversity_extra=outline_diversity_extra,
        )
    if f == "slug":
        return common + build_slug_field_instructions()
    if f == "secondary_keywords":
        return common + build_secondary_keywords_field_instructions(primary_keyword=primary_keyword)
    if f == "tags":
        return common + build_tags_field_instructions()
    if f == "content":
        return common + build_content_html_instructions(
            primary_keyword=primary_keyword,
            target_word_count=target_word_count,
            llm_mode=llm_mode,
            user_outline_present=user_outline_present,
            knowledge=knowledge,
            outline_h2_count=outline_h2_count,
            outline_h3_count=outline_h3_count,
        )
    return common + "Nhiệm vụ: trả về nội dung ngắn gọn đúng định dạng field yêu cầu."
