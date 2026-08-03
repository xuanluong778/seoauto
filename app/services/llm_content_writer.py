from __future__ import annotations

import logging
import os
import re
import json
import html as py_html
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values

from app.services.cost_control.executor import (
    CostControlBypassError,
    execute_guarded_external,
    http_error_retryable,
)
from app.services.cost_control.settings import cost_control_enforced
from app.services.cost_control.types import ExternalApiProvider
from app.services.content_draft_builder import (
    _looks_like_generic_template,
    content_ai_has_local_service_signal,
    detect_search_intent,
    extract_clean_html_fragment,
)


def _content_seo_checklist_snippet(*, max_chars: int = 4500) -> str:
    from app.services.content_seo_checklist import content_seo_checklist_snippet

    return content_seo_checklist_snippet(max_chars=max_chars)


def _anthropic_max_tokens_for_field(*, field: str, word_target: int | None) -> int:
    f = (field or "").strip().lower()
    if f in {"secondary_keywords", "tags"}:
        return 180
    if f in {"title", "slug"}:
        return 120
    if f == "meta_description":
        return 220
    if f == "outline_content":
        return 2400
    if f != "content":
        return 400
    w = int(word_target or 1000)
    w = max(400, min(w, 20000))
    est = int(w * 1.55) + 1800
    return max(4096, min(8192, est))


def _openai_max_tokens_for_field(*, field: str, word_target: int | None) -> int | None:
    f = (field or "").strip().lower()
    if f in {"secondary_keywords", "tags"}:
        return 160
    if f in {"title", "slug"}:
        return 80
    if f == "meta_description":
        return 200
    if f == "outline_content":
        return 2400
    if f != "content":
        return 300
    w = int(word_target or 1000)
    w = max(400, min(w, 20000))
    return min(16384, max(4096, int(w * 1.85) + 800))


WORD_COUNT_TOLERANCE_MIN = 0.90
WORD_COUNT_TOLERANCE_MAX = 1.10
DEFAULT_CONTENT_WORD_COUNT = 1000


def resolve_wc_for_content(target_word_count: int | None) -> int:
    try:
        wc_raw = int(target_word_count) if target_word_count is not None else None
    except (TypeError, ValueError):
        wc_raw = None
    if wc_raw is None or wc_raw <= 0:
        return DEFAULT_CONTENT_WORD_COUNT
    return max(200, min(wc_raw, 20000))


def content_word_count_bounds(wc: int) -> tuple[int, int]:
    wc = max(200, min(int(wc), 20000))
    return int(wc * WORD_COUNT_TOLERANCE_MIN), int(wc * WORD_COUNT_TOLERANCE_MAX)


def _normalize_outline_heading(text: str) -> str:
    s = _clean_ws(str(text or ""))
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^h[1-6]\s*:?\s*", "", s, flags=re.I)
    return s.lower()


