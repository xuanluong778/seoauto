"""
Sequential section writer for Content AI Single Writer.
Viết từng H2 theo word budget; bổ sung heading thiếu mà không viết lại toàn bài.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from bs4 import BeautifulSoup

from app.services.content_ai_outline_engine import (
    MIN_WORDS_PER_H2,
    OutlineSection,
    allocate_section_word_budgets,
    extract_h1_from_outline,
    intro_word_budget,
    normalize_outline_heading,
    parse_outline_sections,
)

_LOG = logging.getLogger(__name__)

LlmCallFn = Callable[..., str]


def _count_words_html(html: str) -> int:
    from app.services.llm_content_writer import _count_words_html as _wc

    return _wc(html)


def _truncate(text: str, max_chars: int) -> str:
    t = str(text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3].rstrip() + "..."


def _extract_clean(html: str) -> str:
    from app.services.llm_content_writer import extract_clean_html_fragment

    return extract_clean_html_fragment(str(html or "").strip()) or str(html or "").strip()


def _section_words_in_html(html: str, h2_title: str) -> int:
    """Đếm từ trong section bắt đầu từ H2 tương ứng."""
    raw = str(html or "").strip()
    if not raw:
        return 0
    try:
        soup = BeautifulSoup(raw, "html.parser")
        target = normalize_outline_heading(h2_title)
        for h2 in soup.find_all("h2"):
            if normalize_outline_heading(h2.get_text(" ", strip=True)) != target:
                if not (target in normalize_outline_heading(h2.get_text(" ", strip=True))):
                    continue
            parts: list[str] = []
            for sib in h2.next_siblings:
                if getattr(sib, "name", None) == "h2":
                    break
                if getattr(sib, "name", None) in {"h1", "h2"}:
                    break
                if hasattr(sib, "get_text"):
                    parts.append(sib.get_text(" ", strip=True))
                elif isinstance(sib, str):
                    parts.append(sib.strip())
            text = " ".join(p for p in parts if p)
            return len(re.findall(r"\S+", text))
    except Exception:
        pass
    return 0


def build_section_write_prompt(
    *,
    section: OutlineSection,
    section_index: int,
    total_sections: int,
    primary_keyword: str,
    title: str,
    source_blob: str,
    is_intro: bool = False,
    intro_budget: int = 0,
) -> str:
    h3_block = ""
    if section.h3s:
        h3_block = "\nH3 bắt buộc (đúng thứ tự, mỗi H3 ≥1 đoạn <p> hoặc list):\n" + "\n".join(
            f"- {h}" for h in section.h3s
        )
    intro_line = ""
    if is_intro:
        intro_line = (
            f"\n- Viết <h1> (1 lần duy nhất) + đoạn mở bài (~{intro_budget} từ), "
            f"keyword trong 100 từ đầu.\n"
        )
    draft_block = ""
    if hasattr(section, "raw_content") and section.raw_content:
        joined = "\n".join(section.raw_content).strip()
        if joined:
            draft_block = f"\nDự thảo nội dung/bảng biểu từ outline:\n{joined}\n"
    return (
        f"Viết PHẦN {section_index + 1}/{total_sections} của bài HTML SEO tiếng Việt.\n"
        f"PRIMARY_KEYWORD: {primary_keyword}\n"
        f"TITLE_DRAFT: {title}\n"
        f"H2 section này: «{section.h2}»\n"
        f"Mục tiêu ~{section.word_budget} từ cho section (tối thiểu {max(MIN_WORDS_PER_H2, section.word_budget - 30)}).\n"
        + intro_line
        + h3_block
        + draft_block
        + "\nRàng buộc:\n"
        "- CHỈ trả HTML cho section này"
        + (" (gồm <h1> + mở bài + <h2> section đầu)" if is_intro else " (bắt đầu bằng <h2>, không lặp <h1>)")
        + ".\n"
        "- Dùng KNOWLEDGE_BASE trong SOURCE cho giá, hotline, địa chỉ, CTA, FAQ — không bịa.\n"
        "- Chuyển đổi bảng biểu dự thảo từ outline (nếu có) thành bảng HTML (<table>) đầy đủ các cột và dòng dữ liệu, giữ nguyên thông tin giá/thông số từ outline.\n"
        "- Không markdown; không giải thích ngoài thẻ HTML.\n"
        "- Mỗi H3 phải có nội dung cụ thể, không chỉ 1 câu.\n"
        "\n=== SOURCE ===\n"
        + _truncate(source_blob, 12000)
        + "\n\n=== OUTPUT (HTML section) ==="
    )


def build_missing_section_prompt(
    *,
    missing_h2: str,
    missing_h3s: list[str],
    word_budget: int,
    primary_keyword: str,
    source_blob: str,
    existing_html: str,
    raw_content: list[str] = None,
) -> str:
    h3_line = ""
    if missing_h3s:
        h3_line = "\nH3 cần có:\n" + "\n".join(f"- {x}" for x in missing_h3s)
    draft_block = ""
    if raw_content:
        joined = "\n".join(raw_content).strip()
        if joined:
            draft_block = f"\nDự thảo nội dung/bảng biểu từ outline:\n{joined}\n"
    return (
        "Bài HTML hiện tại THIẾU section outline sau. Chỉ viết BỔ SUNG section này.\n"
        f"H2 thiếu: «{missing_h2}»\n"
        f"Mục tiêu ~{word_budget} từ.\n"
        + h3_line
        + draft_block
        + "\n- Trả về HTML CHỈ gồm section bổ sung (<h2> + nội dung), không lặp lại phần đã có.\n"
        "- Dùng KNOWLEDGE_BASE; không bịa thông tin doanh nghiệp.\n"
        "- Chuyển đổi bảng biểu dự thảo từ outline (nếu có) thành bảng HTML (<table>) đầy đủ các cột và dòng dữ liệu, giữ nguyên thông tin giá/thông số từ outline.\n"
        f"\nPRIMARY_KEYWORD: {primary_keyword}\n"
        "\n=== HTML HIỆN TẠI (tham khảo, không copy) ===\n"
        + _truncate(existing_html, 8000)
        + "\n\n=== SOURCE ===\n"
        + _truncate(source_blob, 6000)
        + "\n\n=== OUTPUT (HTML section bổ sung) ==="
    )


def merge_section_fragments(intro_html: str, section_htmls: list[str]) -> str:
    parts = [p.strip() for p in [intro_html, *section_htmls] if p and p.strip()]
    return "\n".join(parts).strip()


def append_html_fragment(base: str, fragment: str) -> str:
    b = str(base or "").strip()
    f = _extract_clean(fragment)
    if not f:
        return b
    if not b:
        return f
    # Chèn trước JSON-LD / script nếu có
    m = re.search(r"(<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>)", b, re.I)
    if m:
        idx = m.start()
        return (b[:idx].rstrip() + "\n" + f + "\n" + b[idx:]).strip()
    return (b + "\n" + f).strip()


def _find_incomplete_section_h2(html: str) -> tuple[str, list[str]] | None:
    """Tìm H2 chứa đoạn cuối bị cắt ngang (không phải H2 cuối tài liệu)."""
    raw = str(html or "").strip()
    if not raw:
        return None
    try:
        soup = BeautifulSoup(raw, "html.parser")
        blocks = list(soup.find_all(["p", "li", "td", "blockquote"]))
        for tag in reversed(blocks):
            txt = tag.get_text(" ", strip=True)
            if not txt or len(txt) < 12:
                continue
            if re.search(r"[.!?…\"')\]}]$", txt):
                continue
            # Tìm H2 gần nhất phía trước tag này
            h2_el = tag.find_previous("h2")
            if not h2_el:
                return None
            h2_text = h2_el.get_text(" ", strip=True)
            missing_h3s: list[str] = []
            return h2_text, missing_h3s
    except Exception:
        pass
    return None


def _html_has_incomplete_tail(html: str) -> bool:
    """Phát hiện bài bị cắt ngang giữa câu ở đoạn cuối."""
    return _find_incomplete_section_h2(html) is not None


def _missing_h3_in_last_section(html: str, outline: str) -> tuple[str, list[str]] | None:
    """H2 cuối cùng trong HTML còn thiếu H3 so với outline."""
    sections = parse_outline_sections(outline)
    if not sections:
        return None
    try:
        soup = BeautifulSoup(str(html or ""), "html.parser")
        h2_tags = soup.find_all("h2")
        if not h2_tags:
            return None
        last_h2_text = h2_tags[-1].get_text(" ", strip=True)
        last_key = normalize_outline_heading(last_h2_text)
        sec = None
        for s in sections:
            nk = normalize_outline_heading(s.h2)
            if nk == last_key or last_key in nk or nk in last_key:
                sec = s
                break
        if not sec or not sec.h3s:
            return None
        found_h3: set[str] = set()
        capture = False
        for el in soup.find_all(True):
            name = str(el.name or "").lower()
            if name == "h2":
                capture = normalize_outline_heading(el.get_text(" ", strip=True)) in {
                    last_key,
                    normalize_outline_heading(sec.h2),
                } or last_key in normalize_outline_heading(el.get_text(" ", strip=True))
                continue
            if capture and name == "h2":
                break
            if capture and name == "h3":
                found_h3.add(normalize_outline_heading(el.get_text(" ", strip=True)))
        missing = [
            h3
            for h3 in sec.h3s
            if normalize_outline_heading(h3) not in found_h3
            and not any(
                normalize_outline_heading(h3) in f or f in normalize_outline_heading(h3) for f in found_h3
            )
        ]
        if missing:
            return sec.h2, missing
    except Exception:
        pass
    return None


def _repair_incomplete_tail_section(
    *,
    html: str,
    outline: str,
    total_wc: int,
    primary_keyword: str,
    source_blob: str,
    system: str,
    llm_call: LlmCallFn,
) -> str:
    """Hoàn thiện section bị cắt ngang hoặc thiếu H3."""
    out = str(html or "").strip()
    if not out:
        return out
    inc = _find_incomplete_section_h2(out)
    h3_gap = _missing_h3_in_last_section(out, outline)
    if not inc and not h3_gap:
        return out

    sections = allocate_section_word_budgets(total_wc, parse_outline_sections(outline))
    sec_map = {normalize_outline_heading(s.h2): s for s in sections}
    target_h2 = ""
    missing_h3s: list[str] = []
    if inc:
        target_h2 = inc[0]
    elif h3_gap:
        target_h2, missing_h3s = h3_gap

    if not target_h2:
        return out

    sec = sec_map.get(normalize_outline_heading(target_h2))
    if not sec:
        for s in sections:
            if normalize_outline_heading(s.h2) in normalize_outline_heading(target_h2):
                sec = s
                break
    budget = sec.word_budget if sec else max(MIN_WORDS_PER_H2, total_wc // 8)
    h3s = missing_h3s or (sec.h3s if sec else [])

    draft_block = ""
    if sec and hasattr(sec, "raw_content") and sec.raw_content:
        joined = "\n".join(sec.raw_content).strip()
        if joined:
            draft_block = f"\nDự thảo nội dung/bảng biểu từ outline:\n{joined}\n"

    prompt = (
        "Section HTML cuối bài bị CẮT NGANG giữa câu hoặc thiếu H3.\n"
        f"H2 cần hoàn thiện: «{target_h2}»\n"
        f"Mục tiêu ~{budget} từ cho phần bổ sung.\n"
        + (("\nH3 còn thiếu:\n" + "\n".join(f"- {x}" for x in h3s)) if h3s else "")
        + draft_block
        + "\n- Trả HTML CHỈ phần bổ sung từ H2 này (có thể gồm lại <h2> + đủ H3 + đoạn hoàn chỉnh).\n"
        "- Chuyển đổi bảng biểu dự thảo từ outline (nếu có) thành bảng HTML (<table>) đầy đủ các cột và dòng dữ liệu, giữ nguyên thông tin giá/thông số từ outline.\n"
        "- Hoàn tất mọi câu; không dừng giữa chừng.\n"
        "- Không lặp nguyên văn toàn bộ bài.\n"
        f"\nPRIMARY_KEYWORD: {primary_keyword}\n"
        "\n=== HTML HIỆN TẠI (tham khảo) ===\n"
        + _truncate(out, 9000)
        + "\n\n=== SOURCE ===\n"
        + _truncate(source_blob, 6000)
        + "\n\n=== OUTPUT (HTML bổ sung/hoàn thiện section) ==="
    )
    frag = _extract_clean(llm_call(system=system, user=prompt))
    if frag:
        try:
            soup = BeautifulSoup(out, "html.parser")
            target_key = normalize_outline_heading(target_h2)
            target_h2_el = None
            for h2 in soup.find_all("h2"):
                ht = normalize_outline_heading(h2.get_text(" ", strip=True))
                if ht == target_key or target_key in ht or ht in target_key:
                    target_h2_el = h2
                    break
            if target_h2_el is not None:
                for sib in list(target_h2_el.next_siblings):
                    try:
                        sib.extract()
                    except Exception:
                        if hasattr(sib, "decompose"):
                            sib.decompose()
                target_h2_el.decompose()
                body = soup.body
                out = "".join(str(x) for x in (body.contents if body else soup.contents)).strip()
        except Exception:
            pass
        out = append_html_fragment(out, frag)
        _LOG.info("content_ai_section_write repaired tail h2=%s", target_h2[:80])
    return out


def ensure_full_outline_html(
    *,
    html: str,
    outline: str,
    total_wc: int,
    primary_keyword: str,
    source_blob: str,
    system: str,
    llm_call: LlmCallFn,
    max_passes: int = 5,
) -> str:
    """
    Cổng cuối: bắt buộc đủ mọi H2 outline + không cắt ngang câu cuối.
    """
    from app.services.content_ai_outline_engine import outline_h2_coverage

    out = str(html or "").strip()
    ol = str(outline or "").strip()
    if not ol or not out:
        return out
    sections = parse_outline_sections(ol)
    if len(sections) < 1:
        return out
    secs = allocate_section_word_budgets(total_wc, sections)

    for pass_i in range(max(1, int(max_passes))):
        cov = outline_h2_coverage(ol, out)
        missing = list(cov.get("missing_sections") or [])
        incomplete = _html_has_incomplete_tail(out)
        if cov["ratio"] >= 1.0 and not incomplete and not missing:
            _LOG.info(
                "content_ai_outline_complete ok passes=%s covered=%s/%s",
                pass_i,
                cov.get("covered"),
                cov.get("total"),
            )
            break

        # Sửa section đang cắt ngang trước — tránh append H2 mới rồi xóa nhầm section cuối.
        if incomplete or _missing_h3_in_last_section(out, ol):
            out = _repair_incomplete_tail_section(
                html=out,
                outline=ol,
                total_wc=total_wc,
                primary_keyword=primary_keyword,
                source_blob=source_blob,
                system=system,
                llm_call=llm_call,
            )

        cov = outline_h2_coverage(ol, out)
        missing = list(cov.get("missing_sections") or [])
        if missing or cov["ratio"] < 1.0:
            out = repair_outline_coverage(
                html=out,
                outline=ol,
                sections=secs,
                total_wc=total_wc,
                primary_keyword=primary_keyword,
                source_blob=source_blob,
                system=system,
                llm_call=llm_call,
            )

        cov_after = outline_h2_coverage(ol, out)
        if cov_after["ratio"] >= 1.0 and not _html_has_incomplete_tail(out):
            break

    final = outline_h2_coverage(ol, out)
    if final.get("ratio", 0) < 1.0:
        _LOG.warning(
            "content_ai_outline_incomplete covered=%s/%s missing=%s",
            final.get("covered"),
            final.get("total"),
            (final.get("missing_sections") or [])[:8],
        )
    return out


def write_content_by_outline_sections(
    *,
    outline: str,
    total_wc: int,
    primary_keyword: str,
    title: str,
    source_blob: str,
    system: str,
    llm_call: LlmCallFn,
) -> str | None:
    """
    Viết bài theo từng H2. Trả None nếu outline không parse được → caller fallback 1-shot.
    """
    sections = parse_outline_sections(outline)
    if len(sections) < 2:
        _LOG.info("content_ai_section_write skip: outline_sections=%s", len(sections))
        return None

    sections = allocate_section_word_budgets(total_wc, sections)
    h1 = extract_h1_from_outline(outline) or title or primary_keyword
    intro_b = intro_word_budget(total_wc)

    _LOG.info(
        "content_ai_section_write start sections=%s total_wc=%s intro_budget=%s",
        len(sections),
        total_wc,
        intro_b,
    )

    fragments: list[str] = []
    for i, sec in enumerate(sections):
        is_intro = i == 0
        prompt = build_section_write_prompt(
            section=sec,
            section_index=i,
            total_sections=len(sections),
            primary_keyword=primary_keyword,
            title=title or h1,
            source_blob=source_blob,
            is_intro=is_intro,
            intro_budget=intro_b if is_intro else 0,
        )
        if is_intro:
            prompt = prompt.replace(
                f"H2 section này: «{sec.h2}»",
                f"H2 section đầu: «{sec.h2}» (sau <h1> và mở bài)",
            )
        frag = ""
        for attempt in range(2):
            try:
                raw = llm_call(system=system, user=prompt)
                frag = _extract_clean(raw)
                if frag:
                    break
            except Exception as exc:
                _LOG.warning(
                    "content_ai_section_write fail idx=%s h2=%s attempt=%s err=%s",
                    i,
                    sec.h2[:60],
                    attempt + 1,
                    str(exc)[:200],
                )
        if not frag:
            _LOG.warning("content_ai_section_write empty section idx=%s h2=%s", i, sec.h2[:60])
            continue
        fragments.append(frag)

    if not fragments:
        return None

    html = merge_section_fragments("", fragments)

    return ensure_full_outline_html(
        html=html,
        outline=outline,
        total_wc=total_wc,
        primary_keyword=primary_keyword,
        source_blob=source_blob,
        system=system,
        llm_call=llm_call,
    )


def repair_outline_coverage(
    *,
    html: str,
    outline: str,
    sections: list[OutlineSection],
    total_wc: int,
    primary_keyword: str,
    source_blob: str,
    system: str,
    llm_call: LlmCallFn,
) -> str:
    from app.services.content_ai_outline_engine import outline_h2_coverage

    out = str(html or "").strip()
    sec_map = {normalize_outline_heading(s.h2): s for s in sections}

    for _pass in range(5):
        cov = outline_h2_coverage(outline, out)
        if cov["ratio"] >= 1.0 and not cov.get("missing_sections"):
            break
        missing_titles = list(cov.get("missing_sections") or [])
        if not missing_titles:
            break

        for mh_title in missing_titles:
            key = normalize_outline_heading(mh_title)
            sec = sec_map.get(key)
            if not sec:
                sec = OutlineSection(
                    h2=mh_title,
                    h3s=[],
                    word_budget=max(MIN_WORDS_PER_H2, total_wc // max(len(sections), 4)),
                )
            prompt = build_missing_section_prompt(
                missing_h2=sec.h2,
                missing_h3s=sec.h3s,
                word_budget=sec.word_budget,
                primary_keyword=primary_keyword,
                source_blob=source_blob,
                existing_html=out,
                raw_content=getattr(sec, "raw_content", None),
            )
            frag = _extract_clean(llm_call(system=system, user=prompt))
            if frag:
                out = append_html_fragment(out, frag)
                _LOG.info("content_ai_section_write patched h2=%s", sec.h2[:80])

    final_cov = outline_h2_coverage(outline, out)
    _LOG.info(
        "content_ai_section_write coverage=%s/%s ratio=%.2f",
        final_cov.get("covered"),
        final_cov.get("total"),
        float(final_cov.get("ratio") or 0),
    )
    return out
