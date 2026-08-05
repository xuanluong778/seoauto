"""AI fix đơn trường cho SEO Score — chỉ sửa đúng page_field được chọn."""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Any

TITLE_LEN = (50, 60)
META_LEN = (140, 160)

ALLOWED_PAGE_FIELDS = frozenset({
    "title",
    "meta_description",
    "heading",
    "image_alt",
    "intro",
    "content_section",
})

PAGE_FIELD_ALIASES = {
    "headings": "heading",
    "images": "image_alt",
}

_SYSTEM = (
    "Bạn là chuyên gia SEO on-page. CHỈ sửa đúng một trường được yêu cầu. "
    "Không sửa các trường khác. Không bịa số liệu, thống kê, giá, tên thương hiệu "
    "hay thông tin không có trong ngữ cảnh. Giữ nguyên ý nghĩa nội dung hiện có."
)


class SeoScoreAiFixError(RuntimeError):
    def __init__(self, message: str, *, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.warnings = list(warnings or [])


def normalize_page_field(page_field: str) -> str:
    pf = str(page_field or "").strip().lower()
    return PAGE_FIELD_ALIASES.get(pf, pf)


def seo_score_ai_fix_billing_enabled() -> bool:
    """Product policy: off by default → NOT_BILLABLE until flag explicitly enabled."""
    return os.getenv("SEO_SCORE_AI_FIX_BILLING_ENABLED", "").strip().lower() in ("1", "true", "yes")


def seo_score_ai_fix_billing_status() -> str:
    """BILLABLE when SEO_SCORE_AI_FIX_BILLING_ENABLED=1, else NOT_BILLABLE (no credit debit)."""
    return "BILLABLE" if seo_score_ai_fix_billing_enabled() else "NOT_BILLABLE"


def _clip(text: str, max_len: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rsplit(" ", 1)[0]
    return (cut or t[:max_len]).strip()


def _keyword_in_text(keyword: str, text: str) -> bool:
    kw = str(keyword or "").strip().lower()
    if not kw:
        return True
    return kw in str(text or "").lower()


def _alt_from_src(src: str, keyword: str) -> str:
    name = PurePosixPath(str(src or "").split("?")[0]).stem
    name = re.sub(r"[-_]+", " ", name).strip()
    if name and len(name) >= 3:
        base = name[:1].upper() + name[1:]
    elif keyword:
        base = str(keyword).strip()
    else:
        base = "Hình minh họa"
    if keyword and not _keyword_in_text(keyword, base):
        return _clip(f"{base} — {keyword}", 125)
    return _clip(base, 125)


def _normalize_before(page_field: str, current_value: Any, evidence: dict[str, Any]) -> Any:
    ev = evidence or {}
    if page_field == "heading":
        if isinstance(current_value, dict) and any(current_value.get(tag) for tag in ("h1", "h2", "h3")):
            return current_value
        return {
            "h1": list(ev.get("h1") or []),
            "h2": list(ev.get("h2") or []),
            "h3": list(ev.get("h3") or []),
        }
    if page_field == "image_alt":
        if isinstance(current_value, list) and current_value:
            return current_value
        missing = list(ev.get("missing_alt") or ev.get("target_images") or [])
        if missing:
            return missing
        return list(ev.get("samples") or [])
    if page_field == "intro":
        if isinstance(current_value, str) and current_value.strip():
            return current_value.strip()
        text = str(ev.get("text") or ev.get("intro_text") or "").strip()
        return text or str(current_value or "").strip()
    if page_field == "content_section":
        if isinstance(current_value, list) and current_value:
            return current_value
        return list(ev.get("sections") or [])
    if current_value is not None:
        return current_value
    return current_value


def validate_seo_score_ai_fix_input(
    *,
    page_field: str,
    current_value: Any = None,
    evidence: dict[str, Any] | None = None,
    keyword: str = "",
) -> None:
    """Raise SeoScoreAiFixError khi thiếu input — không gọi AI, không trừ credit."""
    pf = normalize_page_field(page_field)
    if pf not in ALLOWED_PAGE_FIELDS:
        raise SeoScoreAiFixError(f"Trường '{page_field}' không được phép sửa bằng AI.")
    before = _normalize_before(pf, current_value, dict(evidence or {}))
    kw = str(keyword or "").strip()

    if pf in ("title", "meta_description", "intro"):
        text = str(before or "").strip()
        if not text and not kw:
            raise SeoScoreAiFixError("Thiếu dữ liệu hiện tại và keyword để đề xuất sửa.")
        return

    if pf == "heading":
        data = before if isinstance(before, dict) else {}
        if not any(data.get(tag) for tag in ("h1", "h2", "h3")) and not kw:
            raise SeoScoreAiFixError("Thiếu heading hoặc keyword để đề xuất sửa.")
        return

    if pf == "image_alt":
        rows = before if isinstance(before, list) else []
        if not rows:
            raise SeoScoreAiFixError("Không có ảnh thiếu alt trong dữ liệu.")
        return

    if pf == "content_section":
        sections = before if isinstance(before, list) else []
        if not sections:
            raise SeoScoreAiFixError("Không có section nội dung để sửa.")
        return


def _rule_fix_title(*, before: str, keyword: str, issue_id: str) -> tuple[str, str, list[str]]:
    title = str(before or "").strip()
    kw = str(keyword or "").strip()
    warnings: list[str] = []
    if not title and not kw:
        raise SeoScoreAiFixError("Không có title hoặc keyword để đề xuất.")
    if not title:
        after = _clip(kw, TITLE_LEN[1])
        return after, "Tạo title từ keyword chính (rule-based, chưa có LLM).", warnings
    after = title
    if kw and not _keyword_in_text(kw, after):
        after = _clip(f"{kw} | {after}", TITLE_LEN[1])
    if len(after) < TITLE_LEN[0]:
        warnings.append(f"Title ngắn hơn khuyến nghị {TITLE_LEN[0]}–{TITLE_LEN[1]} ký tự.")
    if len(after) > TITLE_LEN[1]:
        after = _clip(after, TITLE_LEN[1])
        warnings.append(f"Title đã rút gọn về tối đa {TITLE_LEN[1]} ký tự.")
    reason = "Chèn keyword vào title nếu thiếu; giữ nguyên ý nghĩa (rule-based)."
    if issue_id == "title_missing":
        reason = "Bổ sung title có keyword (rule-based)."
    return after, reason, warnings


def _rule_fix_meta(*, before: str, keyword: str, title: str) -> tuple[str, str, list[str]]:
    meta = str(before or "").strip()
    kw = str(keyword or "").strip()
    base_title = str(title or "").strip()
    warnings: list[str] = []
    if meta:
        after = meta
        if kw and not _keyword_in_text(kw, after):
            after = _clip(f"{after} — {kw}", META_LEN[1])
    elif base_title:
        after = _clip(base_title, META_LEN[1])
    elif kw:
        after = _clip(f"Tìm hiểu {kw} — thông tin hữu ích và hướng dẫn chi tiết.", META_LEN[1])
    else:
        raise SeoScoreAiFixError("Không có meta, title hoặc keyword để đề xuất.")
    if len(after) < META_LEN[0]:
        warnings.append(f"Meta ngắn hơn khuyến nghị {META_LEN[0]}–{META_LEN[1]} ký tự.")
    if len(after) > META_LEN[1]:
        after = _clip(after, META_LEN[1])
    return after, "Tối ưu meta từ nội dung hiện có, không thêm số liệu (rule-based).", warnings


def _rule_fix_heading(*, before: Any, keyword: str) -> tuple[dict[str, list[str]], str, list[str]]:
    data = before if isinstance(before, dict) else {}
    h1 = [str(x).strip() for x in (data.get("h1") or []) if str(x).strip()]
    h2 = [str(x).strip() for x in (data.get("h2") or []) if str(x).strip()]
    h3 = [str(x).strip() for x in (data.get("h3") or []) if str(x).strip()]
    kw = str(keyword or "").strip()
    warnings: list[str] = []
    if not h1:
        if not kw:
            raise SeoScoreAiFixError("Không có H1 hoặc keyword để đề xuất heading.")
        h1 = [_clip(kw, 80)]
        reason = "Thêm H1 từ keyword (rule-based)."
    elif len(h1) > 1:
        h1 = [h1[0]]
        warnings.append("Chỉ giữ một H1 — đã bỏ các H1 trùng.")
        reason = "Gộp về một H1 duy nhất (rule-based)."
    else:
        reason = "Giữ cấu trúc heading hiện tại; có thể tinh chỉnh H2 nếu cần (rule-based)."
        if kw and not _keyword_in_text(kw, h1[0]):
            h1 = [_clip(f"{kw}: {h1[0]}", 100)]
    return {"h1": h1, "h2": h2[:12], "h3": h3[:12]}, reason, warnings


def _rule_fix_image_alt(*, before: Any, evidence: dict[str, Any], keyword: str) -> tuple[list[dict[str, str]], str, list[str]]:
    rows: list[dict[str, Any]] = []
    if isinstance(before, list):
        rows = [r for r in before if isinstance(r, dict)]
    if not rows:
        rows = list((evidence or {}).get("missing_alt") or [])
    if not rows:
        rows = [r for r in ((evidence or {}).get("samples") or []) if isinstance(r, dict) and r.get("missing_alt")]
    if not rows:
        raise SeoScoreAiFixError("Không có ảnh thiếu alt trong dữ liệu.")
    out: list[dict[str, str]] = []
    for row in rows[:20]:
        src = str(row.get("src") or row.get("url") or "").strip()
        old_alt = str(row.get("alt") or "").strip()
        if old_alt and not row.get("missing_alt"):
            continue
        out.append({"src": src, "alt": _alt_from_src(src, keyword)})
    if not out:
        raise SeoScoreAiFixError("Tất cả ảnh đã có alt — không cần sửa.")
    return out, f"Đề xuất alt cho {len(out)} ảnh thiếu alt (rule-based).", []


def _rule_fix_intro(*, before: str, keyword: str, issue_id: str) -> tuple[str, str, list[str]]:
    intro = str(before or "").strip()
    kw = str(keyword or "").strip()
    warnings: list[str] = []
    if not intro and not kw:
        raise SeoScoreAiFixError("Không có đoạn mở bài hoặc keyword để đề xuất.")
    if not intro:
        after = _clip(f"{kw} — tổng quan ngắn gọn về chủ đề trang.", 600)
        return after, "Tạo intro từ keyword (rule-based).", warnings
    after = intro
    if kw and not _keyword_in_text(kw, after):
        after = _clip(f"{kw}. {after}", 600)
    if len(after) < 120:
        warnings.append("Intro ngắn — nên mở rộng thêm 2–4 câu.")
    reason = "Bổ sung keyword vào intro nếu thiếu (rule-based)."
    if issue_id == "primary_in_body":
        reason = "Đưa keyword chính vào đoạn mở bài (rule-based)."
    return after, reason, warnings


def _rule_fix_content_section(*, before: Any, keyword: str, evidence: dict[str, Any]) -> tuple[Any, str, list[str]]:
    sections = before if isinstance(before, list) else list((evidence or {}).get("sections") or [])
    if not sections:
        raise SeoScoreAiFixError("Không có section nội dung để sửa.")
    kw = str(keyword or "").strip()
    out: list[dict[str, Any]] = []
    for sec in sections[:6]:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "").strip()
        text = str(sec.get("text") or "").strip()
        if kw and text and not _keyword_in_text(kw, text) and not _keyword_in_text(kw, heading):
            text = _clip(f"{text} Liên quan {kw}.", 1200)
        out.append({**sec, "text": text or sec.get("text", ""), "heading": heading or sec.get("heading", "")})
    if not out:
        raise SeoScoreAiFixError("Không parse được section nội dung.")
    return out, f"Tinh chỉnh {len(out)} section — không thêm số liệu (rule-based).", []


def _rule_fallback(
    *,
    page_field: str,
    before: Any,
    keyword: str,
    issue_id: str,
    evidence: dict[str, Any],
) -> tuple[Any, str, float, list[str]]:
    if page_field == "title":
        after, reason, warnings = _rule_fix_title(before=str(before or ""), keyword=keyword, issue_id=issue_id)
    elif page_field == "meta_description":
        title_hint = str((evidence or {}).get("text") or (evidence or {}).get("title") or "")
        after, reason, warnings = _rule_fix_meta(before=str(before or ""), keyword=keyword, title=title_hint)
    elif page_field == "heading":
        after, reason, warnings = _rule_fix_heading(before=before, keyword=keyword)
    elif page_field == "image_alt":
        after, reason, warnings = _rule_fix_image_alt(before=before, evidence=evidence, keyword=keyword)
    elif page_field == "intro":
        after, reason, warnings = _rule_fix_intro(before=str(before or ""), keyword=keyword, issue_id=issue_id)
    elif page_field == "content_section":
        after, reason, warnings = _rule_fix_content_section(before=before, keyword=keyword, evidence=evidence)
    else:
        raise SeoScoreAiFixError(f"Trường '{page_field}' chưa hỗ trợ sửa bằng AI.")
    return after, reason, 0.55, warnings


def _field_prompt(
    *,
    page_field: str,
    url: str,
    keyword: str,
    group_key: str,
    issue_id: str,
    before: Any,
    evidence: dict[str, Any],
) -> str:
    ctx = (
        f"URL: {url}\n"
        f"KEYWORD: {keyword or '(không có)'}\n"
        f"GROUP: {group_key or '—'}\n"
        f"ISSUE_ID: {issue_id or '—'}\n"
        f"PAGE_FIELD: {page_field}\n"
        f"CURRENT_VALUE:\n{before}\n"
        f"EVIDENCE:\n{evidence}\n"
    )
    if page_field == "title":
        return (
            ctx
            + f"\nCHỈ sửa TITLE. Độ dài mục tiêu {TITLE_LEN[0]}–{TITLE_LEN[1]} ký tự. "
            "Trả JSON: {\"after\":\"...\",\"reason\":\"...\",\"confidence\":0.0-1.0,\"warnings\":[]}"
        )
    if page_field == "meta_description":
        return (
            ctx
            + f"\nCHỈ sửa META DESCRIPTION. Độ dài mục tiêu {META_LEN[0]}–{META_LEN[1]} ký tự. "
            "Trả JSON: {\"after\":\"...\",\"reason\":\"...\",\"confidence\":0.0-1.0,\"warnings\":[]}"
        )
    if page_field == "heading":
        return (
            ctx
            + "\nCHỈ sửa HEADING (h1/h2/h3). Một H1 duy nhất; H2/H3 phân cấp hợp lý. "
            'Trả JSON: {"after":{"h1":["..."],"h2":["..."],"h3":["..."]},'
            '"reason":"...","confidence":0.0-1.0,"warnings":[]}'
        )
    if page_field == "image_alt":
        return (
            ctx
            + "\nCHỈ sửa ALT cho ảnh thiếu alt trong evidence. Không đổi src. "
            'Trả JSON: {"after":[{"src":"...","alt":"..."}],'
            '"reason":"...","confidence":0.0-1.0,"warnings":[]}'
        )
    if page_field == "intro":
        return (
            ctx
            + "\nCHỈ sửa ĐOẠN MỞ BÀI (intro). 2–4 câu, có keyword nếu phù hợp. "
            "Không bịa số liệu, giá, cam kết, địa chỉ. "
            'Trả JSON: {"after":"...","reason":"...","confidence":0.0-1.0,"warnings":[]}'
        )
    if page_field == "content_section":
        return (
            ctx
            + "\nCHỈ sửa NỘI DUNG SECTION (mảng sections). Giữ heading; cải thiện text từng section. "
            "Không bịa số liệu, giá, cam kết. "
            'Trả JSON: {"after":[{"heading":"...","level":"h2","text":"..."}],'
            '"reason":"...","confidence":0.0-1.0,"warnings":[]}'
        )
    raise SeoScoreAiFixError(f"Trường '{page_field}' chưa hỗ trợ sửa bằng AI.")


def _validate_llm_result(page_field: str, obj: dict[str, Any]) -> tuple[Any, str, float, list[str]]:
    reason = str(obj.get("reason") or "").strip() or "AI đã đề xuất bản sửa."
    try:
        confidence = float(obj.get("confidence", 0.75))
    except (TypeError, ValueError):
        confidence = 0.75
    confidence = max(0.0, min(1.0, confidence))
    warnings = [str(x).strip() for x in (obj.get("warnings") or []) if str(x).strip()][:10]
    after = obj.get("after")
    if page_field in ("title", "meta_description"):
        if not isinstance(after, str) or not after.strip():
            raise SeoScoreAiFixError("AI không trả về giá trị hợp lệ cho trường văn bản.")
        return after.strip(), reason, confidence, warnings
    if page_field == "heading":
        if not isinstance(after, dict):
            raise SeoScoreAiFixError("AI không trả về heading hợp lệ.")
        return {
            "h1": [str(x).strip() for x in (after.get("h1") or []) if str(x).strip()][:3],
            "h2": [str(x).strip() for x in (after.get("h2") or []) if str(x).strip()][:15],
            "h3": [str(x).strip() for x in (after.get("h3") or []) if str(x).strip()][:15],
        }, reason, confidence, warnings
    if page_field == "image_alt":
        if not isinstance(after, list) or not after:
            raise SeoScoreAiFixError("AI không trả về danh sách alt hợp lệ.")
        rows: list[dict[str, str]] = []
        for item in after[:20]:
            if not isinstance(item, dict):
                continue
            src = str(item.get("src") or "").strip()
            alt = str(item.get("alt") or "").strip()
            if src and alt:
                rows.append({"src": src, "alt": alt})
        if not rows:
            raise SeoScoreAiFixError("AI không trả về alt hợp lệ.")
        return rows, reason, confidence, warnings
    if page_field == "intro":
        if not isinstance(after, str) or not after.strip():
            raise SeoScoreAiFixError("AI không trả về intro hợp lệ.")
        return after.strip(), reason, confidence, warnings
    if page_field == "content_section":
        if isinstance(after, str) and after.strip():
            return after.strip(), reason, confidence, warnings
        if not isinstance(after, list) or not after:
            raise SeoScoreAiFixError("AI không trả về section hợp lệ.")
        rows: list[dict[str, Any]] = []
        for item in after[:12]:
            if not isinstance(item, dict):
                continue
            heading = str(item.get("heading") or "").strip()
            text = str(item.get("text") or "").strip()
            if heading or text:
                rows.append(
                    {
                        "heading": heading,
                        "level": str(item.get("level") or "h2"),
                        "text": text,
                        "word_count": len(text.split()) if text else 0,
                    }
                )
        if not rows:
            raise SeoScoreAiFixError("AI không trả về section hợp lệ.")
        return rows, reason, confidence, warnings
    raise SeoScoreAiFixError(f"Trường '{page_field}' chưa hỗ trợ.")


def run_seo_score_ai_fix(
    *,
    user_id: int,
    url: str,
    keyword: str = "",
    group_key: str = "",
    issue_id: str = "",
    page_field: str,
    current_value: Any = None,
    evidence: dict[str, Any] | None = None,
    force_rule_fallback: bool = False,
) -> dict[str, Any]:
    """Trả dict before/after/reason/confidence/warnings — raise SeoScoreAiFixError khi thất bại."""
    pf = normalize_page_field(page_field)
    if pf not in ALLOWED_PAGE_FIELDS:
        raise SeoScoreAiFixError(f"Trường '{page_field}' không được phép sửa bằng AI.")
    ev = dict(evidence or {})
    validate_seo_score_ai_fix_input(
        page_field=pf,
        current_value=current_value,
        evidence=ev,
        keyword=keyword,
    )
    before = _normalize_before(pf, current_value, ev)

    if force_rule_fallback:
        after, reason, confidence, warnings = _rule_fallback(
            page_field=pf,
            before=before,
            keyword=keyword,
            issue_id=issue_id,
            evidence=ev,
        )
        return {
            "before": before,
            "after": after,
            "reason": reason,
            "confidence": confidence,
            "warnings": warnings,
            "source": "rule",
        }

    from app.services.llm_content_writer import (
        _try_parse_json_object,
        load_llm_config,
        run_seo_score_ai_fix_completion,
    )

    cfg = load_llm_config(user_id)
    if not cfg:
        after, reason, confidence, warnings = _rule_fallback(
            page_field=pf,
            before=before,
            keyword=keyword,
            issue_id=issue_id,
            evidence=ev,
        )
        return {
            "before": before,
            "after": after,
            "reason": reason,
            "confidence": confidence,
            "warnings": warnings + ["LLM chưa cấu hình — dùng rule-based."],
            "source": "rule",
        }

    user_prompt = _field_prompt(
        page_field=pf,
        url=url,
        keyword=keyword,
        group_key=group_key,
        issue_id=issue_id,
        before=before,
        evidence=ev,
    )
    try:
        raw = run_seo_score_ai_fix_completion(
            cfg=cfg,
            system=_SYSTEM,
            user_prompt=user_prompt,
            max_tokens=1200,
            timeout_sec=60,
        )
        obj = _try_parse_json_object(raw)
        if not obj:
            raise SeoScoreAiFixError("AI trả về JSON không hợp lệ.")
        after, reason, confidence, warnings = _validate_llm_result(pf, obj)
        return {
            "before": before,
            "after": after,
            "reason": reason,
            "confidence": confidence,
            "warnings": warnings,
            "source": "llm",
        }
    except SeoScoreAiFixError:
        raise
    except Exception as exc:
        after, reason, confidence, warnings = _rule_fallback(
            page_field=pf,
            before=before,
            keyword=keyword,
            issue_id=issue_id,
            evidence=ev,
        )
        return {
            "before": before,
            "after": after,
            "reason": reason,
            "confidence": confidence,
            "warnings": warnings + [f"LLM không khả dụng — dùng rule-based ({type(exc).__name__})."],
            "source": "rule",
        }


def finalize_seo_score_ai_fix_credit(db, user, *, success: bool, url: str, issue_id: str) -> dict[str, Any]:
    """Hook credit: BILLABLE only when flag on; otherwise NOT_BILLABLE (zero charge)."""
    from app.services.credits import consume_credits, cost_seo_score_ai_fix, credits_enforced

    status = seo_score_ai_fix_billing_status()
    if not success:
        return {
            "charged": 0,
            "billing_enabled": status == "BILLABLE",
            "billing_status": status,
            "skipped": "ai_error",
        }
    if status == "NOT_BILLABLE":
        return {
            "charged": 0,
            "billing_enabled": False,
            "billing_status": "NOT_BILLABLE",
            "policy": "SEO_SCORE_AI_FIX_BILLING_ENABLED unset/false — no credit debit",
        }
    cost = cost_seo_score_ai_fix(db=db)
    if cost > 0 and credits_enforced():
        import hashlib
        idem = hashlib.sha256(f"seo_score_ai_fix:{user.id}:{issue_id}:{url}".encode()).hexdigest()[:48]
        # reserve-first deferred to router when BILLABLE; finalize still supports post-success commit path
        consume_credits(
            db,
            user_id=user.id,
            amount=cost,
            reason="seo_score_ai_fix",
            module="seo_score",
            action="ai_fix",
            note=f"{issue_id}:{url}"[:500],
            feature_code="seo_score",
            job_id=idem,
            idempotency_key=f"seo_score_ai_fix:{idem}"[:128],
        )
        return {"charged": cost, "billing_enabled": True, "billing_status": "BILLABLE"}
    return {"charged": 0, "billing_enabled": True, "billing_status": "BILLABLE"}