def _outline_heading_stats(outline: str) -> dict[str, int]:
    h1 = h2 = h3 = 0
    for line in str(outline or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("###"):
            h3 += 1
        elif s.startswith("##"):
            h2 += 1
        elif s.startswith("#"):
            h1 += 1
        elif re.match(r"^H3\s*:", s, re.I):
            h3 += 1
        elif re.match(r"^H2\s*:", s, re.I):
            h2 += 1
        elif re.match(r"^H1\s*:", s, re.I):
            h1 += 1
    return {"h1": h1, "h2": h2, "h3": h3}


def _expected_outline_headings(outline: str) -> list[str]:
    headings: list[str] = []
    for line in str(outline or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(#{1,3})\s+(.+)$", s)
        if m:
            headings.append(_normalize_outline_heading(m.group(2)))
            continue
        m2 = re.match(r"^H([1-3])\s*:\s*(.+)$", s, re.I)
        if m2:
            headings.append(_normalize_outline_heading(m2.group(2)))
    return [h for h in headings if h]


def _headings_in_html(html: str) -> set[str]:
    raw = str(html or "").strip()
    if not raw:
        return set()
    try:
        soup = BeautifulSoup(raw, "html.parser")
        found: set[str] = set()
        for tag in soup.find_all(["h1", "h2", "h3"]):
            norm = _normalize_outline_heading(tag.get_text(" ", strip=True))
            if norm:
                found.add(norm)
        return found
    except Exception:
        return set()


def _heading_in_set(expected: str, found: set[str]) -> bool:
    e = _normalize_outline_heading(expected)
    if not e:
        return True
    for f in found:
        if e == f or e in f or f in e:
            return True
    return False


def _outline_coverage_stats(outline: str, html: str) -> dict[str, Any]:
    expected = _expected_outline_headings(outline)
    if not expected:
        return {"total": 0, "covered": 0, "ratio": 1.0, "missing_headings": []}
    found = _headings_in_html(html)
    missing: list[str] = []
    covered = 0
    for h in expected:
        if _heading_in_set(h, found):
            covered += 1
        else:
            missing.append(h)
    total = len(expected)
    ratio = covered / total if total else 1.0
    return {
        "total": total,
        "covered": covered,
        "ratio": ratio,
        "missing_headings": missing,
    }


def _effective_word_count_for_outline(*, base_wc: int, outline: str) -> int:
    stats = _outline_heading_stats(outline)
    h2, h3 = int(stats.get("h2") or 0), int(stats.get("h3") or 0)
    if h2 <= 0 and h3 <= 0:
        return base_wc
    floor = 150 + h2 * 90 + h3 * 45
    return max(int(base_wc), min(int(floor), 20000))


def _boost_max_tokens_for_outline(base: int, outline: str, *, cap: int) -> int:
    stats = _outline_heading_stats(outline)
    boost = int(stats.get("h2") or 0) * 350 + int(stats.get("h3") or 0) * 120
    return min(int(cap), max(int(base), int(base) + boost))


def _read_env_local() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / "env.local"
    if not env_file.exists():
        return {}
    raw = dotenv_values(env_file)
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if not k:
            continue
        out[str(k)] = str(v or "")
    return out


def _getenv(name: str, env_local: dict[str, str]) -> str:
    return str((os.getenv(name) or env_local.get(name) or "")).strip()


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _sanitize_mixed_style_phrases(text: str) -> str:
    out = str(text or "")
    substitutions = [
        (r"(?i)\bin this article we will\b", "Thông tin bên dưới tập trung trực tiếp vào nhu cầu dịch vụ"),
        (r"(?i)\btrong bài viết này\b", "Trong nội dung dịch vụ này"),
        (r"(?i)\btrong trải nghiệm của mình\b", "Theo dữ liệu vận hành thực tế"),
        (r"(?i)\bcác bước làm\b", "quy trình xử lý"),
        (r"(?i)\blocal service page\b", ""),
        (r"(?i)\bservice page\b", ""),
        (r"(?i)\btrang dịch vụ địa phương\b", ""),
        (r"(?i)\blà trang dịch vụ địa phương\b", "phục vụ tại khu vực này"),
    ]
    for pattern, repl in substitutions:
        out = re.sub(pattern, repl, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return out.strip()


def _strip_bracket_placeholders(html: str) -> str:
    """Remove editorial placeholders the model must never emit (best-effort)."""
    s = str(html or "")
    s = re.sub(r"\[\s*CẦN\s+XÁC\s+NHẬN\s*\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[\s*TODO\s*\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[\s*TBD\s*\]", "", s, flags=re.IGNORECASE)
    return s


def _transactional_gaps(html_text: str) -> list[str]:
    s = str(html_text or "").lower()
    gaps: list[str] = []
    if not any(x in s for x in ("dịch vụ", "dich vu", "hỗ trợ", "ho tro")):
        gaps.append("Thiếu mô tả rõ dịch vụ cung cấp.")
    if not any(x in s for x in ("kinh nghiệm", "kinh nghiem", "khách hàng", "khach hang", "bảo hành", "bao hanh")):
        gaps.append("Thiếu dấu hiệu tin cậy (kinh nghiệm/khách hàng/bảo hành).")
    if not any(x in s for x in ("bao gồm", "bao gom", "hạng mục", "hang muc")):
        gaps.append("Thiếu phần hạng mục bao gồm.")
    if not any(x in s for x in ("chi phí", "chi phi", "bảng giá", "bang gia", "giá", "gia")):
        gaps.append("Thiếu phần chi phí/bảng giá.")
    if not any(x in s for x in ("liên hệ", "lien he", "hotline", "zalo", "đặt lịch", "dat lich", "booking")):
        gaps.append("Thiếu CTA liên hệ ngay.")
    return gaps


def _first_line(s: str) -> str:
    raw = str(s or "").replace("\r", "")
    parts = [x.strip() for x in raw.split("\n") if x.strip()]
    return parts[0] if parts else str(s or "").strip()


def _looks_like_prose_keyword_field(text: str) -> bool:
    line = _first_line(text).strip()
    if not line:
        return False
    if ". " in line or line.endswith("."):
        return True
    parts = [p.strip() for p in line.split(",") if p.strip()]
    if len(parts) >= 3 and all(_count_words_vi(p) <= 6 for p in parts):
        return False
    return _count_words_vi(line) > 10


def _normalize_comma_keyword_field(text: str, *, field: str, max_items: int = 12) -> str:
    line = _first_line(text).strip().strip(".")
    if not line:
        return ""
    parts = [re.sub(r"\s+", " ", p).strip() for p in line.split(",") if p.strip()]
    max_words = 5 if field == "secondary_keywords" else 3
    max_chars = 48 if field == "secondary_keywords" else 35
    cleaned: list[str] = []
    for part in parts:
        if _count_words_vi(part) > max_words or len(part) > max_chars:
            continue
        if part and part not in cleaned:
            cleaned.append(part)
    if len(cleaned) >= 3:
        return ", ".join(cleaned[:max_items])
    for sep in (" và ", " & ", "; ", " — ", " - "):
        if sep in line:
            alt = [re.sub(r"\s+", " ", p).strip().strip(".") for p in line.split(sep) if p.strip()]
            cleaned = [p for p in alt if p and _count_words_vi(p) <= max_words and len(p) <= max_chars]
            if len(cleaned) >= 2:
                return ", ".join(cleaned[:max_items])
    return line


def _plain_text_to_html_fragment(*, text: str, title: str = "", primary_keyword: str = "") -> str:
    raw = _clean_ws(text)
    if not raw:
        return ""
    lines = [re.sub(r"\s+", " ", x).strip() for x in raw.replace("\r", "\n").split("\n") if x.strip()]
    if not lines:
        return ""
    h1 = _clean_ws(title) or _clean_ws(primary_keyword) or lines[0]
    body: list[str] = [f"<h1>{h1}</h1>"]
    bullets: list[str] = []

    def _flush_bullets() -> None:
        nonlocal bullets
        if not bullets:
            return
        body.append("<ul>")
        for item in bullets:
            body.append(f"<li>{item}</li>")
        body.append("</ul>")
        bullets = []

    for ln in lines:
        if ln == h1:
            continue
        if re.match(r"^[-*•]\s+", ln):
            bullets.append(re.sub(r"^[-*•]\s+", "", ln).strip())
            continue
        _flush_bullets()
        body.append(f"<p>{ln}</p>")
    _flush_bullets()
    return "\n".join(body).strip()


def _decode_html_entities_text(text: str) -> str:
    s = str(text or "")
    if not s:
        return ""
    # Decode entities twice to handle nested escaping (&amp;agrave; -> &agrave; -> à).
    once = py_html.unescape(s)
    twice = py_html.unescape(once)
    return twice


def _count_words_vi(text: str) -> int:
    """
    Rough Vietnamese-friendly word count.
    Count "words" as sequences of letters/digits (including Vietnamese diacritics).
    """
    t = str(text or "").strip()
    if not t:
        return 0
    words = re.findall(r"[\wà-ỹÀ-Ỹ]+", t, flags=re.I)
    return len(words)


def _count_words_html(html: str) -> int:
    raw = str(html or "").strip()
    if not raw:
        return 0
    try:
        soup = BeautifulSoup(raw, "html.parser")
        text = soup.get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
    return _count_words_vi(text)


def _take_first_words(text: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if limit <= 0 or not s:
        return ""
    words = re.findall(r"\S+", s)
    if len(words) <= limit:
        return s
    return " ".join(words[:limit]).strip()


def _trim_html_to_max_words(html: str, max_words: int) -> str:
    """
    Deterministic hard cap for HTML word count.
    Không xóa H1/H2/H3 — chỉ rút gọn đoạn văn cuối để giữ đủ outline.
    """
    raw = str(html or "").strip()
    if not raw or max_words <= 0:
        return ""
    if _count_words_html(raw) <= max_words:
        return raw
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return _take_first_words(raw, max_words)

    heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}
    para_tags = {"p", "li", "blockquote", "td", "th", "figcaption"}

    # Phase 1: shorten paragraphs from the end until under max_words (never remove headings).
    blocks = [t for t in soup.find_all(True) if str(t.name or "").lower() in para_tags]
    for tag in reversed(blocks):
        if _count_words_html(str(soup)) <= max_words:
            break
        txt = tag.get_text(" ", strip=True)
        w = _count_words_vi(txt)
        if w <= 0:
            continue
        # Drop short trailing fluff first
        if w <= 28:
            tag.decompose()
            continue
        keep = max(12, w // 2)
        trimmed = _take_first_words(txt, keep)
        tag.clear()
        if trimmed:
            tag.append(trimmed)

    # Phase 2: if still over, progressively shorten remaining paragraphs (keep last sentence stem).
    if _count_words_html(str(soup)) > max_words:
        for tag in reversed([t for t in soup.find_all(True) if str(t.name or "").lower() in para_tags]):
            if _count_words_html(str(soup)) <= max_words:
                break
            txt = tag.get_text(" ", strip=True)
            w = _count_words_vi(txt)
            if w <= 8:
                continue
            remain_global = max_words - (_count_words_html(str(soup)) - w)
            keep = max(8, min(w - 1, remain_global))
            if keep >= w:
                continue
            trimmed = _take_first_words(txt, keep)
            tag.clear()
            if trimmed:
                tag.append(trimmed if trimmed.endswith((".", "!", "?", "…")) else trimmed + "…")

    # Never remove heading tags even if still slightly over — outline fidelity > exact count.
    body = soup.body
    out = "".join(str(x) for x in (body.contents if body else soup.contents)).strip()
    return out or raw


def _ensure_outline_coverage_after_trim(
    html: str,
    *,
    outline: str,
    before_html: str,
) -> str:
    """Nếu trim cắt mất H2, khôi phục từ bản trước trim."""
    from app.services.content_ai_outline_engine import outline_h2_coverage

    ol = str(outline or "").strip()
    if not ol:
        return html
    after = outline_h2_coverage(ol, html)
    if after.get("ratio", 0) >= 0.99:
        return html
    before = outline_h2_coverage(ol, before_html)
    if before.get("covered", 0) > after.get("covered", 0):
        return before_html
    return html


def _ensure_min_words_html(*, html: str, min_words: int, keyword: str, title: str) -> str:
    raw = str(html or "").strip()
    if not raw:
        raw = f"<h1>{_clean_ws(title) or _clean_ws(keyword) or 'Nội dung dịch vụ'}</h1>"
    if _count_words_html(raw) >= min_words:
        return raw
    need = max(0, min_words - _count_words_html(raw))
    topic = _clean_ws(keyword) or _clean_ws(title) or "dịch vụ"
    blocks: list[str] = []
    i = 1
    while need > 0 and i <= 32:
        blocks.append(
            f"<p>Kinh nghiệm thực tế #{i}: với nhu cầu {topic}, chúng tôi ưu tiên kiểm tra nguyên nhân gốc, "
            "giải thích rõ từng bước xử lý và đề xuất phương án phù hợp ngân sách để khách dễ quyết định.</p>"
        )
        blocks.append(
            "<p>Trong quá trình triển khai, kỹ thuật viên xác nhận hạng mục trước khi làm, cập nhật tiến độ minh bạch, "
            "và nghiệm thu theo checklist nhằm hạn chế lỗi lặp lại sau sửa chữa.</p>"
        )
        need -= 65
        i += 1
    addon = "<h2>Mẹo sử dụng và bảo trì sau xử lý</h2>" + "".join(blocks)
    return (raw + "\n" + addon).strip()


def assess_content_word_count(html: str, target: int) -> dict[str, Any]:
    from app.services.content_ai_word_count_policy import assess_word_count_meta

    return assess_word_count_meta(html, target)


def _enforce_content_word_count_with_llm(
    out: str,
    *,
    wc_for_content: int,
    cfg: LlmConfig,
    system: str,
    pk: str,
    title: str,
    oai_mt: int | None,
    ant_mt: int,
    api_timeout: int,
    outline: str = "",
) -> str:
    """Expand or trim HTML content when deviation exceeds 15% from target."""
    from app.services.content_ai_word_count_policy import (
        needs_word_count_repair,
        needs_word_count_trim,
        word_count_bounds,
    )

    wc = wc_for_content
    min_ok, max_ok = word_count_bounds(wc)
    cur = _count_words_html(out)
    outline_text = str(outline or "").strip()
    if outline_text:
        cov = _outline_coverage_stats(outline_text, out)
        if cov["ratio"] < 0.88:
            out = _continue_content_for_missing_outline(
                html=out,
                outline=outline_text,
                wc_target=wc,
                cfg=cfg,
                system=system,
                oai_mt=oai_mt,
                ant_mt=ant_mt,
                api_timeout=api_timeout,
                source_blob=f"OUTLINE:\n{outline_text}\nPRIMARY_KEYWORD: {pk}",
                primary_keyword=pk,
            )
            cur = _count_words_html(out)
    if not needs_word_count_repair(cur, wc) and not needs_word_count_trim(cur, wc):
        return out

    if needs_word_count_repair(cur, wc):
        for _ in range(3):
            cur_words = _count_words_html(out)
            if cur_words >= min_ok:
                break
            need = max(0, wc - cur_words)
            extender = (
                "Bạn đã viết bài HTML ở dưới.\n"
                f"Hiện khoảng {cur_words} từ, mục tiêu khoảng {wc} từ (cho phép {min_ok}–{max_ok} từ).\n"
                f"Hãy MỞ RỘNG để thêm khoảng {need} từ, bổ sung đúng ngữ cảnh bài hiện tại.\n"
                "Ràng buộc bắt buộc:\n"
                "- Không dùng [CẦN XÁC NHẬN] hay placeholder tương tự; không nhắc SEO/service page.\n"
                "- Giữ nguyên nội dung đã có, CHỈ ĐƯỢC thêm tiếp vào cuối bài hoặc mở rộng section hiện có.\n"
                "- Thêm tối thiểu: 1 H2 mới + 2 H3, 1 checklist chi tiết, và 1 FAQ (3–5 câu hỏi).\n"
                "- Không lặp lại nguyên văn các đoạn đã viết.\n"
                "- Trả về TOÀN BỘ HTML hoàn chỉnh (bao gồm cả phần cũ + phần mới); chỉ HTML, không markdown, không giải thích ngoài thẻ.\n"
                "\n"
                "=== BÀI HIỆN TẠI (HTML) ===\n"
                f"{out}\n"
                "\n"
                "=== OUTPUT (HTML) ==="
            )
            if cfg.provider == "openai":
                out = _openai_chat_completion(
                    cfg=cfg,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": extender},
                    ],
                    max_tokens=oai_mt,
                    timeout_sec=api_timeout,
                )
            else:
                out = _anthropic_messages(
                    cfg=cfg,
                    system=system,
                    user=extender,
                    max_tokens=ant_mt,
                    timeout_sec=api_timeout,
                )
            out = extract_clean_html_fragment(str(out or "").strip()) or out

    if needs_word_count_trim(_count_words_html(out), wc):
        if outline_text:
            cov = _outline_coverage_stats(outline_text, out)
            if cov["ratio"] < 0.95:
                return out
        for _ in range(3):
            cur_words = _count_words_html(out)
            if cur_words <= max_ok:
                break
            shrink_to = max(wc, max_ok - 20)
            compressor = (
                "Bạn đã viết bài HTML ở dưới nhưng đang quá dài.\n"
                f"Hiện khoảng {cur_words} từ; yêu cầu rút gọn còn khoảng {shrink_to} từ (không vượt quá {max_ok} từ).\n"
                "Ràng buộc bắt buộc:\n"
                "- Không dùng [CẦN XÁC NHẬN] hay placeholder; không nhắc SEO/service page.\n"
                "- Giữ NGUYÊN 100% mọi thẻ <h2>/<h3> trong bài — tuyệt đối không xóa heading outline.\n"
                "- Giữ 1 H1 và hệ H2/H3 chính, giữ thông tin cốt lõi.\n"
                "- Cắt bớt phần lặp, câu đệm, ví dụ thừa trong <p> — không cắt nửa câu giữa chừng.\n"
                "- Không thêm ý mới ngoài bài hiện tại.\n"
                "- Trả về TOÀN BỘ HTML hoàn chỉnh sau khi rút gọn; chỉ HTML, không markdown, không giải thích ngoài thẻ.\n"
                "\n"
                "=== BÀI HIỆN TẠI (HTML) ===\n"
                f"{out}\n"
                "\n"
                "=== OUTPUT (HTML) ==="
            )
            if cfg.provider == "openai":
                out = _openai_chat_completion(
                    cfg=cfg,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": compressor},
                    ],
                    max_tokens=oai_mt,
                    timeout_sec=api_timeout,
                )
            else:
                out = _anthropic_messages(
                    cfg=cfg,
                    system=system,
                    user=compressor,
                    max_tokens=ant_mt,
                    timeout_sec=api_timeout,
                )
            out = extract_clean_html_fragment(str(out or "").strip()) or out
        if _count_words_html(out) > max_ok:
            before = out
            out = _trim_html_to_max_words(out, max_ok)
            out = _ensure_outline_coverage_after_trim(out, outline=outline_text, before_html=before)

    if _count_words_html(out) < min_ok:
        force_expand_user = (
            "Bài HTML hiện tại còn quá ngắn so với mục tiêu.\n"
            f"Yêu cầu viết lại TOÀN BỘ để đạt tối thiểu {min_ok} từ, mục tiêu khoảng {wc} từ.\n"
            "Bắt buộc có sapo, các section H2/H3 đầy đủ nội dung, bảng, checklist và FAQ.\n"
            "Chỉ trả về HTML sạch, không markdown, không giải thích.\n"
            "\n=== HTML HIỆN TẠI ===\n"
            f"{out}\n"
            "\n=== OUTPUT (HTML) ==="
        )
        if cfg.provider == "openai":
            out2 = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": force_expand_user}],
                max_tokens=oai_mt,
                timeout_sec=api_timeout,
            )
        else:
            out2 = _anthropic_messages(
                cfg=cfg,
                system=system,
                user=force_expand_user,
                max_tokens=ant_mt,
                timeout_sec=api_timeout,
            )
        out2 = extract_clean_html_fragment(str(out2 or "").strip())
        if out2:
            out = _sanitize_mixed_style_phrases(_strip_bracket_placeholders(out2))
    if _count_words_html(out) < min_ok:
        out = _ensure_min_words_html(html=out, min_words=min_ok, keyword=pk, title=title)
    if _count_words_html(out) > max_ok:
        before = out
        out = _trim_html_to_max_words(out, max_ok)
        out = _ensure_outline_coverage_after_trim(out, outline=outline_text, before_html=before)
    # Prefer full outline over exact word cap when both conflict.
    if outline_text:
        from app.services.content_ai_outline_engine import outline_h2_coverage

        cov = outline_h2_coverage(outline_text, out)
        if cov.get("ratio", 0) < 0.99 and cov.get("missing_sections"):
            try:
                out = _continue_content_for_missing_outline(
                    html=out,
                    outline=outline_text,
                    wc_target=wc,
                    cfg=cfg,
                    system=system,
                    oai_mt=oai_mt,
                    ant_mt=ant_mt,
                    api_timeout=api_timeout,
                    source_blob=f"OUTLINE:\n{outline_text}\nPRIMARY_KEYWORD: {pk}",
                    primary_keyword=pk,
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "enforce_outline_repair_failed: %s",
                    str(exc)[:300],
                )
    return out


def enforce_content_ai_word_count(
    html: str,
    *,
    target_word_count: int | None,
    title: str = "",
    primary_keyword: str = "",
    outline_content: str = "",
    use_system_llm: bool = False,
    user_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Post-process streamed or raw HTML to meet target word count (±10%).
    Returns (html, word_count_stats). On LLM failure, returns best-effort HTML.
    """
    import logging

    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    wc = resolve_wc_for_content(target_word_count)
    outline_text = str(outline_content or "").strip()
    if outline_text:
        wc = _effective_word_count_for_outline(base_wc=wc, outline=outline_text)
    pk = _clean_ws(primary_keyword)
    t = str(title or "").strip()
    api_timeout = 120
    oai_mt = _openai_max_tokens_for_field(field="content", word_target=wc)
    ant_mt = _anthropic_max_tokens_for_field(field="content", word_target=wc)
    if outline_text:
        oai_mt = _boost_max_tokens_for_outline(int(oai_mt or 4096), outline_text, cap=16384)
        ant_mt = _boost_max_tokens_for_outline(int(ant_mt or 4096), outline_text, cap=8192)
    system = (
        "Bạn là trợ lý viết nội dung SEO tiếng Việt: chính xác, hữu ích (Helpful Content), E-E-A-T."
        " Chỉ dùng nội dung bài hiện tại; không bịa số liệu/giá."
        " Field content: chỉ HTML thuần; không markdown, không lời dẫn ngoài thẻ."
    )

    out = str(html or "").strip()
    out = _decode_html_entities_text(out)
    out_html = extract_clean_html_fragment(out)
    if not out_html and out:
        out_html = _plain_text_to_html_fragment(text=_decode_html_entities_text(out), title=t, primary_keyword=pk)
    out = out_html or out
    out = _strip_bracket_placeholders(out)
    out = _sanitize_mixed_style_phrases(out)

    if outline_text:
        try:
            out = _continue_content_for_missing_outline(
                html=out,
                outline=outline_text,
                wc_target=wc,
                cfg=cfg,
                system=system,
                oai_mt=oai_mt,
                ant_mt=ant_mt,
                api_timeout=api_timeout,
                source_blob=f"OUTLINE:\n{outline_text}\nPRIMARY_KEYWORD: {pk}",
                primary_keyword=pk,
            )
            out = extract_clean_html_fragment(str(out or "").strip()) or out
            out = _strip_bracket_placeholders(out)
            out = _sanitize_mixed_style_phrases(out)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "enforce_content_ai_outline_repair_failed: %s",
                str(exc)[:300],
            )

    from app.services.content_ai_word_count_policy import (
        assess_word_count_meta,
        needs_word_count_repair,
        needs_word_count_trim,
        word_count_bounds,
    )

    meta_before = assess_word_count_meta(out, wc)
    if meta_before["word_count_status"] == "ok":
        if outline_text:
            from app.services.content_ai_outline_engine import outline_h2_coverage

            cov_ok = outline_h2_coverage(outline_text, out)
            if cov_ok.get("ratio", 0) >= 0.99 and not cov_ok.get("missing_sections"):
                meta = dict(meta_before)
                meta["skip_client_enforce"] = True
                return out, meta
        else:
            return out, meta_before
    if outline_text:
        cov = _outline_coverage_stats(outline_text, out)
        min_ok, max_ok = word_count_bounds(wc)
        actual = int(meta_before.get("actual_word_count") or 0)
        if cov["ratio"] >= 0.85 and actual >= min_ok and actual <= max_ok:
            meta = dict(meta_before)
            meta["skip_client_enforce"] = True
            return out, meta
    if not meta_before["needs_repair"] and not meta_before["needs_trim"]:
        return out, meta_before

    for attempt in range(3):
        meta_cur = assess_word_count_meta(out, wc)
        if meta_cur["word_count_status"] == "ok":
            break
        if not meta_cur["needs_repair"] and not meta_cur["needs_trim"]:
            break
        try:
            out = _enforce_content_word_count_with_llm(
                out,
                wc_for_content=wc,
                cfg=cfg,
                system=system,
                pk=pk,
                title=t,
                oai_mt=oai_mt,
                ant_mt=ant_mt,
                api_timeout=api_timeout,
                outline=outline_text,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "enforce_content_ai_word_count_llm_failed attempt=%s: %s",
                attempt + 1,
                str(exc)[:500],
            )
            if attempt >= 2:
                break
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes

    out = postprocess_content_blockquotes(out)
    return out, assess_content_word_count(out, wc)


def _continue_content_for_missing_outline(
    *,
    html: str,
    outline: str,
    wc_target: int,
    cfg: LlmConfig,
    system: str,
    oai_mt: int | None,
    ant_mt: int,
    api_timeout: int,
    source_blob: str = "",
    primary_keyword: str = "",
) -> str:
    """Bổ sung section outline còn thiếu — append-only, không viết lại toàn bài."""
    from app.services.content_ai_section_writer import ensure_full_outline_html

    ol = str(outline or "").strip()
    if not ol:
        return html

    def _llm(*, system: str, user: str) -> str:
        return _llm_chat_for_cfg(
            cfg=cfg,
            system=system,
            user=user,
            max_tokens_oai=_boost_max_tokens_for_outline(int(oai_mt or 4096), ol, cap=16384),
            max_tokens_ant=_boost_max_tokens_for_outline(int(ant_mt or 4096), ol, cap=8192),
            timeout_sec=min(180, max(api_timeout, 90)),
        )

    return ensure_full_outline_html(
        html=str(html or "").strip(),
        outline=ol,
        total_wc=int(wc_target or 1000),
        primary_keyword=primary_keyword,
        source_blob=source_blob or f"OUTLINE:\n{ol}",
        system=system,
        llm_call=_llm,
    )


def finalize_content_ai_stream_html(
    html: str,
    *,
    target_word_count: int | None,
    title: str = "",
    primary_keyword: str = "",
    outline_content: str = "",
    target_website: str = "",
    use_system_llm: bool = False,
    user_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """
  Sau khi stream xong: làm sạch HTML, bổ sung H2 thiếu từ outline, rồi ±10% số từ.
    """
    out = str(html or "").strip()
    outline = str(outline_content or "").strip()
    cfg = None
    if outline:
        from app.services.content_ai_outline_engine import outline_h2_coverage

        cov = outline_h2_coverage(outline, out)
        if cov.get("ratio", 0) < 1.0 or cov.get("missing_sections"):
            cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
            if cfg:
                wc = resolve_wc_for_content(target_word_count)
                if outline:
                    wc = _effective_word_count_for_outline(base_wc=wc, outline=outline)
                system = (
                    "Bạn là trợ lý viết nội dung SEO tiếng Việt. "
                    "Chỉ viết bổ sung section outline còn thiếu; HTML thuần; không bịa dữ liệu."
                )
                oai_mt = _boost_max_tokens_for_outline(
                    int(_openai_max_tokens_for_field(field="content", word_target=wc) or 4096),
                    outline,
                    cap=16384,
                )
                ant_mt = _boost_max_tokens_for_outline(
                    int(_anthropic_max_tokens_for_field(field="content", word_target=wc) or 4096),
                    outline,
                    cap=8192,
                )

                def _llm(*, system: str, user: str) -> str:
                    return _llm_chat_for_cfg(
                        cfg=cfg,
                        system=system,
                        user=user,
                        max_tokens_oai=oai_mt,
                        max_tokens_ant=ant_mt,
                        timeout_sec=120,
                    )

                from app.services.content_ai_section_writer import ensure_full_outline_html

                out = ensure_full_outline_html(
                    html=out,
                    outline=outline,
                    total_wc=wc,
                    primary_keyword=primary_keyword,
                    source_blob=f"OUTLINE:\n{outline}\nPRIMARY_KEYWORD: {primary_keyword}",
                    system=system,
                    llm_call=_llm,
                )

    return enforce_content_ai_word_count(
        out,
        target_word_count=target_word_count,
        title=title,
        primary_keyword=primary_keyword,
        outline_content=outline,
        use_system_llm=use_system_llm,
        user_id=user_id,
    )


def _fetch_website_context_bundle(
    target_website: str,
    keyword: str,
    *,
    related_limit: int = 10,
) -> tuple[tuple[str, str], list[dict[str, str]]]:
    """Fetch homepage text + related WP posts once per request (cached, parallel)."""
    from concurrent.futures import ThreadPoolExecutor

    from app.services.content_ai_request_cache import cache_get, cache_set

    site = str(target_website or "").strip()
    if not site:
        return ("", ""), []
    pk = str(keyword or "").strip()
    cache_key = f"webctx:{site.lower()}:{pk.lower()}:{int(related_limit)}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_src = pool.submit(_fetch_source_text, site)
        fut_rel = pool.submit(
            _fetch_related_posts_for_internal_links, site, pk, limit=related_limit
        )
        bundle = (fut_src.result(), fut_rel.result())
    cache_set(cache_key, bundle)
    return bundle


def _fetch_source_text(url: str) -> tuple[str, str]:
    """
    Fetch a URL and return (final_url, extracted_text).
    Best-effort: strips scripts/styles, keeps visible text.
    """
    raw_url = str(url or "").strip()
    if not raw_url:
        return "", ""
    if not raw_url.lower().startswith(("http://", "https://")):
        raw_url = "https://" + raw_url.lstrip("/")
    try:
        resp = requests.get(
            raw_url,
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
                )
            },
        )
    except Exception:
        return raw_url, ""
    final_url = str(resp.url or raw_url)
    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return final_url, text


def _fetch_related_posts_for_internal_links(target_website: str, keyword: str, *, limit: int = 8) -> list[dict[str, str]]:
    """Best-effort crawl related posts from WP REST for internal-link prompting."""
    raw = str(target_website or "").strip()
    if not raw:
        return []
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")
    try:
        p = requests.utils.urlparse(raw)
        if p.scheme not in {"http", "https"} or not p.netloc:
            return []
        base = f"{p.scheme}://{p.netloc}".rstrip("/")
    except Exception:
        return []

    api = f"{base}/wp-json/wp/v2/posts"
    params: dict[str, Any] = {
        "per_page": max(3, min(int(limit or 8), 20)),
        "_fields": "link,title.rendered",
        "orderby": "date",
        "order": "desc",
    }
    kw = str(keyword or "").strip()
    if kw:
        params["search"] = kw
    try:
        r = requests.get(api, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code >= 400:
            return []
        data = r.json() if r.content else []
    except Exception:
        return []
    out: list[dict[str, str]] = []
    if not isinstance(data, list):
        return out
    for it in data:
        if not isinstance(it, dict):
            continue
        link = str(it.get("link") or "").strip()
        title_obj = it.get("title") or {}
        title_html = str((title_obj.get("rendered") if isinstance(title_obj, dict) else "") or "").strip()
        title = BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True)
        if link and title:
            out.append({"title": title, "url": link})
    return out


def _truncate_text(text: str, *, max_chars: int) -> str:
    t = str(text or "").strip()
    if len(t) <= max_chars:
        return t
    # keep head + tail for some context
    head = t[: max(0, int(max_chars * 0.75))]
    tail = t[-max(0, int(max_chars * 0.20)) :]
    return (head + "\n...\n" + tail).strip()


@dataclass(frozen=True)
class LlmConfig:
    provider: str  # "openai" | "anthropic" | "gemini"
    api_key: str
    model: str
    temperature: float
    api_base_url: str | None = None
    logical_provider: str = "openai"


_OPENAI_KEY_PROVIDERS = frozenset({"openai", "custom_openai", "openrouter"})
_ANTHROPIC_KEY_PROVIDERS = frozenset({"custom_anthropic"})

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _openai_request_headers(cfg: LlmConfig) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    base = str(cfg.api_base_url or "")
    if "openrouter.ai" in base:
        env_local = _read_env_local()
        site = (_getenv("APP_BASE_URL", env_local) or "https://seoauto.vn").strip().rstrip("/")
        headers["HTTP-Referer"] = site
        headers["X-Title"] = _getenv("OPENROUTER_APP_TITLE", env_local) or "SEOAuto"
    return headers


def openai_compatible_chat_url(api_base_url: str | None) -> str:
    """Build chat-completions URL; base có thể đã chứa /v1 (OpenRouter) hoặc chưa (OpenAI)."""
    base = (api_base_url or "https://api.openai.com").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _llm_temperature(env_local: dict[str, str]) -> float:
    temp_raw = _getenv("LLM_TEMPERATURE", env_local) or "0.3"
    try:
        temperature = float(temp_raw)
    except ValueError:
        temperature = 0.3
    return max(0.0, min(1.0, temperature))


def _load_llm_config_from_env() -> LlmConfig | None:
    env_local = _read_env_local()
    provider_raw = (_getenv("LLM_PROVIDER", env_local) or "").strip().lower()
    openai_key = _getenv("OPENAI_API_KEY", env_local)
    anthropic_key = _getenv("ANTHROPIC_API_KEY", env_local)
    openrouter_key = _getenv("OPENROUTER_API_KEY", env_local)

    if provider_raw in {"openai", "anthropic", "openrouter"}:
        provider = provider_raw
    elif openrouter_key and not openai_key and not anthropic_key:
        provider = "openrouter"
    else:
        provider = "anthropic" if anthropic_key else ("openai" if openai_key else "openai")

    # LLM_PROVIDER=openrouter nhưng chưa điền key → fallback key khác để không gián đoạn hệ thống.
    if provider == "openrouter" and not openrouter_key:
        provider = "anthropic" if anthropic_key else "openai"

    api_base_url: str | None = None
    if provider == "openrouter":
        # OpenRouter là OpenAI-compatible: dùng provider "openai" + base URL riêng.
        api_key = openrouter_key
        api_base_url = OPENROUTER_BASE_URL
        model = _getenv("OPENROUTER_MODEL", env_local) or "openai/gpt-4o-mini"
        provider = "openai"
    elif provider == "openai":
        api_key = openai_key
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
        base = _getenv("OPENAI_BASE_URL", env_local)
        if base:
            api_base_url = base.rstrip("/")
    else:
        api_key = anthropic_key
        model = _getenv("ANTHROPIC_MODEL", env_local) or "claude-3-5-sonnet-20241022"

    if not api_key:
        return None

    return LlmConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        temperature=_llm_temperature(env_local),
        api_base_url=api_base_url,
    )


def _load_llm_config_from_user_keys(user_id: int) -> LlmConfig | None:
    from app.services.api_keys_store import list_enabled_keys_for_user

    keys = list_enabled_keys_for_user(user_id)
    if not keys:
        return None

    env_local = _read_env_local()
    provider_pref = (_getenv("LLM_PROVIDER", env_local) or "").strip().lower()

    openai_keys = [k for k in keys if k["provider"] in _OPENAI_KEY_PROVIDERS]
    anthropic_keys = [k for k in keys if k["provider"] in _ANTHROPIC_KEY_PROVIDERS]
    or_keys = [k for k in keys if str(k.get("provider") or "") == "openrouter"]

    pick: dict[str, Any] | None = None
    llm_provider: str | None = None

    if provider_pref == "openrouter" and or_keys:
        pick, llm_provider = or_keys[0], "openai"
    elif provider_pref == "openai" and openai_keys:
        pick, llm_provider = openai_keys[0], "openai"
    elif provider_pref == "anthropic" and anthropic_keys:
        pick, llm_provider = anthropic_keys[0], "anthropic"
    elif or_keys and not anthropic_keys:
        pick, llm_provider = or_keys[0], "openai"
    elif anthropic_keys:
        pick, llm_provider = anthropic_keys[0], "anthropic"
    elif openai_keys:
        pick, llm_provider = openai_keys[0], "openai"

    if not pick or not llm_provider:
        return None

    store_provider = str(pick.get("provider") or "")
    api_base_url: str | None = None
    if store_provider == "openrouter":
        api_base_url = OPENROUTER_BASE_URL
        model = (
            str(pick.get("model") or "").strip()
            or _getenv("OPENROUTER_MODEL", env_local)
            or _getenv("OPENAI_MODEL", env_local)
            or "openai/gpt-4o-mini"
        )
    elif store_provider == "custom_openai":
        base = _getenv("OPENAI_BASE_URL", env_local)
        api_base_url = base.rstrip("/") if base else None
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
    elif llm_provider == "openai":
        model = _getenv("OPENAI_MODEL", env_local) or "gpt-4o-mini"
    else:
        model = _getenv("ANTHROPIC_MODEL", env_local) or "claude-3-5-sonnet-20241022"

    api_key = str(pick.get("api_key") or "").strip()
    if not api_key:
        return None

    return LlmConfig(
        provider=llm_provider,
        api_key=api_key,
        model=model,
        temperature=_llm_temperature(env_local),
        api_base_url=api_base_url,
    )


def load_llm_config(user_id: int | None = None) -> LlmConfig | None:
    """
    Resolve LLM credentials for the current request.

    Logged-in users: own API keys first; if admin granted ``use_admin_api_pool``,
    fall back to env.local / admin keys. Requires ``api_access_enabled`` (except admin).
  """
    uid = user_id
    if uid is None:
        from app.core.user_context import get_request_user_id

        uid = get_request_user_id()
    if uid is not None:
        from app.db import SessionLocal
        from app.services.user_api_access import resolve_llm_config_for_user

        db = SessionLocal()
        try:
            return resolve_llm_config_for_user(db, int(uid))
        finally:
            db.close()
    return _load_llm_config_from_env()


def load_llm_config_admin() -> LlmConfig | None:
    """Khóa API hệ thống (env.local + admin keys) — không lộ cho user."""
    from app.db import SessionLocal
    from app.services.user_api_access import load_admin_shared_llm_config

    db = SessionLocal()
    try:
        return load_admin_shared_llm_config(db)
    finally:
        db.close()


def _build_instructions(
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
    """Delegate SEO field prompts to seo_content_prompt (Helpful Content + EEAT)."""
    from app.services.content_ai_knowledge_context import build_content_prompt_with_knowledge
    from app.services.seo_content_prompt import build_llm_field_instructions

    base = build_llm_field_instructions(
        field=field,
        target_word_count=target_word_count,
        primary_keyword=primary_keyword,
        llm_mode=llm_mode,
        user_outline_present=user_outline_present,
        knowledge=knowledge,
        outline_h2_count=outline_h2_count,
        outline_h3_count=outline_h3_count,
        outline_diversity_extra=outline_diversity_extra,
    )
    extra = build_content_prompt_with_knowledge(
        knowledge or {},
        field=field,
        primary_keyword=primary_keyword,
    )
    return base + extra if extra else base


def _openai_chat_completion(
    *,
    cfg: LlmConfig,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    timeout_sec: int = 45,
) -> str:
    url = openai_compatible_chat_url(cfg.api_base_url)
    headers = _openai_request_headers(cfg)
    payload: dict[str, Any] = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    def _post() -> requests.Response:
        return requests.post(url, headers=headers, json=payload, timeout=timeout_sec)

    if cost_control_enforced():
        from app.services.cost_control.module_gates import llm_provider_for_config

        r = execute_guarded_external(
            llm_provider_for_config(cfg),
            "chat_completion",
            _post,
            is_retryable=http_error_retryable,
        )
    else:
        r = _post()
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:400]}")
    data = r.json() if r.content else {}
    try:
        msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return _clean_ws("\n".join(parts)).strip()
        return str(content or "").strip()
    except Exception as exc:
        raise RuntimeError("OpenAI response parse failed") from exc


def _gemini_chat_completion(
    *,
    cfg: LlmConfig,
    system: str,
    user: str,
    max_tokens: int | None = None,
    timeout_sec: int = 45,
) -> str:
    model = str(cfg.model or "gemini-2.0-flash").strip()
    if model.startswith("models/"):
        model_path = model
    else:
        model_path = f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": cfg.temperature},
    }
    if system.strip():
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if max_tokens is not None:
        payload["generationConfig"]["maxOutputTokens"] = int(max_tokens)

    def _post() -> requests.Response:
        return requests.post(url, params={"key": cfg.api_key}, json=payload, timeout=timeout_sec)

    if cost_control_enforced():
        from app.services.cost_control.module_gates import llm_provider_for_config

        r = execute_guarded_external(
            llm_provider_for_config(cfg),
            "chat_completion",
            _post,
            is_retryable=http_error_retryable,
        )
    else:
        r = _post()
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {(r.text or '')[:400]}")
    data = r.json() if r.content else {}
    try:
        cands = data.get("candidates") or []
        parts = (((cands[0] or {}).get("content") or {}).get("parts") or []) if cands else []
        text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
        return str(text or "").strip()
    except Exception as exc:
        raise RuntimeError("Gemini response parse failed") from exc


def _llm_chat_for_cfg(
    *,
    cfg: LlmConfig,
    system: str,
    user: str,
    max_tokens_oai: int | None,
    max_tokens_ant: int,
    timeout_sec: int,
) -> str:
    if cfg.provider == "gemini":
        mt = max_tokens_oai if max_tokens_oai is not None else max_tokens_ant
        return _gemini_chat_completion(
            cfg=cfg, system=system, user=user, max_tokens=mt, timeout_sec=timeout_sec
        )
    if cfg.provider == "openai":
        msg = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return _openai_chat_completion(cfg=cfg, messages=msg, max_tokens=max_tokens_oai, timeout_sec=timeout_sec)
    return _anthropic_messages(
        cfg=cfg, system=system, user=user, max_tokens=max_tokens_ant, timeout_sec=timeout_sec
    )


def _iter_openai_chat_completion_deltas(
    *,
    cfg: LlmConfig,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    timeout_sec: int = 45,
) -> Iterator[str]:
    """Yield text deltas from OpenAI-compatible chat completions streaming API."""
    url = openai_compatible_chat_url(cfg.api_base_url)
    headers = _openai_request_headers(cfg)
    payload: dict[str, Any] = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "messages": messages,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    def _post_stream() -> requests.Response:
        return requests.post(url, headers=headers, json=payload, timeout=timeout_sec, stream=True)

    if cost_control_enforced():
        from app.services.cost_control.module_gates import llm_provider_for_config

        r = execute_guarded_external(
            llm_provider_for_config(cfg),
            "chat_completion_stream",
            _post_stream,
            is_retryable=http_error_retryable,
        )
    else:
        r = _post_stream()
    with r:
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:400]}")
        for raw_line in r.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = str(raw_line).strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta_obj = (choices[0] or {}).get("delta") or {}
            piece = delta_obj.get("content")
            if isinstance(piece, str) and piece:
                yield piece


def _iter_text_as_deltas(text: str, *, chunk_size: int = 48) -> Iterator[str]:
    raw = str(text or "")
    if not raw:
        return
    size = max(8, min(int(chunk_size or 48), 240))
    for i in range(0, len(raw), size):
        yield raw[i : i + size]


def iter_content_ai_content_stream_deltas(
    *,
    title: str = "",
    content: str = "",
    target_website: str = "",
    slug: str = "",
    tags: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    target_word_count: int | None = None,
    user_id: int | None = None,
    use_system_llm: bool = False,
) -> Iterator[str]:
    """
    Stream token/text deltas for field=content (primary LLM pass).
    Post-expand/trim passes are skipped so the client sees live typing.
    """
    from app.services.content_ai_knowledge_context import (
        ContentAiLlmUnavailableError,
        assert_single_writer_source_ready,
    )

    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        raise ContentAiLlmUnavailableError("llm_not_configured")

    env_local = _read_env_local()
    llm_mode = (_getenv("CONTENT_AI_LLM_MODE", env_local) or "auto").strip().lower()
    if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
        llm_mode = "auto"

    pk = _clean_ws(primary_keyword)
    sec = _clean_ws(secondary_keywords)
    t = str(title or "").strip()
    outline = (outline_content or "").strip()
    if llm_mode == "auto" and outline and _looks_like_generic_template(outline):
        outline = ""
    user_outline_present = bool(outline)

    assert_single_writer_source_ready(
        primary_keyword=pk,
        target_website=target_website,
        content=content,
        outline_content=outline,
        title=t,
        field="content",
        user_id=user_id,
    )

    try:
        wc_raw = int(target_word_count) if target_word_count is not None else None
    except Exception:
        wc_raw = None
    wc_for_content = resolve_wc_for_content(wc_raw)

    api_timeout = 120
    oai_mt = _openai_max_tokens_for_field(field="content", word_target=wc_for_content)
    ant_mt = _anthropic_max_tokens_for_field(field="content", word_target=wc_for_content)

    src_url = ""
    src_text = ""
    related_posts: list[dict[str, str]] = []
    if str(target_website or "").strip():
        (src_url, src_text), related_posts = _fetch_website_context_bundle(
            str(target_website or "").strip(), pk, related_limit=10
        )
        src_text = _truncate_text(src_text, max_chars=9000)

    notes = _truncate_text(_clean_ws(content), max_chars=3500) if content else ""
    outline_src = _truncate_text(outline, max_chars=4500) if outline else ""

    source_parts: list[str] = []
    if pk:
        source_parts.append(f"PRIMARY_KEYWORD: {pk}")
    if sec:
        source_parts.append(f"SECONDARY_KEYWORDS: {sec}")
    if t:
        source_parts.append(f"TITLE_DRAFT: {t}")
    if slug:
        source_parts.append(f"SLUG_DRAFT: {slug}")
    if tags:
        source_parts.append(f"TAGS_DRAFT: {tags}")
    if meta_description:
        source_parts.append(f"META_DESCRIPTION_DRAFT: {meta_description}")
    if outline_src:
        source_parts.append("OUTLINE_SOURCE:\n" + outline_src)
    if notes:
        source_parts.append("NOTES_SOURCE:\n" + notes)
    if src_text:
        source_parts.append(f"WEBSITE_SOURCE_URL: {src_url}")
        source_parts.append("WEBSITE_SOURCE_TEXT:\n" + src_text)
    if related_posts:
        rel_lines = []
        for i, item in enumerate(related_posts, start=1):
            t_rel = str(item.get("title") or "").strip()
            u_rel = str(item.get("url") or "").strip()
            if t_rel and u_rel:
                rel_lines.append(f"{i}. {t_rel} | {u_rel}")
        if rel_lines:
            source_parts.append("RELATED_ARTICLES:\n" + "\n".join(rel_lines))

    knowledge: dict[str, Any] | None = None
    if pk:
        try:
            from app.services.content_ai_knowledge_context import (
                build_outline_context_from_knowledge,
                get_relevant_knowledge_for_keyword,
            )

            knowledge = get_relevant_knowledge_for_keyword(
                pk,
                target_website=str(target_website or ""),
                user_id=user_id,
            )
            if knowledge and knowledge.get("found"):
                kb_ctx = build_outline_context_from_knowledge(knowledge)
                if kb_ctx:
                    source_parts.append("KNOWLEDGE_BASE:\n" + kb_ctx)
        except Exception:
            knowledge = None

    source_blob = "\n\n".join(source_parts).strip() or "SOURCE: (trống)"
    instructions = _build_instructions(
        field="content",
        target_word_count=wc_for_content,
        primary_keyword=pk,
        llm_mode=llm_mode,
        user_outline_present=user_outline_present,
        knowledge=knowledge,
    )
    kb_active = bool(knowledge and knowledge.get("found"))
    system = (
        "Bạn là trợ lý viết nội dung SEO tiếng Việt: chính xác, hữu ích (Helpful Content), E-E-A-T."
        " Chỉ dùng SOURCE; không bịa số liệu/giá."
    )
    if kb_active:
        system += (
            " Ưu tiên KNOWLEDGE_BASE trong SOURCE cho bảng giá, SĐT/hotline, thông tin công ty;"
            " không ghi «Cần bổ sung dữ liệu» khi KB/SOURCE đã có."
        )
    else:
        system += " Thiếu dữ liệu trong SOURCE → «Cần bổ sung dữ liệu»."
    system += (
        " Không nhồi từ khóa; không placeholder [CẦN XÁC NHẬN]."
        " Field content: chỉ HTML thuần (h1–h3, p, list, table, figure+alt, FAQ,"
        " gợi yếu link nội/ngoài, JSON-LD schema); KHÔNG thêm section Checklist SEO trong bài;"
        " không markdown, không lời dẫn ngoài thẻ."
        f" BẮT BUỘC đạt độ dài mục tiêu {wc_for_content} từ (±10%); không dừng khi bài còn quá ngắn."
    )
    user = f"{instructions}\n\n=== SOURCE (chỉ dùng phần này) ===\n{source_blob}\n\n=== OUTPUT ==="

    if cfg.provider == "openai":
        msg = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        yield from _iter_openai_chat_completion_deltas(
            cfg=cfg, messages=msg, max_tokens=oai_mt, timeout_sec=api_timeout
        )
        return

    out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=ant_mt, timeout_sec=api_timeout)
    yield from _iter_text_as_deltas(out, chunk_size=40)


def _anthropic_messages(
    *,
    cfg: LlmConfig,
    system: str,
    user: str,
    max_tokens: int = 1600,
    timeout_sec: int = 45,
) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    mt = max(256, min(8192, int(max_tokens)))
    payload: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": mt,
        "temperature": cfg.temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    def _post() -> requests.Response:
        return requests.post(url, headers=headers, json=payload, timeout=timeout_sec)

    if cost_control_enforced():
        from app.services.cost_control.module_gates import llm_provider_for_config

        r = execute_guarded_external(
            llm_provider_for_config(cfg),
            "messages",
            _post,
            is_retryable=http_error_retryable,
        )
    else:
        r = _post()
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic HTTP {r.status_code}: {(r.text or '')[:400]}")
    data = r.json() if r.content else {}
    try:
        blocks = data.get("content") or []
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
        return _clean_ws("\n".join(parts)).strip()
    except Exception as exc:
        raise RuntimeError("Anthropic response parse failed") from exc


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def run_seo_score_ai_fix_completion(
    *,
    cfg: LlmConfig,
    system: str,
    user_prompt: str,
    max_tokens: int = 1200,
    timeout_sec: int = 60,
) -> str:
    """LLM completion riêng cho SEO Score AI fix — tách khỏi pipeline Content AI."""
    if cfg.provider == "openai":
        return _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
        )
    return _anthropic_messages(cfg=cfg, system=system, user=user_prompt)


def generate_seo_article_json(
    *,
    keyword: str,
    secondary_keywords: list[str] | None = None,
    intent: str = "",
    audience: str = "",
    brand_name: str = "",
    outline: str = "",
    context_data: str = "",
) -> dict[str, Any]:
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    kw = _clean_ws(keyword)
    if not kw:
        raise RuntimeError("keyword is required")
    lsi = secondary_keywords or []
    lsi_clean = [re.sub(r"\s+", " ", str(x or "").strip()) for x in lsi if str(x or "").strip()]
    lsi_clean = lsi_clean[:20]

    system = "Bạn là copywriter và biên tập. Ưu tiên chính xác, hữu ích cho độc giả; không dùng placeholder [CẦN XÁC NHẬN]."
    user = (
        "Bạn PHẢI trả về đúng 1 JSON object hợp lệ (không markdown, không code fence, không giải thích).\n"
        "\n"
        "Mục tiêu:\n"
        "- Bài có giá trị thực, đúng nhu cầu tìm kiếm; viết cho người đọc, không giải thích khái niệm SEO\n"
        "- Nội dung chính xác; thiếu dữ kiện thì trung tính hoặc minh họa, không placeholder\n"
        "- Văn phong human-like: ưu tiên “Tôi/Mình/Chúng tôi”, có trải nghiệm thực tế khi phù hợp\n"
        "- Cấu trúc rõ, dễ đọc, có lời kêu gọi phù hợp khi là chủ đề dịch vụ\n"
        "\n"
        "INPUT:\n"
        f"- Keyword chính: {kw}\n"
        f"- Keyword phụ (LSI): {', '.join(lsi_clean)}\n"
        f"- Search intent: {str(intent or '').strip()}\n"
        f"- Đối tượng đọc: {str(audience or '').strip()}\n"
        f"- Brand: {str(brand_name or '').strip()}\n"
        f"- Outline (nếu có): {str(outline or '').strip()}\n"
        f"- Context (crawl/top SERP nếu có): {str(context_data or '').strip()}\n"
        "\n"
        "NGUYÊN TẮC (BẮT BUỘC):\n"
        "1) Trả lời trực tiếp vấn đề trong 2 câu đầu.\n"
        "2) Không lan man; mỗi đoạn 2–3 câu, ≤ 3 dòng.\n"
        "3) 1 H1 duy nhất (chứa keyword chính), ≥ 3 H2; H2 đầu tiên chứa keyword chính/biến thể.\n"
        "4) Keyword chính: có trong H1, trong ~100 ký tự đầu, và H2 đầu tiên; mật độ ~1%, không spam.\n"
        "5) TITLE: 50–60 ký tự, keyword ở đầu, không giật tít.\n"
        "6) META: 150–160 ký tự, có keyword chính + brand.\n"
        "7) UX: có bullet list, có bảng, có blockquote, có in đậm ý quan trọng.\n"
        "8) Media: gợi ý vị trí ảnh cho mỗi H2 (ghi chú trong HTML), alt có nghĩa + keyword; có 1 video embed (iframe).\n"
        "9) Link: có internal link placeholder + 1 external link uy tín (Wikipedia hoặc site uy tín) nếu phù hợp.\n"
        "10) E-E-A-T: có author thật + bio cuối bài (nếu thiếu dữ kiện thì viết trung tính).\n"
        "\n"
        "OUTPUT FORMAT (JSON):\n"
        "{\n"
        '  \"title\": \"...\",\n'
        '  \"meta_description\": \"...\",\n'
        '  \"slug\": \"...\",\n'
        '  \"content_html\": \"...\",\n'
        '  \"tags\": [\"...\"],\n'
        '  \"excerpt\": \"...\",\n'
        '  \"schema\": { \"article\": \"...\", \"author\": \"...\", \"faq\": \"...\" }\n'
        "}\n"
        "\n"
        "Ràng buộc output:\n"
        "- content_html phải là HTML hợp lệ (có <h1>...)</n"
        "- schema.* là JSON-LD string (mỗi field là 1 chuỗi chứa JSON-LD)\n"
        "- Không được trả về null; thiếu thì dùng chuỗi rỗng hoặc mảng rỗng.\n"
    ).strip()

    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user)

    obj = _try_parse_json_object(out)
    if obj is None:
        fixer = (
            "Bạn đã tạo output nhưng nó chưa phải JSON object hợp lệ.\n"
            "Hãy CHỈ trả về 1 JSON object hợp lệ đúng schema yêu cầu, không thêm chữ nào khác.\n"
            "\n"
            "=== OUTPUT CẦN SỬA ===\n"
            f"{out}\n"
            "\n"
            "=== JSON HỢP LỆ ===\n"
        )
        if cfg.provider == "openai":
            out2 = _openai_chat_completion(
                cfg=cfg,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": fixer}],
            )
        else:
            out2 = _anthropic_messages(cfg=cfg, system=system, user=fixer)
        obj = _try_parse_json_object(out2)
        if obj is None:
            raise RuntimeError("Model did not return valid JSON.")

    def _s(x: Any) -> str:
        return str(x or "").strip()

    tags_val = obj.get("tags")
    tags_out: list[str] = []
    if isinstance(tags_val, list):
        for t in tags_val[:20]:
            tt = re.sub(r"\s+", " ", str(t or "").strip())
            if tt:
                tags_out.append(tt)

    schema_val = obj.get("schema") if isinstance(obj.get("schema"), dict) else {}
    schema_out = {
        "article": _s((schema_val or {}).get("article")),
        "author": _s((schema_val or {}).get("author")),
        "faq": _s((schema_val or {}).get("faq")),
    }

    html_body = _sanitize_mixed_style_phrases(_strip_bracket_placeholders(_s(obj.get("content_html"))))
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes

    from app.services.content_ai_publish_checklist import strip_publish_checklist_from_html
    from app.services.content_table_format import enhance_tables_in_html

    html_body = enhance_tables_in_html(
        strip_publish_checklist_from_html(postprocess_content_blockquotes(html_body))
    )
    return {
        "title": _s(obj.get("title")),
        "meta_description": _s(obj.get("meta_description")),
        "slug": _s(obj.get("slug")),
        "content_html": html_body,
        "tags": tags_out,
        "excerpt": _s(obj.get("excerpt")),
        "schema": schema_out,
    }


def optimize_seo_content_html(*, content_html: str) -> str:
    """
    SEO Editor: rewrite existing HTML to be clearer, accurate, human-like and SEO-friendly.
    Must return clean HTML (no markdown / no code fences).
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")

    html = str(content_html or "").strip()
    if not html:
        return ""
    # Guard cost / latency.
    html = html[:18000]

    system = "Bạn là biên tập nội dung. Ưu tiên chính xác, rõ ràng, tự nhiên. Không bịa; xóa placeholder [CẦN XÁC NHẬN] bằng câu hoàn chỉnh."
    user = (
        "Nhiệm vụ: Tối ưu lại content cho dễ đọc, mạch lạc:\n"
        "- Logic rõ ràng\n"
        "- Không sai fact\n"
        "- Không lan man\n"
        "- Giọng tự nhiên, vì người đọc (không meta-bình về SEO hay service page)\n"
        "\n"
        "FIX:\n"
        "1) Sửa sai logic, câu khó hiểu, nội dung vô nghĩa.\n"
        "2) Tối ưu: ngắn gọn hơn, tăng readability, thêm trải nghiệm cá nhân nếu thiếu (nhưng không bịa).\n"
        "3) Loại bỏ: AI tone, lặp ý, keyword stuffing.\n"
        "\n"
        "Ràng buộc bắt buộc:\n"
        "- Trả về HTML sạch.\n"
        "- Giữ nguyên cấu trúc heading hiện có (giữ 1 H1 nếu có, giữ hệ H2/H3; không phá cấp heading).\n"
        "- Không thêm claim/số liệu mới nếu không có trong bài.\n"
        "- Không trả về markdown, không code fence.\n"
        "\n"
        "INPUT (HTML):\n"
        f"{html}\n"
        "\n"
        "OUTPUT (HTML sạch):\n"
    ).strip()

    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user)

    cleaned = str(out or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    cleaned = _strip_bracket_placeholders(cleaned)
    return _sanitize_mixed_style_phrases(cleaned)


def suggest_internal_link_row_keywords(
    *,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    target_post_title: str = "",
    target_post_url: str = "",
    target_categories: str = "",
    target_tags: str = "",
    content_snippet: str = "",
) -> dict[str, str]:
    """
    Gợi ý từ khóa (chính/phụ) + một anchor ngắn cho một URL đích — trả JSON object.
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")
    system = (
        "Bạn là chuyên gia SEO nội dung. Trả về đúng 1 JSON object (không markdown, không code fence).\n"
        "Các key bắt buộc: primary_keyword (string), secondary_keywords (string, có thể nhiều từ cách nhau dấu phẩy), "
        "anchor_suggestion (string, 2–8 từ tiếng Việt, tự nhiên, mô tả đúng bài đích, phù hợp làm anchor internal link).\n"
        "anchor_suggestion phải ngắn gọn, không clickbait, không 'tại đây'."
    )
    user = (
        "Bài đang viết (ngữ cảnh):\n"
        f"- Từ khóa chính bài hiện tại: { _clean_ws(article_primary_keyword) }\n"
        f"- Từ khóa phụ bài hiện tại: { _clean_ws(article_secondary_keywords) }\n"
        f"- Đoạn trích content hiện tại (có thể rút): {_truncate_text(_clean_ws(content_snippet), max_chars=2200)}\n\n"
        "Bài viết đích cần trỏ internal link:\n"
        f"- Tiêu đề: {_clean_ws(target_post_title)}\n"
        f"- URL: {_clean_ws(target_post_url)}\n"
        f"- Chuyên mục (nếu có): {_clean_ws(target_categories)}\n"
        f"- Tag (nếu có): {_clean_ws(target_tags)}\n\n"
        "Nhiệm vụ:\n"
        "- primary_keyword: 1 cụm từ khóa chính mô tả đúng chủ đề bài ĐÍCH (có thể khác từ khóa bài đang viết).\n"
        "- secondary_keywords: 3–8 từ/cụm phụ liên quan bài đích (LSI), cách nhau bởi dấu phẩy.\n"
        "- anchor_suggestion: 1 anchor text đề xuất (có thể trùng hoặc gần với primary_keyword).\n"
    ).strip()
    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=400,
            timeout_sec=45,
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=500, timeout_sec=45)
    parsed = _try_parse_json_object(out) or {}
    return {
        "primary_keyword": str(parsed.get("primary_keyword") or "").strip(),
        "secondary_keywords": str(parsed.get("secondary_keywords") or "").strip(),
        "anchor_suggestion": str(parsed.get("anchor_suggestion") or "").strip(),
    }


def rewrite_html_insert_internal_links(
    *,
    content_html: str,
    link_jobs: list[dict[str, str]],
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    minimal: bool = False,
) -> str:
    """
    Chèn internal link vào HTML bài đang soạn.
    minimal=True: giữ nguyên bài, chỉ thêm đoạn/câu ngắn (tiết kiệm token, không viết lại cả bài).
    link_jobs: [{"url", "title", "anchor_text"}] — anchor_text bắt buộc (đã chọn/điền).
    """
    cfg = load_llm_config()
    if not cfg:
        raise RuntimeError("LLM not configured (missing API key).")
    html = str(content_html or "").strip()
    if not html:
        return ""
    html = html[:56000]
    jobs = []
    for it in link_jobs or []:
        if not isinstance(it, dict):
            continue
        u = str(it.get("url") or "").strip()
        t = str(it.get("title") or "").strip()
        a = str(it.get("anchor_text") or "").strip() or t
        if u and t:
            jobs.append({"url": u, "title": t, "anchor_text": a})
    if not jobs:
        return content_html

    jobs_json = json.dumps(jobs, ensure_ascii=False)
    if minimal:
        system = (
            "Bạn là biên tập HTML tiếng Việt. Bài viết ĐÃ CHUẨN — chỉ chèn internal link, KHÔNG viết lại bài.\n"
            "Ràng buộc bắt buộc:\n"
            "- Trả về DUY NHẤT HTML hợp lệ (không markdown, không giải thích).\n"
            "- GIỮ NGUYÊN 100% mọi đoạn/câu/heading/ảnh đã có — không paraphrase, không xóa, không đổi thứ tự section.\n"
            "- Với MỖI link trong LINKS_JSON: chèn đúng 1 thẻ <a href=\"URL\">ANCHOR_TEXT</a> (đúng URL và anchor_text).\n"
            "- Nếu anchor_text đã có trong một câu: chỉ bọc cụm đó bằng <a>, không sửa câu khác.\n"
            "- Nếu anchor chưa có: thêm TỐI ĐA một thẻ <p> mới (1–2 câu ngắn) ngay sau đoạn/section liên quan, rồi gắn link.\n"
            "- Không chèn link trong H1/H2/H3; không sửa đoạn đã có <a>.\n"
            "- Không nhồi keyword; không dùng 'tại đây', 'click here'.\n"
        )
        user = (
            f"Từ khóa chính: {_clean_ws(article_primary_keyword)}\n"
            f"Từ khóa phụ: {_clean_ws(article_secondary_keywords)}\n\n"
            "LINKS_JSON:\n"
            f"{jobs_json}\n\n"
            "HTML_GỐC (chỉ được bổ sung tối thiểu, không rewrite toàn bài):\n"
            f"{html}\n\n"
            "Trả về HTML sau khi chèn link."
        ).strip()
        max_tok = 4500
        timeout = 90
    else:
        system = (
            "Bạn là biên tập viên HTML tiếng Việt. Nhiệm vụ: chỉnh sửa bài để chèn internal link tự nhiên, đúng ngữ cảnh.\n"
            "Ràng buộc:\n"
            "- Trả về DUY NHẤT HTML hợp lệ (không markdown, không code fence, không giải thích ngoài HTML).\n"
            "- Giữ nguyên ý chính và cấu trúc heading (H1/H2/H3) tương đương bản gốc; được phép thêm/cắt ngắn câu để neo link hợp lý.\n"
            "- Với MỖI mục trong LINKS_JSON: chèn đúng 1 thẻ <a href=\"URL\">ANCHOR_TEXT</a> dùng ĐÚNG URL và ĐÚNG anchor_text đã cho (không đổi wording anchor trừ khi sửa lỗi chính tả nhẹ).\n"
            "- Text hiển thị trong thẻ <a>...</a> phải trùng anchor_text (Unicode có dấu đầy đủ như đã cho); không rút gọn, không thay từ đồng nghĩa.\n"
            "- Nếu anchor_text chưa xuất hiện trong bài: thêm một câu ngắn trong đoạn liên quan chủ đề rồi gắn link vào anchor đó.\n"
            "- Không nhồi keyword; không dùng anchor chung chung kiểu 'click here', 'tại đây'.\n"
            "- Không xóa ảnh/media có sẵn; không đổi URL ảnh.\n"
        )
        user = (
            f"Từ khóa chính bài hiện tại: {_clean_ws(article_primary_keyword)}\n"
            f"Từ khóa phụ: {_clean_ws(article_secondary_keywords)}\n\n"
            "LINKS_JSON (bắt buộc dùng đủ các link):\n"
            f"{jobs_json}\n\n"
            "HTML_GỐC:\n"
            f"{html}\n\n"
            "Trả về HTML đã chèn link."
        ).strip()
        max_tok = 12000
        timeout = 120
    if cfg.provider == "openai":
        out = _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tok,
            timeout_sec=timeout,
        )
    else:
        out = _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=max_tok, timeout_sec=timeout)
    cleaned = str(out or "").strip()
    cleaned = re.sub(r"^```(?:html)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    cleaned = _strip_bracket_placeholders(cleaned)
    return _sanitize_mixed_style_phrases(cleaned)


def _repair_brief_field_primary_keyword_with_llm(
    *,
    field: str,
    line: str,
    pk: str,
    cfg: LlmConfig,
    system: str,
    api_timeout: int,
    strict: bool = False,
) -> str:
    """Sửa brief field bằng LLM khi output không bám PRIMARY_KEYWORD/địa danh."""
    from app.services.content_draft_builder import content_ai_extract_geo_tail

    geo = content_ai_extract_geo_tail(pk)
    geo_line = ""
    if geo:
        geo_line = (
            f"- Bắt buộc giữ địa danh «{geo}» đúng như PRIMARY_KEYWORD; "
            "không thay bằng Thủ Dầu Một hay bất kỳ địa danh nào khác.\n"
        )
    strict_line = ""
    if strict:
        strict_line = (
            f"- OUTPUT phải chứa NGUYÊN VĂN PRIMARY_KEYWORD «{pk}» "
            "(chỉ được viết hoa chữ cái đầu).\n"
            "- TUYỆT ĐỐI KHÔNG dùng địa danh không có trong PRIMARY_KEYWORD.\n"
        )
    repair_user = (
        f"Output sau KHÔNG bám PRIMARY_KEYWORD «{pk}».\n"
        f"Hãy viết lại đúng 1 dòng cho field «{field}», tuân thủ instruction ban đầu.\n"
        f"- Phải chứa PRIMARY_KEYWORD hoặc địa danh «{geo or pk}».\n"
        + geo_line
        + strict_line
        + f"=== OUTPUT SAI ===\n{line}\n\n=== OUTPUT (1 dòng) ==="
    )
    repaired = _llm_chat_for_cfg(
        cfg=cfg,
        system=system,
        user=repair_user,
        max_tokens_oai=200,
        max_tokens_ant=220,
        timeout_sec=min(api_timeout, 25),
    )
    return _first_line(repaired)


def generate_content_ai_suggestion(
    *,
    field: str,
    title: str = "",
    content: str = "",
    target_website: str = "",
    slug: str = "",
    tags: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    target_word_count: int | None = None,
    user_id: int | None = None,
    use_system_llm: bool = False,
    ai_provider: str = "auto",
    meta_out: dict[str, Any] | None = None,
) -> str:
    """
    Lớp LLM (sinh nội dung / gợi ý theo field), tách khỏi rule-based trong `content_draft_builder`.

    Intent/signal địa phương lấy từ `detect_search_intent` / `content_ai_has_local_service_signal` (cùng nguồn với UI).
    Trả về một chuỗi tương thích API /content-ai/suggest.
    """
    from app.services.content_ai_knowledge_context import ContentAiLlmUnavailableError
    from app.services.content_ai_llm_providers import (
        call_with_provider_fallback,
        openai_direct_available,
        resolve_suggest_brief_chain,
    )

    del use_system_llm

    env_local = _read_env_local()
    llm_mode = (_getenv("CONTENT_AI_LLM_MODE", env_local) or "auto").strip().lower()
    if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
        llm_mode = "auto"
    skip_rule_html = llm_mode == "auto"

    pk = _clean_ws(primary_keyword)
    sec = _clean_ws(secondary_keywords)
    t = str(title or "").strip()
    f0 = (field or "").strip().lower()
    outline = (outline_content or "").strip()
    if skip_rule_html and f0 == "content" and outline and _looks_like_generic_template(outline):
        outline = ""
    user_outline_present = bool(outline)

    from app.services.content_ai_knowledge_context import assert_single_writer_source_ready

    if f0 in {
        "title",
        "meta_description",
        "outline_content",
        "content",
        "slug",
        "tags",
        "secondary_keywords",
    }:
        assert_single_writer_source_ready(
            primary_keyword=pk,
            target_website=target_website,
            content=content,
            outline_content=outline,
            title=t,
            field=f0,
            user_id=user_id,
        )

    wc_for_content: int | None = None
    outline_stats: dict[str, int] = {"h1": 0, "h2": 0, "h3": 0}
    if f0 == "content":
        wc_for_content = resolve_wc_for_content(target_word_count)
        if user_outline_present and outline:
            outline_stats = _outline_heading_stats(outline)
            wc_for_content = _effective_word_count_for_outline(base_wc=wc_for_content, outline=outline)

    # Outline/title/meta thường >12s khi có website context + research — default cũ gây popup 503 giả.
    if f0 == "content":
        api_timeout = int(_getenv("CONTENT_AI_LLM_TIMEOUT_CONTENT", env_local) or "120")
    elif f0 == "outline_content":
        api_timeout = int(_getenv("CONTENT_AI_LLM_TIMEOUT_OUTLINE", env_local) or "90")
    else:
        api_timeout = int(_getenv("CONTENT_AI_LLM_TIMEOUT_BRIEF", env_local) or "22")
    api_timeout = max(15, min(int(api_timeout or 60), 180))
    brief_suggest = f0 in {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
    }
    if brief_suggest:
        api_timeout = min(api_timeout, 22)
    oai_mt = _openai_max_tokens_for_field(field=f0, word_target=wc_for_content)
    ant_mt = _anthropic_max_tokens_for_field(field=f0, word_target=wc_for_content)
    if f0 == "content" and user_outline_present and outline:
        oai_mt = _boost_max_tokens_for_outline(int(oai_mt or 4096), outline, cap=16384)
        ant_mt = _boost_max_tokens_for_outline(int(ant_mt or 4096), outline, cap=8192)

    src_url = ""
    src_text = ""
    related_posts: list[dict[str, str]] = []
    # Chỉ crawl website + bài liên quan cho nội dung/dàn ý — field ngắn gọi LLM trực tiếp (nhanh hơn).
    if str(target_website or "").strip() and f0 in {"content", "outline_content"}:
        from app.services.content_ai_write_timing import STEP_WEBSITE_CONTEXT, mark_step

        mark_step(STEP_WEBSITE_CONTEXT, target_website=str(target_website or "")[:120])
        (src_url, src_text), related_posts = _fetch_website_context_bundle(
            str(target_website or "").strip(), pk, related_limit=10 if f0 == "content" else 6
        )
        src_text = _truncate_text(src_text, max_chars=9000 if f0 == "content" else 5500)
        if f0 != "content":
            related_posts = []

    # Let user-provided notes be part of SOURCE too (but clearly labeled).
    notes = _truncate_text(_clean_ws(content), max_chars=3500) if content else ""
    outline_src = _truncate_text(outline, max_chars=10000) if outline else ""

    source_parts: list[str] = []
    if pk:
        source_parts.append(f"PRIMARY_KEYWORD: {pk}")
    if sec:
        source_parts.append(f"SECONDARY_KEYWORDS: {sec}")
    if t:
        source_parts.append(f"TITLE_DRAFT: {t}")
    if slug:
        source_parts.append(f"SLUG_DRAFT: {slug}")
    if tags:
        source_parts.append(f"TAGS_DRAFT: {tags}")
    if meta_description:
        source_parts.append(f"META_DESCRIPTION_DRAFT: {meta_description}")
    if outline_src:
        source_parts.append("OUTLINE_SOURCE:\n" + outline_src)
    if notes:
        source_parts.append("NOTES_SOURCE:\n" + notes)
    if src_text:
        source_parts.append(f"WEBSITE_SOURCE_URL: {src_url}")
        source_parts.append("WEBSITE_SOURCE_TEXT:\n" + src_text)
    if related_posts:
        rel_lines = []
        for i, item in enumerate(related_posts, start=1):
            t_rel = str(item.get("title") or "").strip()
            u_rel = str(item.get("url") or "").strip()
            if not t_rel or not u_rel:
                continue
            rel_lines.append(f"{i}. {t_rel} | {u_rel}")
        if rel_lines:
            source_parts.append("RELATED_ARTICLES:\n" + "\n".join(rel_lines))

    knowledge: dict[str, Any] | None = None
    if pk and f0 in {"content", "outline_content"}:
        try:
            from app.services.content_ai_knowledge_context import (
                build_outline_context_from_knowledge,
                get_relevant_knowledge_for_keyword,
            )
            from app.services.content_ai_request_cache import cache_get_or_set
            from app.services.content_ai_write_timing import STEP_RESEARCH, mark_step

            mark_step(STEP_RESEARCH, keyword=pk[:80])
            knowledge = cache_get_or_set(
                f"kb:{pk.lower()}:{str(target_website or '').lower()}:{int(user_id or 0)}",
                lambda: get_relevant_knowledge_for_keyword(
                    pk,
                    target_website=str(target_website or ""),
                    user_id=user_id,
                ),
            )
            if knowledge and knowledge.get("found"):
                kb_ctx = build_outline_context_from_knowledge(knowledge)
                if kb_ctx:
                    source_parts.append("KNOWLEDGE_BASE:\n" + kb_ctx)
        except Exception:
            knowledge = None

    outline_diversity_extra = ""
    if f0 == "outline_content" and pk:
        from app.services.content_ai_outline_engine import (
            build_outline_diversity_instruction,
            classify_article_type,
        )

        article_type = classify_article_type(pk, knowledge=knowledge)
        brand_hint = str((knowledge or {}).get("brand_name") or "").strip()
        outline_diversity_extra = build_outline_diversity_instruction(
            article_type=article_type,
            primary_keyword=pk,
            brand=brand_hint,
            variant="A",
        )

    source_blob = "\n\n".join(source_parts).strip() or "SOURCE: (trống)"
    instructions = _build_instructions(
        field=field,
        target_word_count=wc_for_content if f0 == "content" else target_word_count,
        primary_keyword=pk,
        llm_mode=llm_mode,
        user_outline_present=user_outline_present,
        knowledge=knowledge,
        outline_h2_count=int(outline_stats.get("h2") or 0),
        outline_h3_count=int(outline_stats.get("h3") or 0),
        outline_diversity_extra=outline_diversity_extra,
    )

    f_early = (field or "").strip().lower()
    kb_active = bool(knowledge and knowledge.get("found"))
    system = (
        "Bạn là trợ lý viết nội dung SEO tiếng Việt: chính xác, hữu ích (Helpful Content), E-E-A-T."
        " Chỉ dùng SOURCE; không bịa số liệu/giá."
    )
    if kb_active:
        system += (
            " Ưu tiên KNOWLEDGE_BASE trong SOURCE cho bảng giá, SĐT/hotline, thông tin công ty, quy trình, FAQ;"
            " không ghi «Cần bổ sung dữ liệu» khi KB/SOURCE đã có thông tin đó."
        )
    else:
        system += " Thiếu dữ liệu trong SOURCE → «Cần bổ sung dữ liệu»."
    system += " Không nhồi từ khóa; không placeholder [CẦN XÁC NHẬN]."
    if f_early == "content":
        system += (
            " Field content: chỉ HTML thuần (h1–h3, p, list, table, figure+alt, FAQ,"
            " gợi ý link nội/ngoài, JSON-LD schema); KHÔNG thêm section Checklist SEO trong bài;"
            " không markdown, không lời dẫn ngoài thẻ."
        )
    elif f_early in {"title", "meta_description", "slug", "outline_content"}:
        system += " Tuân thủ đúng giới hạn độ dài và định dạng field; trả về đúng 1 output, không giải thích."
    elif f_early in {"secondary_keywords", "tags"}:
        system += (
            " Field này là danh sách keyword/tag ngắn cách nhau dấu phẩy;"
            " KHÔNG viết meta description hay đoạn giới thiệu dịch vụ."
        )
    user = f"{instructions}\n\n=== SOURCE (chỉ dùng phần này) ===\n{source_blob}\n\n=== OUTPUT ==="

    from app.services.content_ai_write_timing import STEP_LLM, STEP_OUTLINE, STEP_REPAIR, STEP_WORD_COUNT, mark_step

    if f0 == "outline_content":
        mark_step(STEP_OUTLINE)
    mark_step(STEP_LLM, field=f0)

    section_write_eligible = False
    if f0 == "content" and user_outline_present and outline:
        from app.services.content_ai_outline_engine import parse_outline_sections

        section_write_eligible = len(parse_outline_sections(outline)) >= 2
        if section_write_eligible:
            n_h2 = len(parse_outline_sections(outline))
            api_timeout = min(180, max(api_timeout, 90 + n_h2 * 10))

    def _run_field_llm(c: LlmConfig) -> str:
        if section_write_eligible:
            from app.services.content_ai_section_writer import write_content_by_outline_sections

            def _section_llm(*, system: str, user: str) -> str:
                return _llm_chat_for_cfg(
                    cfg=c,
                    system=system,
                    user=user,
                    max_tokens_oai=oai_mt,
                    max_tokens_ant=ant_mt,
                    timeout_sec=api_timeout,
                )

            section_html = write_content_by_outline_sections(
                outline=outline,
                total_wc=int(wc_for_content or 1000),
                primary_keyword=pk,
                title=t,
                source_blob=source_blob,
                system=system,
                llm_call=_section_llm,
            )
            if section_html and section_html.strip():
                logging.getLogger(__name__).info("content_ai_section_write used h2_count=%s", len(parse_outline_sections(outline)))
                return section_html
        return _llm_call_once(cfg=c, timeout_sec=api_timeout)

    cfg: LlmConfig | None = None
    route = None
    brief_openai_direct = brief_suggest and openai_direct_available()

    def _llm_call_once(*, cfg: LlmConfig, timeout_sec: int) -> str:
        return _llm_chat_for_cfg(
            cfg=cfg,
            system=system,
            user=user,
            max_tokens_oai=oai_mt,
            max_tokens_ant=ant_mt,
            timeout_sec=timeout_sec,
        )

    def _is_read_timeout(exc: BaseException) -> bool:
        msg = str(exc or "").lower()
        return any(
            x in msg
            for x in (
                "read timed out",
                "readtimeout",
                "timed out",
                "timeout",
            )
        )

    try:
        out, route = call_with_provider_fallback(
            ai_provider="openai" if brief_openai_direct else ai_provider,
            field=f0,
            target_word_count=wc_for_content if f0 == "content" else target_word_count,
            fn=_run_field_llm,
            chain_override=resolve_suggest_brief_chain() if brief_openai_direct else None,
            allow_fallback=not brief_openai_direct,
        )
        cfg = route.cfg if route else None
        if cfg is None:
            raise ContentAiLlmUnavailableError("llm_not_configured")
        if meta_out is not None and route is not None:
            meta_out["ai_provider"] = route.provider_used
            meta_out["ai_provider_requested"] = route.provider_requested
            meta_out["provider_fallback_applied"] = bool(route.fallback_applied)
            meta_out["provider_fallback_notice"] = route.fallback_notice or ""
    except ContentAiLlmUnavailableError:
        raise
    except Exception as exc:
        if "llm_not_configured" in str(exc).lower():
            raise ContentAiLlmUnavailableError("llm_not_configured") from exc
        if not _is_read_timeout(exc) or cfg is None or brief_suggest:
            raise
        retry_timeout = min(180, max(api_timeout + 30, int(api_timeout * 1.5)))
        logger = logging.getLogger(__name__)
        logger.warning(
            "content_ai_llm_timeout_retry field=%s from=%ss to=%ss err=%s",
            f0,
            api_timeout,
            retry_timeout,
            str(exc)[:200],
        )
        out = _llm_call_once(cfg=cfg, timeout_sec=retry_timeout)
    if f0 == "content" and not str(out or "").strip():
        rescue_user = (
            "Bạn vừa trả output rỗng. Hãy trả về NGAY 1 bài HTML đầy đủ cho cùng SOURCE.\n"
            "Bắt buộc: 1 <h1>, ≥4 <h2>, keyword trong 100 từ đầu, FAQ,"
            " ít nhất 1 list/table, figure+alt mỗi H2, gợi ý internal/external link, JSON-LD schema."
            " Không thêm section Checklist SEO.\n"
            "Chỉ trả về HTML sạch, không markdown, không giải thích.\n"
            "\n=== SOURCE ===\n"
            f"{source_blob}\n"
            "\n=== OUTPUT (HTML) ==="
        )
        out = _llm_chat_for_cfg(
            cfg=cfg,
            system=system,
            user=rescue_user,
            max_tokens_oai=oai_mt,
            max_tokens_ant=ant_mt,
            timeout_sec=api_timeout,
        )

    f = (field or "").strip().lower()

    fast_suggest = (_getenv("CONTENT_AI_SUGGEST_FAST", env_local) or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    if f == "content" and detect_search_intent(pk) == "transactional" and not fast_suggest:
        # Validate transactional/actionability before finalizing; rewrite if needed.
        for _ in range(2):
            cur = extract_clean_html_fragment(_sanitize_mixed_style_phrases(str(out or "").strip()))
            gaps = _transactional_gaps(cur)
            if not gaps:
                out = cur
                break
            rewrite_user = (
                "Nội dung dưới đây CHƯA đạt intent transactional/action.\n"
                "Hãy viết lại TOÀN BỘ: thuyết phục khách đặt dịch vụ / liên hệ ngay (không giải thích SEO, không nhắc service page).\n"
                "BẮT BUỘC có đủ: (1) dịch vụ cung cấp, (2) dấu hiệu tin cậy, (3) hạng mục bao gồm, (4) chi phí/bảng giá, (5) liên hệ ngay.\n"
                "Không viết blog, không lý thuyết, không phản tư cá nhân; không dùng [CẦN XÁC NHẬN] hay placeholder.\n"
                "Chỉ trả về HTML sạch.\n"
                f"\nCác điểm thiếu:\n- " + "\n- ".join(gaps) + "\n"
                "\n=== HTML HIỆN TẠI ===\n"
                f"{cur}\n"
                "\n=== OUTPUT (HTML) ==="
            )
            out = _llm_chat_for_cfg(
                cfg=cfg,
                system=system,
                user=rewrite_user,
                max_tokens_oai=oai_mt,
                max_tokens_ant=ant_mt,
                timeout_sec=api_timeout,
            )

    # Normalize single-line fields even if model outputs multiple lines.
    if f in {"title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords", "target_website"}:
        line = _first_line(out)
        if f in {"title", "meta_description"}:
            line = _strip_bracket_placeholders(line)
        if f in {"secondary_keywords", "tags"}:
            line = _normalize_comma_keyword_field(line, field=f)
            if _looks_like_prose_keyword_field(line) and not fast_suggest:
                repair_user = (
                    f"Đoạn sau KHÔNG đúng định dạng {f}. "
                    "Hãy chuyển thành danh sách cụm từ ngắn (keyword/tag), cách nhau dấu phẩy, "
                    "không câu văn, không meta description, không CTA.\n"
                    f"=== INPUT ===\n{line}\n\n=== OUTPUT (1 dòng) ==="
                )
                line = _llm_chat_for_cfg(
                    cfg=cfg,
                    system=system,
                    user=repair_user,
                    max_tokens_oai=160,
                    max_tokens_ant=180,
                    timeout_sec=min(api_timeout, 20),
                )
                line = _normalize_comma_keyword_field(_first_line(line), field=f)
        if f in {"title", "meta_description", "secondary_keywords"} and pk:
            from app.services.content_draft_builder import (
                content_ai_brief_field_honors_primary_keyword,
                content_ai_finalize_brief_field_value,
            )

            for attempt in range(2):
                if content_ai_brief_field_honors_primary_keyword(field=f, text=line, pk=pk):
                    break
                if cfg is None:
                    break
                line = _repair_brief_field_primary_keyword_with_llm(
                    field=f,
                    line=line,
                    pk=pk,
                    cfg=cfg,
                    system=system,
                    api_timeout=api_timeout,
                    strict=attempt >= 1,
                )
                if f in {"title", "meta_description"}:
                    line = _strip_bracket_placeholders(line)
                if f in {"secondary_keywords", "tags"}:
                    line = _normalize_comma_keyword_field(line, field=f)
            line = content_ai_finalize_brief_field_value(field=f, text=line, pk=pk)
            if f in {"title", "meta_description"}:
                line = _strip_bracket_placeholders(line)
            if f in {"secondary_keywords", "tags"}:
                line = _normalize_comma_keyword_field(line, field=f)
        return line
    out = str(out or "").strip()
    raw_out = out
    if f in {"content", "outline_content"}:
        out = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", out).strip()
        out = re.sub(r"\s*```\s*$", "", out).strip()
    if f == "content":
        from app.services.content_ai_knowledge_context import ContentAiLlmUnavailableError

        out = _decode_html_entities_text(out)
        out_html = extract_clean_html_fragment(out)
        if not out_html:
            raise ContentAiLlmUnavailableError("llm_empty_content_html")
        out = out_html
        out = _strip_bracket_placeholders(out)
        out = _sanitize_mixed_style_phrases(out)
        if user_outline_present and outline and cfg is not None:
            from app.services.content_ai_outline_engine import outline_h2_coverage

            cov = outline_h2_coverage(outline, out)
            if cov["ratio"] < 0.99 or cov.get("missing_sections"):
                mark_step(STEP_REPAIR, outline_coverage=f"{cov['covered']}/{cov['total']}")
                out = _continue_content_for_missing_outline(
                    html=out,
                    outline=outline,
                    wc_target=int(wc_for_content or 1000),
                    cfg=cfg,
                    system=system,
                    oai_mt=oai_mt,
                    ant_mt=ant_mt,
                    api_timeout=api_timeout,
                    source_blob=source_blob,
                    primary_keyword=pk,
                )
                out = extract_clean_html_fragment(str(out or "").strip()) or out
                out = _strip_bracket_placeholders(out)
                out = _sanitize_mixed_style_phrases(out)
        if wc_for_content is not None:
            from app.services.content_ai_word_count_policy import (
                needs_word_count_repair,
                needs_word_count_trim,
                word_count_from_html,
            )

            actual_wc = word_count_from_html(out)
            mark_step(STEP_WORD_COUNT, actual=actual_wc, target=wc_for_content)
            if needs_word_count_repair(actual_wc, wc_for_content) or needs_word_count_trim(
                actual_wc, wc_for_content
            ):
                if not fast_suggest:
                    mark_step(STEP_REPAIR, actual=actual_wc, target=wc_for_content)
                    out = _enforce_content_word_count_with_llm(
                        out,
                        wc_for_content=wc_for_content,
                        cfg=cfg,
                        system=system,
                        pk=pk,
                        title=t,
                        oai_mt=oai_mt,
                        ant_mt=ant_mt,
                        api_timeout=api_timeout,
                        outline=outline if user_outline_present else "",
                    )
                elif needs_word_count_trim(actual_wc, wc_for_content):
                    from app.services.content_ai_word_count_policy import word_count_bounds

                    _, max_ok = word_count_bounds(wc_for_content)
                    if _count_words_html(out) > max_ok:
                        before = out
                        out = _trim_html_to_max_words(out, max_ok)
                        if user_outline_present and outline:
                            out = _ensure_outline_coverage_after_trim(
                                out, outline=outline, before_html=before
                            )
            # Sau word-count: cổng cuối bắt buộc đủ outline.
            if user_outline_present and outline and cfg is not None:
                from app.services.content_ai_outline_engine import outline_h2_coverage

                cov2 = outline_h2_coverage(outline, out)
                if cov2.get("ratio", 0) < 1.0 or cov2.get("missing_sections"):
                    mark_step(STEP_REPAIR, outline_coverage=f"{cov2['covered']}/{cov2['total']}")
                    out = _continue_content_for_missing_outline(
                        html=out,
                        outline=outline,
                        wc_target=int(wc_for_content or 1000),
                        cfg=cfg,
                        system=system,
                        oai_mt=oai_mt,
                        ant_mt=ant_mt,
                        api_timeout=api_timeout,
                        source_blob=source_blob,
                        primary_keyword=pk,
                    )
                    out = extract_clean_html_fragment(str(out or "").strip()) or out
                    out = _strip_bracket_placeholders(out)
                    out = _sanitize_mixed_style_phrases(out)
            from app.services.content_blockquote_postprocess import postprocess_content_blockquotes

            out = postprocess_content_blockquotes(out)
    elif f == "outline_content":
        out = _strip_bracket_placeholders(out)
        if user_id and str(out or "").strip():
            from app.services.content_ai_outline_engine import (
                build_outline_diversity_instruction,
                classify_article_type,
                list_recent_outlines_for_user,
                outline_too_similar_to_recent,
                pick_outline_variant,
            )

            recent = list_recent_outlines_for_user(
                int(user_id),
                target_website=str(target_website or ""),
            )
            too_sim, sim_val, sim_note = outline_too_similar_to_recent(out, recent)
            if too_sim and cfg is not None:
                article_type = classify_article_type(pk, knowledge=knowledge)
                variant = pick_outline_variant(article_type, avoid_variant="A")
                regen_extra = build_outline_diversity_instruction(
                    article_type=article_type,
                    primary_keyword=pk,
                    brand=str((knowledge or {}).get("brand_name") or ""),
                    variant=variant,
                    similarity_note=sim_note,
                )
                regen_instructions = _build_instructions(
                    field=field,
                    target_word_count=target_word_count,
                    primary_keyword=pk,
                    llm_mode=llm_mode,
                    user_outline_present=False,
                    knowledge=knowledge,
                    outline_diversity_extra=regen_extra,
                )
                regen_user = f"{regen_instructions}\n\n=== SOURCE ===\n{source_blob}\n\n=== OUTPUT ==="
                logging.getLogger(__name__).info(
                    "content_ai_outline_regen similarity=%.2f variant=%s",
                    sim_val,
                    variant,
                )
                out = _llm_chat_for_cfg(
                    cfg=cfg,
                    system=system,
                    user=regen_user,
                    max_tokens_oai=oai_mt,
                    max_tokens_ant=ant_mt,
                    timeout_sec=api_timeout,
                )
                out = _strip_bracket_placeholders(str(out or "").strip())
    return out


def _cau_modal_llm_chat(
    *,
    system: str,
    user: str,
    user_id: int | None,
    use_system_llm: bool,
    timeout_sec: int = 120,
    word_target: int | None = None,
) -> str:
    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if not cfg:
        if use_system_llm:
            raise RuntimeError("Khóa LLM hệ thống chưa được cấu hình trên server.")
        raise RuntimeError("LLM not configured (missing API key).")
    oai_mt = _openai_max_tokens_for_field(field="content", word_target=word_target) or 4096
    ant_mt = _anthropic_max_tokens_for_field(field="content", word_target=word_target)
    if cfg.provider == "openai":
        return _openai_chat_completion(
            cfg=cfg,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=oai_mt,
            timeout_sec=timeout_sec,
        )
    return _anthropic_messages(cfg=cfg, system=system, user=user, max_tokens=ant_mt, timeout_sec=timeout_sec)


def generate_cau_modal_rewrite_html(
    *,
    title: str = "",
    meta_description: str = "",
    slug: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    content_html: str = "",
    target_website: str = "",
    user_id: int | None = None,
    use_system_llm: bool = False,
    target_word_count: int | None = None,
) -> str:
    """Viết lại toàn bộ HTML bài viết cho popup Sửa SEO."""
    from app.services.seo_content_prompt import build_content_html_instructions

    pk = _clean_ws(primary_keyword)
    if not pk:
        raise ValueError("Cần focus keyword để viết lại content.")
    t = str(title or "").strip()
    if not t:
        raise ValueError("Cần title để viết lại content.")

    wc = resolve_wc_for_content(target_word_count)
    outline = (outline_content or "").strip()
    existing = str(content_html or "")[:12_000]
    related_lines: list[str] = []
    if str(target_website or "").strip():
        for item in _fetch_related_posts_for_internal_links(str(target_website).strip(), pk, limit=8):
            rt = str(item.get("title") or "").strip()
            ru = str(item.get("url") or "").strip()
            if rt and ru:
                related_lines.append(f"- {rt} | {ru}")

    content_rules = build_content_html_instructions(
        primary_keyword=pk,
        target_word_count=wc,
        llm_mode="auto",
        user_outline_present=bool(outline),
        knowledge=None,
    )
    system = (
        "Bạn là chuyên gia viết bài SEO tiếng Việt. Viết lại TOÀN BỘ nội dung bài theo brief, "
        "giữ đúng chủ đề, không lan man, không bịa số liệu. Chỉ trả HTML thuần (h1–h3, p, ul/ol, table, "
        "figure+alt, FAQ, JSON-LD schema). Không markdown, không giải thích ngoài HTML."
    )
    user_parts = [
        "NHIỆM VỤ: Viết lại toàn bộ content HTML cho bài viết sau (không copy nguyên văn bản cũ).",
        content_rules,
        f"TITLE: {t}",
        f"FOCUS_KEYWORD: {pk}",
        f"SECONDARY_KEYWORDS: {_clean_ws(secondary_keywords)}",
        f"META_DESCRIPTION: {_clean_ws(meta_description)}",
        f"SLUG: {_clean_ws(slug)}",
    ]
    if outline:
        user_parts.append("OUTLINE:\n" + _truncate_text(outline, max_chars=4500))
    if existing:
        user_parts.append(
            "CURRENT_ARTICLE_HTML (chỉ tham khảo chủ đề & ngữ cảnh, viết lại mới hoàn toàn):\n"
            + existing
        )
    if related_lines:
        user_parts.append("RELATED_ARTICLES (ưu tiên chèn internal link tự nhiên):\n" + "\n".join(related_lines))
    user_parts.append("=== OUTPUT (HTML đầy đủ) ===")
    raw = _cau_modal_llm_chat(
        system=system,
        user="\n\n".join(user_parts),
        user_id=user_id,
        use_system_llm=use_system_llm,
        word_target=wc,
    )
    out = extract_clean_html_fragment(_sanitize_mixed_style_phrases(str(raw or "").strip()))
    if not out:
        raise ValueError("LLM không trả về nội dung HTML hợp lệ.")
    cfg = load_llm_config_admin() if use_system_llm else load_llm_config(user_id)
    if cfg:
        out = _enforce_content_word_count_with_llm(
            out,
            wc_for_content=wc,
            cfg=cfg,
            system=system,
            pk=pk,
            title=t,
            oai_mt=_openai_max_tokens_for_field(field="content", word_target=wc) or 4096,
            ant_mt=_anthropic_max_tokens_for_field(field="content", word_target=wc),
            api_timeout=120,
        )
    return out


def generate_cau_modal_append_sections_html(
    *,
    headings: list[str],
    title: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    content_html: str = "",
    existing_headings: list[str] | None = None,
    target_website: str = "",
    user_id: int | None = None,
    use_system_llm: bool = False,
) -> str:
    """Sinh HTML fragment cho các heading mới (H2/H3 + 2–4 đoạn) — chỉ thêm, không sửa cũ."""
    pk = _clean_ws(primary_keyword)
    clean_headings = [re.sub(r"\s+", " ", str(h or "").strip()) for h in headings if str(h or "").strip()]
    if not clean_headings:
        raise ValueError("Cần ít nhất 1 heading mới.")
    if not pk:
        raise ValueError("Cần focus keyword.")

    context = _truncate_text(_strip_tags_text(content_html), max_chars=3500)
    existing_lines = "\n".join(f"- {h}" for h in (existing_headings or [])[:40])
    related_lines: list[str] = []
    if str(target_website or "").strip():
        for item in _fetch_related_posts_for_internal_links(str(target_website).strip(), pk, limit=6):
            rt = str(item.get("title") or "").strip()
            ru = str(item.get("url") or "").strip()
            if rt and ru:
                related_lines.append(f"- {rt} | {ru}")

    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(clean_headings))
    system = (
        "Bạn viết nội dung SEO tiếng Việt. CHỈ trả HTML fragment các section MỚI — KHÔNG sửa/xóa/thay thế nội dung cũ. "
        "Mỗi section: 1 <h2> hoặc <h3> + 2–4 <p> (có thể <ul> ngắn). Không h1, không schema, không FAQ, không markdown."
    )
    user = (
        f"Bài viết: {str(title or '').strip()}\n"
        f"Từ khóa chính: {pk}\n"
        f"Từ khóa phụ: {_clean_ws(secondary_keywords)}\n"
        f"Meta: {_clean_ws(meta_description)}\n"
        f"Outline: {_truncate_text(outline_content or '', max_chars=2000)}\n\n"
        f"Heading ĐÃ CÓ trong bài (KHÔNG được trùng, KHÔNG viết lại ý đã có):\n"
        f"{existing_lines or '(chưa có heading trong HTML)'}\n\n"
        f"Ngữ cảnh nội dung hiện có (CHỈ đọc, KHÔNG sửa):\n{context or '(trống)'}\n\n"
        f"Viết section MỚI cho các heading sau:\n{numbered}\n\n"
        "Yêu cầu: bổ sung ý còn thiếu, đúng ngữ cảnh bài, keyword tự nhiên, không lan man."
    )
    if related_lines:
        user += "\n\nInternal link gợi ý:\n" + "\n".join(related_lines)
    user += "\n\n=== OUTPUT (chỉ HTML section mới) ==="
    raw = _cau_modal_llm_chat(
        system=system,
        user=user,
        user_id=user_id,
        use_system_llm=use_system_llm,
        timeout_sec=90,
        word_target=600,
    )
    out = extract_clean_html_fragment(_sanitize_mixed_style_phrases(str(raw or "").strip()))
    if not out:
        raise ValueError("LLM không trả về section HTML hợp lệ.")
    return out


def generate_cau_modal_auto_append_sections_html(
    *,
    title: str = "",
    meta_description: str = "",
    primary_keyword: str = "",
    secondary_keywords: str = "",
    outline_content: str = "",
    content_html: str = "",
    existing_headings: list[str] | None = None,
    target_website: str = "",
    user_id: int | None = None,
    use_system_llm: bool = False,
) -> str:
    """Phân tích bài + tự đề xuất 1–3 heading H2/H3 mới và viết nội dung (HTML fragment)."""
    pk = _clean_ws(primary_keyword)
    if not pk:
        raise ValueError("Cần focus keyword.")
    if not str(content_html or "").strip():
        raise ValueError("Cần nội dung bài viết để AI phân tích.")

    context = _truncate_text(_strip_tags_text(content_html), max_chars=4500)
    existing_lines = "\n".join(f"- {h}" for h in (existing_headings or [])[:40])
    related_lines: list[str] = []
    if str(target_website or "").strip():
        for item in _fetch_related_posts_for_internal_links(str(target_website).strip(), pk, limit=6):
            rt = str(item.get("title") or "").strip()
            ru = str(item.get("url") or "").strip()
            if rt and ru:
                related_lines.append(f"- {rt} | {ru}")

    system = (
        "Bạn là biên tập viên SEO tiếng Việt. Phân tích bài viết và TỰ ĐỀ XUẤT 1–3 heading H2/H3 MỚI "
        "bổ sung ý còn thiếu (không trùng, không viết lại ý đã có). "
        "CHỈ trả HTML fragment section mới: mỗi section = 1 <h2> hoặc <h3> + 2–4 <p>. "
        "Không h1, không schema, không FAQ, không markdown, không sửa nội dung cũ."
    )
    user = (
        f"Bài viết: {str(title or '').strip()}\n"
        f"Từ khóa chính: {pk}\n"
        f"Từ khóa phụ: {_clean_ws(secondary_keywords)}\n"
        f"Meta: {_clean_ws(meta_description)}\n"
        f"Outline: {_truncate_text(outline_content or '', max_chars=2000)}\n\n"
        f"Heading ĐÃ CÓ (KHÔNG trùng, KHÔNG lặp ý):\n{existing_lines or '(chưa có)'}\n\n"
        f"Nội dung hiện tại (CHỈ đọc):\n{context}\n\n"
        "Nhiệm vụ:\n"
        "1) Tìm khoảng trống kiến thức / chủ đề phụ còn thiếu so với tiêu đề & từ khóa.\n"
        "2) Tạo 1–3 heading H2/H3 mới phù hợp.\n"
        "3) Viết 2–4 đoạn cho mỗi heading — bổ sung giá trị, không paraphrase section cũ.\n"
    )
    if related_lines:
        user += "\nInternal link gợi ý:\n" + "\n".join(related_lines)
    user += "\n\n=== OUTPUT (chỉ HTML section mới) ==="
    raw = _cau_modal_llm_chat(
        system=system,
        user=user,
        user_id=user_id,
        use_system_llm=use_system_llm,
        timeout_sec=100,
        word_target=900,
    )
    out = extract_clean_html_fragment(_sanitize_mixed_style_phrases(str(raw or "").strip()))
    if not out:
        raise ValueError("LLM không trả về section HTML hợp lệ.")
    return out


def _strip_tags_text(html: str) -> str:
    try:
        return re.sub(r"\s+", " ", BeautifulSoup(str(html or ""), "html.parser").get_text(" ", strip=True))
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")

