"""CAU assistant — generate structured patches (Auto Update only).

Does not modify Content AI writers. Uses CAU LLM helper only when needed.
Credit is charged by the router only after a successful LLM result.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.cau_assistant_patches import (
    ContentPatch,
    REFRESH_LEVELS,
    build_patch,
    build_refresh_plan,
)
from app.services.cau_block_model import ContentBlock, heading_level, parse_blocks, section_range, serialize_blocks


ACTION_CREDIT_EST: dict[str, int] = {
    "expand_1_2": 3,
    "expand_3_5": 5,
    "expand_100": 8,
    "expand_200": 12,
    "rewrite_heading": 5,
    "rewrite_heading_sync_section": 15,
    "add_example": 5,
    "add_steps": 5,
    "add_table": 4,
    "add_faq": 6,
    "add_cta": 3,
    "add_internal_link": 2,
    "selection_rewrite": 5,
    "selection_expand": 5,
    "selection_shorten": 4,
    "selection_simpler": 4,
    "selection_pro": 5,
    "selection_keyword": 5,
    "selection_spell": 3,
}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html or ""))).strip()


def _wrap_p(text: str) -> str:
    t = (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"<p>{t}</p>"


def _find(blocks: list[ContentBlock], block_id: str | None) -> tuple[int, ContentBlock | None]:
    if not block_id:
        return -1, None
    for i, b in enumerate(blocks):
        if b.block_id == block_id:
            return i, b
    return -1, None


def _estimate_seo(score: int | None, delta: int) -> int | None:
    if score is None:
        return None
    return max(0, min(100, int(score) + int(delta)))


def generate_template_patch(
    *,
    action: str,
    blocks: list[ContentBlock],
    target_block_id: str | None,
    selection_html: str = "",
    keyword: str = "",
    seo_score: int | None = None,
    link_url: str = "",
    link_anchor: str = "",
) -> ContentPatch:
    """Deterministic / template patches — no LLM, credit_estimate only (charge 0)."""
    idx, block = _find(blocks, target_block_id)
    kw = str(keyword or "").strip() or "từ khóa"
    credit = int(ACTION_CREDIT_EST.get(action, 5))

    if action.startswith("selection_") and selection_html:
        old = selection_html
        plain = _plain(old)
        if action == "selection_shorten":
            words = plain.split()
            new_plain = " ".join(words[: max(3, len(words) // 2)])
            new = _wrap_p(new_plain)
            reason = "Rút gọn đoạn đã chọn, giữ ý chính."
        elif action == "selection_simpler":
            new = _wrap_p(plain + " (diễn đạt dễ hiểu hơn, giữ nguyên ý).")
            reason = "Diễn đạt dễ hiểu hơn."
        elif action == "selection_pro":
            new = _wrap_p(plain + " — tối ưu giọng chuyên nghiệp, rõ ràng.")
            reason = "Tăng tính chuyên nghiệp."
        elif action == "selection_keyword":
            new = _wrap_p(plain if kw.lower() in plain.lower() else (plain + f" Liên quan {kw}."))
            reason = f"Thêm từ khóa «{kw}» tự nhiên."
        elif action == "selection_spell":
            new = old  # placeholder identity — LLM path improves
            reason = "Rà chính tả (bản mẫu; LLM sẽ cải thiện khi bật)."
        elif action == "selection_expand":
            new = old + _wrap_p(f"Bổ sung chi tiết về {kw} để làm rõ nội dung.")
            reason = "Viết thêm sau đoạn đã chọn."
        else:  # selection_rewrite
            new = _wrap_p(f"Phiên bản viết lại: {plain}")
            reason = "Viết lại đoạn đã chọn."
        return build_patch(
            action=action,
            old_html=old,
            new_html=new,
            target_block_id=target_block_id,
            reason=reason,
            seo_score_before=seo_score,
            seo_score_after_est=_estimate_seo(seo_score, 1),
            credit_estimate=credit,
            meta={"selection": True, "source": "template"},
        )

    if block is None:
        raise ValueError("Cần chọn heading/block đích.")

    if block.locked:
        raise ValueError("Block đã khóa AI.")

    old = block.current_content
    hl = heading_level(block)

    if action in {"expand_1_2", "expand_3_5", "expand_100", "expand_200"}:
        if action == "expand_1_2":
            add = _wrap_p(f"Bổ sung ngắn gọn về {kw}, giúp người đọc nắm ý chính.")
            reason = "Viết thêm 1–2 câu sau heading."
            delta = 1
        elif action == "expand_3_5":
            add = (
                _wrap_p(f"Phần này làm rõ {kw} theo góc nhìn thực tế.")
                + _wrap_p("Người dùng nên lưu ý điều kiện áp dụng và trường hợp ngoại lệ.")
                + _wrap_p("Tóm lại, nắm đúng nhu cầu sẽ giúp chọn hướng xử lý phù hợp.")
            )
            reason = "Viết thêm 3–5 câu."
            delta = 2
        elif action == "expand_100":
            add = "".join(
                _wrap_p(s)
                for s in [
                    f"Khi tìm hiểu {kw}, hãy bắt đầu từ mục tiêu và bối cảnh sử dụng.",
                    "Xác định ràng buộc về thời gian, ngân sách và kỹ thuật trước khi triển khai.",
                    "Đối chiếu với tiêu chí đánh giá rõ ràng để tránh quyết định cảm tính.",
                    "Ghi nhận phản hồi thực tế để tinh chỉnh nội dung và trải nghiệm.",
                ]
            )
            reason = "Mở rộng khoảng 100 từ."
            delta = 3
        else:
            add = "".join(
                _wrap_p(s)
                for s in [
                    f"Phân tích chuyên sâu về {kw} giúp độc giả hiểu bản chất vấn đề.",
                    "So sánh các phương án phổ biến, nêu ưu nhược điểm ngắn gọn.",
                    "Đề xuất lộ trình thực hiện theo từng bước, dễ kiểm chứng.",
                    "Bổ sung lưu ý rủi ro và cách giảm thiểu khi triển khai.",
                    "Kết nối với các mục liên quan trong bài để tăng chiều sâu nội dung.",
                    "Tóm tắt actionable checklist để độc giả áp dụng ngay.",
                ]
            )
            reason = "Mở rộng khoảng 200 từ."
            delta = 4
        return build_patch(
            action=action,
            old_html=old,
            new_html=add,
            target_block_id=block.block_id,
            reason=reason,
            seo_score_before=seo_score,
            seo_score_after_est=_estimate_seo(seo_score, delta),
            credit_estimate=credit,
            meta={"append_after_heading": True, "source": "template"},
        )

    if action == "rewrite_heading":
        title = _plain(old) or "Heading"
        lvl = hl or 2
        new = f"<h{lvl}>{title} — cập nhật rõ ràng hơn</h{lvl}>"
        return build_patch(
            action=action,
            old_html=old,
            new_html=new,
            target_block_id=block.block_id,
            reason="Viết lại heading, giữ cấp.",
            seo_score_before=seo_score,
            seo_score_after_est=_estimate_seo(seo_score, 2),
            credit_estimate=credit,
            meta={"source": "template"},
        )

    if action == "rewrite_heading_sync_section":
        start, end = section_range(blocks, idx)
        section = blocks[start:end]
        if any(b.locked for b in section):
            raise ValueError("Section có block khóa AI.")
        old_ser = serialize_blocks(section)
        title = _plain(section[0].current_content) if section else "Section"
        lvl = heading_level(section[0]) if section else 2
        body = "".join(
            b.current_content
            for b in section[1:]
            if b.block_type not in {"heading"}
        )
        new = f"<h{lvl or 2}>{title}</h{lvl or 2}>" + (body or _wrap_p(f"Nội dung đồng bộ về {kw}."))
        return build_patch(
            action=action,
            old_html=old_ser,
            new_html=new,
            target_block_id=block.block_id,
            reason="Viết lại heading và đồng bộ section (không đụng block khóa).",
            seo_score_before=seo_score,
            seo_score_after_est=_estimate_seo(seo_score, 3),
            credit_estimate=credit,
            meta={"source": "template"},
        )

    if action == "add_example":
        add = _wrap_p(f"Ví dụ: Với trường hợp {kw}, có thể áp dụng quy trình kiểm tra nhanh trong 3–5 phút.")
        reason = "Thêm ví dụ minh họa."
    elif action == "add_steps":
        add = "<ol><li>Xác định nhu cầu</li><li>Thu thập thông tin</li><li>Triển khai và đo kết quả</li></ol>"
        reason = "Thêm các bước thực hiện."
    elif action == "add_table":
        add = (
            "<table><thead><tr><th>Tiêu chí</th><th>Ghi chú</th></tr></thead>"
            f"<tbody><tr><td>{kw}</td><td>Nội dung tóm tắt</td></tr>"
            "<tr><td>Rủi ro</td><td>Cần kiểm tra thực tế</td></tr></tbody></table>"
        )
        reason = "Thêm bảng so sánh."
    elif action == "add_faq":
        add = (
            f"<h3>Câu hỏi thường gặp về {kw}</h3>"
            f"<p><strong>Hỏi:</strong> {kw} phù hợp khi nào?</p>"
            "<p><strong>Đáp:</strong> Khi đã rõ mục tiêu và ràng buộc triển khai.</p>"
        )
        reason = "Thêm FAQ."
    elif action == "add_cta":
        add = f'<p class="cta"><a href="#lien-he">Liên hệ tư vấn {kw}</a></p>'
        reason = "Thêm CTA."
    elif action == "add_internal_link":
        url = str(link_url or "").strip() or "#"
        anchor = str(link_anchor or kw).strip() or kw
        add = f'<p>Xem thêm: <a href="{url}">{anchor}</a>.</p>'
        reason = "Thêm internal link."
    else:
        raise ValueError(f"Action không hỗ trợ: {action}")

    return build_patch(
        action=action,
        old_html=old,
        new_html=add,
        target_block_id=block.block_id,
        reason=reason,
        seo_score_before=seo_score,
        seo_score_after_est=_estimate_seo(seo_score, 2),
        credit_estimate=credit,
        meta={"append_after_heading": True, "source": "template"},
    )


def generate_refresh_patches(
    *,
    level: str,
    blocks: list[ContentBlock],
    keyword: str = "",
    seo_score: int | None = None,
) -> tuple[dict[str, Any], list[ContentPatch]]:
    plan = build_refresh_plan(level=level, blocks=blocks, seo_score=seo_score)
    patches: list[ContentPatch] = []
    kw = str(keyword or "").strip() or "chủ đề"
    for item in plan.get("impacted") or []:
        bid = str(item.get("block_id") or "")
        idx, block = _find(blocks, bid)
        if idx < 0 or not block or block.locked:
            continue
        if level == "light":
            action = "expand_1_2"
        elif level == "deep":
            action = "expand_100"
        else:
            action = "expand_3_5"
        try:
            patches.append(
                generate_template_patch(
                    action=action,
                    blocks=blocks,
                    target_block_id=bid,
                    keyword=kw,
                    seo_score=seo_score,
                )
            )
        except ValueError:
            continue
        if level in {"standard", "deep"} and len(patches) < plan["sections_estimated"] + 1:
            try:
                patches.append(
                    generate_template_patch(
                        action="add_faq" if level == "standard" else "add_steps",
                        blocks=blocks,
                        target_block_id=bid,
                        keyword=kw,
                        seo_score=seo_score,
                    )
                )
            except ValueError:
                pass
    cfg = REFRESH_LEVELS.get(level) or REFRESH_LEVELS["standard"]
    plan["credit_estimate_total"] = sum(p.credit_estimate for p in patches)
    plan["credit_max"] = cfg["credit_max"]
    plan["patches_count"] = len(patches)
    return plan, patches


def try_llm_refine_patch(
    patch: ContentPatch,
    *,
    user_id: int | None,
    use_system_llm: bool,
    keyword: str = "",
) -> ContentPatch:
    """Optional LLM refine — on failure keep template patch. Caller charges only if source=llm."""
    try:
        from app.services.llm_content_writer import _cau_modal_llm_chat
    except Exception:
        return patch

    system = (
        "Bạn là biên tập SEO. Chỉ trả HTML đoạn cần chèn/thay (không trả cả bài, "
        "không markdown fence). Giữ thẻ HTML hợp lệ, không xóa link/ảnh nếu có trong input."
    )
    user = (
        f"Action: {patch.action}\nKeyword: {keyword}\n"
        f"OLD HTML:\n{patch.old_html[:4000]}\n\n"
        f"DRAFT NEW HTML:\n{patch.new_html[:4000]}\n\n"
        "Hãy cải thiện DRAFT NEW HTML, ngắn gọn, tự nhiên bằng tiếng Việt."
    )
    try:
        raw = _cau_modal_llm_chat(
            system=system,
            user=user,
            user_id=user_id,
            use_system_llm=use_system_llm,
            timeout_sec=60,
            word_target=200,
        )
        html = str(raw or "").strip()
        if html.startswith("```"):
            html = re.sub(r"^```(?:html)?\s*", "", html)
            html = re.sub(r"\s*```$", "", html)
        if not html or len(html) < 8:
            return patch
        refined = build_patch(
            action=patch.action,
            old_html=patch.old_html,
            new_html=html,
            target_block_id=patch.target_block_id,
            insert_index=patch.insert_index,
            reason=patch.reason + " (LLM)",
            seo_score_before=patch.seo_score_before,
            seo_score_after_est=patch.seo_score_after_est,
            credit_estimate=patch.credit_estimate,
            meta={**patch.meta, "source": "llm", "success": True},
        )
        return refined
    except Exception:
        patch.meta = dict(patch.meta)
        patch.meta["source"] = "template"
        patch.meta["llm_error"] = True
        return patch
