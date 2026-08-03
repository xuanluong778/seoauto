"""Background bulk article writer — one keyword at a time, persisted via job_store."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from app.services.content_ai_bulk_parse import normalize_bulk_job_items
from app.services.content_ai_project_store import save_or_update_written_bulk_project
from app.services.content_draft_builder import build_draft_payload, suggest_content_ai_field
from app.services.job_store import fail_job, finish_job, get_job, update_job

_LOG = logging.getLogger(__name__)
_FALLBACK_STUB_PHRASE = "Nội dung chi tiết được triển khai theo dàn ý bài viết."


def _fallback_content_html(*, primary_keyword: str, title: str, outline_content: str) -> str:
    """Minimal HTML fallback when LLM returns empty (avoids importing pages router)."""
    kw = (primary_keyword or "").strip()
    t = (title or "").strip() or kw or "Nội dung dịch vụ"
    outline = (outline_content or "").strip()
    h2_items: list[str] = []
    if outline:
        for ln in outline.splitlines():
            s = re.sub(r"^\s*#+\s*", "", str(ln or "").strip())
            if len(s) >= 4:
                h2_items.append(s)
            if len(h2_items) >= 6:
                break
    if not h2_items:
        h2_items = [f"Giới thiệu {kw or 'dịch vụ'}", "Quy trình và chi phí", "Liên hệ đặt lịch"]
    parts = [f"<h1>{t}</h1>", f"<p><strong>Bạn đang tìm {kw or 'dịch vụ'} — nội dung tổng hợp dưới đây.</strong></p>"]
    for h2 in h2_items:
        parts.append(f"<h2>{h2}</h2>")
        parts.append("<p>Nội dung chi tiết được triển khai theo dàn ý bài viết.</p>")
    parts.append("<h2>Liên hệ</h2><p>Gọi hotline hoặc nhắn Zalo để được tư vấn nhanh.</p>")
    return "\n".join(parts)


def _is_stub_content_html(html: str) -> bool:
    return _FALLBACK_STUB_PHRASE in str(html or "")


# Điểm tối thiểu để coi là đạt trong bulk (sau checklist + tối ưu tối đa 1 lần).
_BULK_SEO_PASS_SCORE = 75


def _seo_issues_from_checklist(result: dict[str, Any]) -> list[str]:
    """Gộp issue từ các yếu tố failed/warning của evaluate_publish_checklist."""
    issues: list[str] = []
    for f in result.get("factors") or []:
        if not isinstance(f, dict):
            continue
        st = str(f.get("status") or "").strip().lower()
        if st not in {"failed", "warning"}:
            continue
        label = str(f.get("label") or f.get("id") or "").strip()
        msg = str(f.get("message") or f.get("fix") or "").strip()
        line = f"{label}: {msg}".strip(": ").strip()
        if line and line not in issues:
            issues.append(line)
        if len(issues) >= 30:
            break
    return issues


def _seo_status_for_bulk(*, score: int, failed_n: int) -> str:
    if int(score) >= _BULK_SEO_PASS_SCORE and int(failed_n) <= 0:
        return "pass"
    return "needs_review"


def _strip_script_tags_bulk(html: str) -> str:
    """Loại <script> (JSON-LD autofix) khỏi HTML bài bulk — giữ nội dung sạch."""
    return re.sub(
        r"<script\b[^>]*>[\s\S]*?</script>",
        "",
        str(html or ""),
        flags=re.I,
    )


def run_bulk_article_seo_checklist(
    *,
    user_id: int,
    title: str,
    meta_description: str,
    content_html: str,
    primary_keyword: str,
    slug: str = "",
    secondary_keywords: list[str] | None = None,
    target_website: str = "",
    db=None,
    user=None,
    use_system_llm: bool = True,
    skip_llm_credit_check: bool = False,
    lock_title: bool = False,
    lock_meta: bool = False,
) -> dict[str, Any]:
    """
    Chạy SEO checklist sau khi viết + sửa số từ (chỉ luồng bulk).
    Nếu điểm thấp → gọi LLM tối ưu tối đa 1 lần, rồi chấm lại.
    lock_title/lock_meta: tôn trọng title/meta user nhập tay (không ghi đè).
    """
    from app.services.content_ai_publish_checklist import evaluate_publish_checklist
    from app.services.content_ai_seo_autofix import run_seo_autofix_preview

    title_s = str(title or "").strip()
    meta_s = str(meta_description or "").strip()
    content_s = _strip_script_tags_bulk(str(content_html or "").strip())
    slug_s = str(slug or "").strip()
    pk = str(primary_keyword or "").strip()
    secs = list(secondary_keywords or [])
    locked_title = title_s if lock_title and title_s else ""
    locked_meta = meta_s if lock_meta and meta_s else ""

    before = evaluate_publish_checklist(
        title=title_s,
        meta_description=meta_s,
        content_html=content_s,
        primary_keyword=pk,
        slug=slug_s,
        secondary_keywords=secs,
    )
    score = int(before.get("score") or 0)
    optimized = False
    final = before

    if score < _BULK_SEO_PASS_SCORE and content_s:
        try:
            autofix = run_seo_autofix_preview(
                user_id=int(user_id),
                db=db,
                user=user,
                title=title_s,
                meta_description=meta_s,
                content_html=content_s,
                primary_keyword=pk,
                slug=slug_s,
                secondary_keywords=secs,
                target_website=str(target_website or ""),
                mode="optimize_90",
                use_system_llm=bool(use_system_llm),
                skip_llm_credit_check=bool(skip_llm_credit_check),
            )
        except Exception as exc:
            _LOG.warning("bulk SEO autofix failed for %s: %s", pk, exc)
            autofix = {"success": False}

        if autofix.get("success") and isinstance(autofix.get("patch"), dict):
            patch = autofix["patch"]
            new_title = locked_title or (str(patch.get("title") or title_s).strip() or title_s)
            new_meta = locked_meta or (str(patch.get("meta_description") or meta_s).strip() or meta_s)
            new_slug = str(patch.get("slug") or slug_s).strip() or slug_s
            new_content = _strip_script_tags_bulk(
                str(patch.get("content_html") or content_s).strip() or content_s
            )
            after = evaluate_publish_checklist(
                title=new_title,
                meta_description=new_meta,
                content_html=new_content,
                primary_keyword=pk,
                slug=new_slug,
                secondary_keywords=secs,
            )
            after_score = int(after.get("score") or 0)
            # Chỉ nhận bản tối ưu nếu điểm không thấp hơn (tránh hồi quy).
            if after_score >= score:
                title_s, meta_s, slug_s, content_s = new_title, new_meta, new_slug, new_content
                score = after_score
                final = after
                optimized = True

    if locked_title:
        title_s = locked_title
    if locked_meta:
        meta_s = locked_meta
    content_s = _strip_script_tags_bulk(content_s)

    issues = _seo_issues_from_checklist(final)
    summary = final.get("summary") if isinstance(final.get("summary"), dict) else {}
    failed_n = int(summary.get("fail") or 0)
    status = _seo_status_for_bulk(score=score, failed_n=failed_n)

    return {
        "title": title_s,
        "meta_description": meta_s,
        "slug": slug_s,
        "content": content_s,
        "seo_score": score,
        "seo_issues": issues,
        "seo_status": status,
        "seo_issue_count": len(issues),
        "seo_optimized": optimized,
        "seo_grade_label": str(final.get("grade_label") or ""),
    }


def _load_llm_cfg(*, use_system_llm: bool = False):
    try:
        from app.services.llm_content_writer import load_llm_config, load_llm_config_admin

        if use_system_llm:
            return load_llm_config_admin()
        return load_llm_config()
    except Exception:
        return None


def _open_system_llm_db_user(user_id: int):
    """Open DB session + user for cost-gated system LLM (chatbot / background jobs)."""
    from app.db import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    user = db.get(User, int(user_id))
    if not user:
        db.close()
        raise ValueError(f"User {user_id} không tồn tại.")
    return db, user


def _auto_target_word_count_for_row(
    *,
    row: dict[str, Any],
    fallback_word_count: int,
    bulk_user,
    gate_db,
) -> int:
    from app.services.content_ai_word_count_policy import validate_target_word_count
    from app.services.content_draft_builder import detect_search_intent

    kw = str(row.get("keyword") or "").strip()
    ctype = str(row.get("content_type") or "").strip().lower()
    intent = detect_search_intent(kw)
    try:
        sv = int(row.get("search_volume") or 0)
    except (TypeError, ValueError):
        sv = 0

    if "landing" in ctype or "conversion" in ctype or intent in {"transactional", "ecommerce"}:
        base = 1000
    elif "comparison" in ctype or intent == "commercial":
        base = 1500
    elif "guide" in ctype or "pillar" in ctype:
        base = 2000
    else:
        base = 1500

    if sv >= 10000:
        base += 300
    elif sv >= 3000:
        base += 150

    if fallback_word_count >= 200 and abs(fallback_word_count - 1000) > 50:
        base = max(base, int(fallback_word_count))
    return validate_target_word_count(base, bulk_user, gate_db)


def _llm_gate_kwargs(
    *,
    db,
    user,
    field: str,
    skip_llm_credit_check: bool,
    action: str = "bulk_suggest",
):
    from app.services.cost_control.module_gates import content_ai_llm_gate
    from app.services.llm_content_writer import load_llm_config_admin

    llm_cfg_admin = load_llm_config_admin()
    return content_ai_llm_gate(
        db,
        user,
        action=action,
        field=field,
        use_system_llm=True,
        llm_cfg=llm_cfg_admin,
        skip_credit_check=bool(skip_llm_credit_check),
    )


def ensure_article_content_word_count(
    *,
    content_html: str,
    target_word_count: int,
    primary_keyword: str,
    title: str = "",
    target_website: str = "",
    outline_content: str = "",
    secondary_keywords: str = "",
    use_system_llm: bool = True,
    db=None,
    user=None,
    skip_llm_credit_check: bool = False,
) -> str:
    """Regenerate or repair HTML until stub/short content meets validated target (chatbot/system LLM)."""
    from app.services.content_ai_word_count_policy import (
        needs_word_count_repair,
        needs_word_count_trim,
        word_count_from_html,
    )
    from app.services.llm_content_writer import enforce_content_ai_word_count

    html = str(content_html or "").strip()
    wc = max(200, int(target_word_count or 1000))
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    title_s = str(title or pk).strip()

    def _needs_fix(h: str) -> bool:
        actual = word_count_from_html(h)
        return _is_stub_content_html(h) or needs_word_count_repair(actual, wc) or needs_word_count_trim(actual, wc)

    if not _needs_fix(html):
        return html

    if _is_stub_content_html(html) or word_count_from_html(html) < max(200, int(wc * 0.5)):
        try:
            from app.services.llm_content_writer import generate_content_ai_suggestion

            gen_kwargs = dict(
                field="content",
                primary_keyword=pk,
                title=title_s,
                outline_content=outline_content,
                target_website=target_website,
                secondary_keywords=secondary_keywords,
                target_word_count=wc,
                use_system_llm=use_system_llm,
            )
            if db is not None and user is not None:
                with _llm_gate_kwargs(
                    db=db,
                    user=user,
                    field="content",
                    skip_llm_credit_check=skip_llm_credit_check,
                    action="chatbot_word_count",
                ):
                    regen = generate_content_ai_suggestion(**gen_kwargs)
            else:
                regen = generate_content_ai_suggestion(**gen_kwargs)
            regen = str(regen or "").strip()
            if regen and not _is_stub_content_html(regen):
                html = regen
        except Exception:
            _LOG.exception("content regenerate for word count failed pk=%s", pk[:80])

    if _needs_fix(html):
        try:
            if db is not None and user is not None:
                with _llm_gate_kwargs(
                    db=db,
                    user=user,
                    field="content",
                    skip_llm_credit_check=skip_llm_credit_check,
                    action="chatbot_word_count_enforce",
                ):
                    html, _stats = enforce_content_ai_word_count(
                        html,
                        target_word_count=wc,
                        title=title_s,
                        primary_keyword=pk,
                        use_system_llm=use_system_llm,
                    )
            else:
                html, _stats = enforce_content_ai_word_count(
                    html,
                    target_word_count=wc,
                    title=title_s,
                    primary_keyword=pk,
                    use_system_llm=use_system_llm,
                )
            html = str(html or "").strip() or html
        except Exception:
            _LOG.exception("content enforce word count failed pk=%s", pk[:80])

    actual = word_count_from_html(html)
    if _is_stub_content_html(html) or needs_word_count_repair(actual, wc):
        raise RuntimeError(
            f"Không sinh được bài đủ ~{wc} từ (hiện {actual} từ). Kiểm tra cấu hình LLM hệ thống."
        )
    return html


def _first_line(text: str) -> str:
    parts = [x.strip() for x in str(text or "").replace("\r", "").split("\n") if x.strip()]
    return parts[0] if parts else str(text or "").strip()


def _llm_mode() -> str:
    mode = (os.getenv("CONTENT_AI_LLM_MODE", "auto") or "auto").strip().lower()
    return mode if mode in {"off", "auto", "title_meta_only", "content_only"} else "auto"


def _llm_fields(mode: str) -> set[str]:
    if mode == "off":
        return set()
    if mode == "title_meta_only":
        return {"title", "meta_description", "outline_content", "slug", "tags", "secondary_keywords"}
    if mode == "content_only":
        return {"content"}
    return {"title", "meta_description", "outline_content", "content", "slug", "tags", "secondary_keywords"}


def _bulk_fast_meta_enabled() -> bool:
    return (os.getenv("CONTENT_AI_BULK_FAST", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _derive_title_from_content(content: str, primary_keyword: str) -> str:
    html = str(content or "")
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if m:
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            return t
    return _first_line(primary_keyword)


def _derive_meta_from_content(content: str, primary_keyword: str, *, max_len: int = 155) -> str:
    text = re.sub(r"<[^>]+>", " ", str(content or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) >= 48:
        if len(text) <= max_len:
            return text
        cut = text[:max_len]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.strip()
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    return f"Tìm hiểu {pk or 'dịch vụ'} — thông tin chi tiết, quy trình và liên hệ tư vấn nhanh."[:max_len]


def _bulk_article_progress_pct(*, index: int, total: int, substep: int) -> int:
    """index: 0-based article index; substep: 0..100 within current article."""
    t = max(total, 1)
    base = int((index / t) * 100)
    span = max(1, int(100 / t))
    return max(1, min(99, base + int(span * max(0, min(100, substep)) / 100)))


def _suggest(
    field: str,
    *,
    primary_keyword: str,
    target_website: str = "",
    title: str = "",
    outline_content: str = "",
    content: str = "",
    meta_description: str = "",
    slug: str = "",
    tags: str = "",
    secondary_keywords: str = "",
    target_word_count: int | None = None,
    bulk_fast: bool = False,
    db=None,
    user=None,
    use_system_llm: bool = False,
    skip_llm_credit_check: bool = False,
) -> str:
    f = (field or "").strip().lower()
    mode = _llm_mode()
    use_system = bool(use_system_llm or (db is None and user is None))
    llm_cfg = _load_llm_cfg(use_system_llm=use_system)
    bulk_skip_llm = bulk_fast and f in {"title", "meta_description", "slug", "tags"}
    use_llm = bool(llm_cfg) and f in _llm_fields(mode) and not bulk_skip_llm
    if use_llm:
        try:
            from app.services.llm_content_writer import generate_content_ai_suggestion

            gen_kwargs = dict(
                field=f,
                title=title,
                content=content,
                target_website=target_website,
                slug=slug,
                tags=tags,
                meta_description=meta_description,
                primary_keyword=primary_keyword,
                secondary_keywords=secondary_keywords,
                outline_content=outline_content,
                target_word_count=target_word_count,
                use_system_llm=use_system,
            )
            if db is not None and user is not None:
                with _llm_gate_kwargs(
                    db=db,
                    user=user,
                    field=f,
                    skip_llm_credit_check=skip_llm_credit_check,
                ):
                    out = generate_content_ai_suggestion(**gen_kwargs)
            else:
                out = generate_content_ai_suggestion(**gen_kwargs)
            if str(out or "").strip():
                return str(out).strip()
        except Exception:
            if f == "content" and use_system:
                raise
            if f != "content":
                raise
    if f == "content":
        if use_system:
            raise RuntimeError("LLM hệ thống không sinh được nội dung bài viết.")
        return _fallback_content_html(primary_keyword=primary_keyword, title=title, outline_content=outline_content)
    return suggest_content_ai_field(
        field=f,
        title=title,
        content=content,
        target_website=target_website,
        slug=slug,
        tags=tags,
        meta_description=meta_description,
        primary_keyword=primary_keyword,
        secondary_keywords=secondary_keywords,
        outline_content=outline_content,
    )


def _bulk_planning_notes(*, search_volume: int = 0, content_type: str = "", brand_name: str = "") -> str:
    parts: list[str] = []
    bn = str(brand_name or "").strip()
    if bn:
        parts.append(f"BRAND_NAME: {bn}")
    ct = str(content_type or "").strip()
    if ct:
        parts.append(f"CONTENT_TYPE: {ct}")
    if search_volume and search_volume > 0:
        parts.append(f"SEARCH_VOLUME: {search_volume}")
    return "\n".join(parts)


def _write_one_article(
    *,
    user_id: int,
    primary_keyword: str,
    target_website: str,
    target_word_count: int,
    secondary_keywords: list[str],
    custom_title: str = "",
    custom_description: str = "",
    custom_outline: str = "",
    search_volume: int = 0,
    content_type: str = "",
    competitor_url: str = "",
    brand_name: str = "",
    wp_category_id: int = 0,
    bulk_fast: bool = False,
    on_progress=None,
    db=None,
    user=None,
    job_id: str | None = None,
    article_index: int | None = None,
    use_system_llm: bool = False,
    skip_llm_credit_check: bool = False,
    seo_writing_brief: str = "",
    run_seo_checklist: bool = False,
) -> dict[str, Any]:
    from app.services.content_ai_request_cache import reset_request_cache
    from app.services.content_ai_write_timing import ContentAiWriteTimer, bind_write_timer
    from app.services.content_ai_word_count_policy import word_count_from_html

    reset_request_cache()
    req_id = None
    if job_id and article_index is not None:
        req_id = f"bulk:{job_id}:{int(article_index)}"
    timer = ContentAiWriteTimer(
        endpoint="content_ai_bulk_write",
        request_id=req_id,
        user_id=int(user_id),
    )
    bind_write_timer(timer)
    pk = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    if not pk:
        raise ValueError("Từ khóa trống")
    use_system = bool(use_system_llm or (db is None and user is None))
    owns_gate_db = False
    if use_system and (db is None or user is None):
        db, user = _open_system_llm_db_user(user_id)
        owns_gate_db = True
    try:
        sec_str = ", ".join(str(x).strip() for x in (secondary_keywords or []) if str(x).strip())
        c_title = re.sub(r"\s+", " ", str(custom_title or "").strip())
        c_desc = re.sub(r"\s+", " ", str(custom_description or "").strip())
        c_outline = str(custom_outline or "").strip()

        if callable(on_progress):
            on_progress(8, "Đang lập dàn ý…")

        if c_outline:
            outline = c_outline
        else:
            outline = _suggest(
                "outline_content",
                primary_keyword=pk,
                target_website=target_website,
                secondary_keywords=sec_str,
                target_word_count=target_word_count,
                bulk_fast=bulk_fast,
                db=db,
                user=user,
                use_system_llm=use_system,
                skip_llm_credit_check=skip_llm_credit_check,
            )
        plan_notes = _bulk_planning_notes(
            search_volume=search_volume, content_type=content_type, brand_name=brand_name
        )
        if competitor_url and not c_outline:
            plan_notes = f"{plan_notes}\nCOMPETITOR_URL: {competitor_url}".strip()
        brief = str(seo_writing_brief or "").strip()
        if brief:
            plan_notes = f"{plan_notes}\n\n{brief}".strip() if plan_notes else brief

        if callable(on_progress):
            on_progress(28, f"Đang viết nội dung: {pk}")

        content = _suggest(
            "content",
            primary_keyword=pk,
            target_website=target_website,
            outline_content=outline,
            secondary_keywords=sec_str,
            target_word_count=target_word_count,
            title=c_title,
            meta_description=c_desc,
            content=plan_notes,
            bulk_fast=bulk_fast,
            db=db,
            user=user,
            use_system_llm=use_system,
            skip_llm_credit_check=skip_llm_credit_check,
        )

        if use_system and int(target_word_count or 0) >= 200:
            content = ensure_article_content_word_count(
                content_html=content,
                target_word_count=int(target_word_count),
                primary_keyword=pk,
                title=c_title or pk,
                target_website=target_website,
                outline_content=outline,
                secondary_keywords=sec_str,
                use_system_llm=True,
                db=db,
                user=user,
                skip_llm_credit_check=skip_llm_credit_check,
            )

        if callable(on_progress):
            on_progress(78, "Đang hoàn thiện title & meta…")

        if c_title:
            title = _first_line(c_title) or pk
        elif bulk_fast:
            title = _derive_title_from_content(content, pk)
        else:
            title = _first_line(
                _suggest(
                    "title",
                    primary_keyword=pk,
                    target_website=target_website,
                    outline_content=outline,
                    content=content,
                    secondary_keywords=sec_str,
                    bulk_fast=bulk_fast,
                    db=db,
                    user=user,
                    skip_llm_credit_check=skip_llm_credit_check,
                )
            ) or pk
        if c_desc:
            meta = _first_line(c_desc)
        elif bulk_fast:
            meta = _derive_meta_from_content(content, pk)
        else:
            meta = _first_line(
                _suggest(
                    "meta_description",
                    primary_keyword=pk,
                    target_website=target_website,
                    title=title,
                    outline_content=outline,
                    content=content,
                    secondary_keywords=sec_str,
                    bulk_fast=bulk_fast,
                    db=db,
                    user=user,
                    skip_llm_credit_check=skip_llm_credit_check,
                )
            )
        slug = _first_line(
            _suggest(
                "slug",
                primary_keyword=pk,
                title=title,
                outline_content=outline,
                target_website=target_website,
                bulk_fast=bulk_fast,
                db=db,
                user=user,
                skip_llm_credit_check=skip_llm_credit_check,
            )
        )
        tags_raw = _suggest(
            "tags",
            primary_keyword=pk,
            title=title,
            content=content,
            outline_content=outline,
            secondary_keywords=sec_str,
            bulk_fast=bulk_fast,
            db=db,
            user=user,
            skip_llm_credit_check=skip_llm_credit_check,
        )
        tag_list = [x.strip() for x in re.split(r"[,;]", str(tags_raw or "")) if x.strip()]

        try:
            wpc = int(wp_category_id or 0)
        except (TypeError, ValueError):
            wpc = 0
        draft_cats = [wpc] if wpc > 0 else None

        from app.services.content_ai_image_guard import repair_content_html_images

        content = repair_content_html_images(
            content,
            site_base=str(target_website or "").strip().rstrip("/"),
            source="bulk_write_article",
            probe_remote=False,
        )

        seo_score: int | None = None
        seo_issues: list[str] = []
        seo_status = ""
        seo_issue_count = 0
        if run_seo_checklist:
            if callable(on_progress):
                on_progress(88, "Đang chạy SEO checklist…")
            seo = run_bulk_article_seo_checklist(
                user_id=user_id,
                title=title,
                meta_description=meta,
                content_html=content,
                primary_keyword=pk,
                slug=slug,
                secondary_keywords=secondary_keywords,
                target_website=target_website,
                db=db,
                user=user,
                use_system_llm=use_system,
                skip_llm_credit_check=skip_llm_credit_check,
                lock_title=bool(c_title),
                lock_meta=bool(c_desc),
            )
            title = str(seo.get("title") or title)
            meta = str(seo.get("meta_description") or meta)
            slug = str(seo.get("slug") or slug)
            content = _strip_script_tags_bulk(str(seo.get("content") or content))
            if c_title:
                title = _first_line(c_title) or title
            if c_desc:
                meta = _first_line(c_desc) or meta
            # SEO autofix có thể làm lệch ±10% — enforce lại số từ 1 vòng.
            if use_system and int(target_word_count or 0) >= 200:
                content = ensure_article_content_word_count(
                    content_html=content,
                    target_word_count=int(target_word_count),
                    primary_keyword=pk,
                    title=title or pk,
                    target_website=target_website,
                    outline_content=outline,
                    secondary_keywords=sec_str,
                    use_system_llm=True,
                    db=db,
                    user=user,
                    skip_llm_credit_check=skip_llm_credit_check,
                )
                content = _strip_script_tags_bulk(content)
            seo_score = int(seo.get("seo_score") or 0)
            seo_issues = list(seo.get("seo_issues") or [])
            seo_status = str(seo.get("seo_status") or "needs_review")
            seo_issue_count = int(seo.get("seo_issue_count") or len(seo_issues))
            # Re-score nhẹ sau enforce (không LLM) để seo_score khớp HTML cuối.
            try:
                from app.services.content_ai_publish_checklist import evaluate_publish_checklist

                final_chk = evaluate_publish_checklist(
                    title=title,
                    meta_description=meta,
                    content_html=content,
                    primary_keyword=pk,
                    slug=slug,
                    secondary_keywords=secondary_keywords,
                )
                seo_score = int(final_chk.get("score") or seo_score)
                seo_issues = _seo_issues_from_checklist(final_chk)
                summary = final_chk.get("summary") if isinstance(final_chk.get("summary"), dict) else {}
                seo_status = _seo_status_for_bulk(
                    score=seo_score,
                    failed_n=int(summary.get("fail") or 0),
                )
                seo_issue_count = len(seo_issues)
            except Exception:
                pass
        else:
            content = _strip_script_tags_bulk(content)

        if callable(on_progress):
            on_progress(92, "Đang lưu dự án…")

        actual_wc = word_count_from_html(str(content))
        draft = build_draft_payload(
            title=title,
            content=content,
            slug=slug,
            tags=tag_list,
            meta_description=meta,
            target_website=target_website,
            primary_keyword=pk,
            secondary_keywords=secondary_keywords,
            outline_content=outline,
            categories=draft_cats,
        )
        # Tôn trọng dữ liệu user nhập tay — không lấy title/meta đã pad/cắt từ draft builder.
        if c_title:
            title = _first_line(c_title) or title
            draft["title"] = title
        if c_desc:
            meta = _first_line(c_desc) or meta
            draft["meta_description"] = meta
        content = _strip_script_tags_bulk(str(draft.get("content") or content))
        draft["content"] = content
        slug = str(draft.get("slug") or slug)
        source = {
            "title": title,
            "content": content,
            "slug": slug,
            "tags": tag_list,
            "meta_description": meta,
            "target_website": target_website,
            "primary_keyword": pk,
            "secondary_keywords": secondary_keywords,
            "outline_content": outline,
            "target_word_count": int(target_word_count or 1000),
            "validated_word_count": int(target_word_count or 1000),
            "actual_word_count": actual_wc,
            "custom_title": c_title,
            "custom_description": c_desc,
            "custom_outline": c_outline,
            "search_volume": int(search_volume or 0),
            "content_type": str(content_type or "").strip(),
            "competitor_url": str(competitor_url or "").strip(),
            "wp_category_id": wpc,
        }
        if seo_score is not None:
            source["seo_score"] = seo_score
            source["seo_issues"] = seo_issues
            source["seo_status"] = seo_status
            source["seo_issue_count"] = seo_issue_count
        project_id = save_or_update_written_bulk_project(
            user_id=user_id,
            source_payload=source,
            draft_payload=draft,
        )
        if db is not None and user is not None and str(content or "").strip() and not skip_llm_credit_check:
            from app.services.content_ai_credit_service import charge_content_ai_from_html

            req_id = None
            if job_id and article_index is not None:
                req_id = f"bulk:{job_id}:{int(article_index)}"
            used_llm_content = True
            charge_content_ai_from_html(
                db,
                user,
                str(content),
                field="content",
                use_system_llm=True,
                request_id=req_id,
                llm_used=used_llm_content,
                used_fallback=False,
            )
            from app.services.content_ai_word_count_policy import (
                build_word_count_response,
                log_word_count_event,
            )

            wc_meta = build_word_count_response(
                client_value=target_word_count,
                user=user,
                db=db,
                html=str(content),
            )
            log_word_count_event(
                user_id=int(user.id),
                endpoint="content_ai_bulk_runner",
                requested=int(wc_meta["requested_word_count"]),
                validated=int(wc_meta["validated_word_count"]),
                actual=int(wc_meta["actual_word_count"]),
                status=str(wc_meta["word_count_status"]),
                request_id=req_id,
            )
            db.commit()
        timer.finish()
        out: dict[str, Any] = {
            "project_id": project_id,
            "word_count": actual_wc,
            "title": title,
            "meta_description": meta,
        }
        if seo_score is not None:
            out["seo_score"] = seo_score
            out["seo_issues"] = seo_issues
            out["seo_status"] = seo_status
            out["seo_issue_count"] = seo_issue_count
        return out
    finally:
        if owns_gate_db and db is not None:
            db.close()


def write_content_ai_article(
    *,
    user_id: int,
    primary_keyword: str,
    target_website: str = "",
    target_word_count: int = 1000,
    secondary_keywords: list[str] | None = None,
    custom_title: str = "",
    custom_description: str = "",
    custom_outline: str = "",
    search_volume: int = 0,
    content_type: str = "",
    competitor_url: str = "",
    brand_name: str = "",
    wp_category_id: int = 0,
    bulk_fast: bool = False,
    on_progress=None,
    use_system_llm: bool = True,
    skip_llm_credit_check: bool = False,
    seo_writing_brief: str = "",
) -> str:
    """Entry point nội bộ (chatbot workflow, automation) — không đổi luồng bulk hiện tại."""
    result = _write_one_article(
        user_id=user_id,
        primary_keyword=primary_keyword,
        target_website=target_website,
        target_word_count=target_word_count,
        secondary_keywords=list(secondary_keywords or []),
        custom_title=custom_title,
        custom_description=custom_description,
        custom_outline=custom_outline,
        search_volume=search_volume,
        content_type=content_type,
        competitor_url=competitor_url,
        brand_name=brand_name,
        wp_category_id=wp_category_id,
        bulk_fast=bulk_fast,
        on_progress=on_progress,
        use_system_llm=use_system_llm,
        skip_llm_credit_check=skip_llm_credit_check,
        seo_writing_brief=seo_writing_brief,
        run_seo_checklist=False,
    )
    return str(result.get("project_id") or "")


def run_content_ai_bulk_job(job_id: str, payload: dict[str, Any]) -> None:
    from app.core.user_context import bind_request_user_id, unbind_request_user_id

    raw_items = payload.get("items")
    raw_kw = payload.get("keywords") or []
    kw_list: list[str] = []
    if isinstance(raw_kw, str):
        for line in raw_kw.replace("\r", "\n").split("\n"):
            k = line.strip()
            if k:
                kw_list.append(k)
    elif isinstance(raw_kw, list):
        for item in raw_kw:
            k = str(item or "").strip()
            if k:
                kw_list.append(k)

    item_dicts: list[dict[str, Any]] | None = None
    if isinstance(raw_items, list) and raw_items:
        item_dicts = [x for x in raw_items if isinstance(x, dict)]

    bulk_rows = normalize_bulk_job_items(keywords=kw_list, items=item_dicts)
    keywords = [r["keyword"] for r in bulk_rows]

    if not keywords:
        fail_job(job_id, error="Danh sách từ khóa trống.")
        return

    try:
        bulk_user_id = int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        bulk_user_id = 0
    if bulk_user_id <= 0:
        fail_job(job_id, error="Thiếu user_id trong job — hãy đăng nhập và chạy lại bulk.")
        return

    user_ctx_token = bind_request_user_id(bulk_user_id)
    try:
        _run_content_ai_bulk_job_body(
            job_id=job_id,
            payload=payload,
            bulk_rows=bulk_rows,
            keywords=keywords,
            bulk_user_id=bulk_user_id,
        )
    finally:
        unbind_request_user_id(user_ctx_token)


def _run_content_ai_bulk_job_body(
    *,
    job_id: str,
    payload: dict[str, Any],
    bulk_rows: list[dict[str, Any]],
    keywords: list[str],
    bulk_user_id: int,
) -> None:
    from app.services.content_ai_word_count_policy import validate_target_word_count

    target_website = str(payload.get("target_website") or "").strip()
    try:
        raw_target_wc = int(payload.get("target_word_count") or 1000)
    except (TypeError, ValueError):
        raw_target_wc = 1000

    sec_raw = payload.get("secondary_keywords") or []
    secondary: list[str] = []
    if isinstance(sec_raw, str):
        secondary = [x.strip() for x in sec_raw.split(",") if x.strip()]
    elif isinstance(sec_raw, list):
        secondary = [str(x).strip() for x in sec_raw if str(x).strip()]

    brand_name = str(payload.get("brand_name") or "").strip()
    try:
        wp_cat = int(payload.get("wp_category_id") or 0)
    except (TypeError, ValueError):
        wp_cat = 0
    if wp_cat < 0:
        wp_cat = 0
    total = len(keywords)
    bulk_fast = _bulk_fast_meta_enabled()
    items: list[dict[str, Any]] = [{"keyword": r["keyword"], "status": "pending"} for r in bulk_rows]
    success_n = 0

    from app.db import SessionLocal
    from app.models.user import User

    gate_db = SessionLocal()
    bulk_user = gate_db.get(User, bulk_user_id)
    if not bulk_user:
        gate_db.close()
        fail_job(job_id, error="User không tồn tại.")
        return

    target_word_count = validate_target_word_count(raw_target_wc, bulk_user, gate_db)

    def _publish_progress(*, index: int, substep: int, message: str) -> None:
        pct = _bulk_article_progress_pct(index=index, total=total, substep=substep)
        update_job(
            job_id,
            progress=pct,
            message=message,
            result={
                "total": total,
                "success": success_n,
                "failed": sum(1 for x in items if x.get("status") == "error"),
                "target_website": target_website,
                "items": items,
            },
        )

    _publish_progress(index=0, substep=0, message=f"Chuẩn bị viết {total} bài…")

    try:
        for i, row in enumerate(bulk_rows):
            st_chk = get_job(job_id)
            if st_chk and st_chk.state == "CANCELLED":
                update_job(
                    job_id,
                    message="Đã dừng — giữ kết quả đã viết",
                    result={
                        "total": total,
                        "success": success_n,
                        "failed": sum(1 for x in items if x.get("status") == "error"),
                        "cancelled": True,
                        "target_website": target_website,
                        "items": items,
                    },
                )
                return
            kw = row["keyword"]
            items[i] = {**items[i], "status": "running", "keyword": kw}
            _publish_progress(
                index=i,
                substep=2,
                message=f"Đang viết bài {i + 1}/{total}: {kw}",
            )

            def _article_progress(substep: int, step_msg: str) -> None:
                _publish_progress(
                    index=i,
                    substep=substep,
                    message=f"Đang viết bài {i + 1}/{total}: {kw} — {step_msg}",
                )

            try:
                raw_row_wc = row.get("target_word_count")
                try:
                    row_wc = int(raw_row_wc or 0)
                except (TypeError, ValueError):
                    row_wc = 0
                if raw_row_wc is None or str(raw_row_wc).strip() == "":
                    item_wc = _auto_target_word_count_for_row(
                        row=row,
                        fallback_word_count=target_word_count,
                        bulk_user=bulk_user,
                        gate_db=gate_db,
                    )
                else:
                    item_wc = validate_target_word_count(
                        row_wc if row_wc >= 200 else target_word_count,
                        bulk_user,
                        gate_db,
                    )
                row_sec_raw = row.get("secondary_keywords")
                row_secondary: list[str] = []
                if isinstance(row_sec_raw, list):
                    row_secondary = [str(x).strip() for x in row_sec_raw if str(x).strip()]
                elif isinstance(row_sec_raw, str):
                    row_secondary = [x.strip() for x in re.split(r"[,;\n\r]+", row_sec_raw) if x.strip()]
                use_secondary = row_secondary if row_secondary else secondary
                try:
                    row_wp = int(row.get("wp_category_id") or 0)
                except (TypeError, ValueError):
                    row_wp = 0
                if row_wp <= 0:
                    row_wp = wp_cat
                row_target_website = str(row.get("target_website") or "").strip() or target_website
                project_id = _write_one_article(
                    user_id=bulk_user_id,
                    primary_keyword=kw,
                    target_website=row_target_website,
                    target_word_count=item_wc,
                    secondary_keywords=use_secondary,
                    custom_title=row.get("custom_title") or "",
                    custom_description=row.get("custom_description") or "",
                    custom_outline=row.get("custom_outline") or "",
                    search_volume=int(row.get("search_volume") or 0),
                    content_type=str(row.get("content_type") or ""),
                    competitor_url=str(row.get("competitor_url") or ""),
                    brand_name=brand_name,
                    wp_category_id=row_wp,
                    bulk_fast=bulk_fast,
                    on_progress=_article_progress,
                    db=gate_db,
                    user=bulk_user,
                    job_id=job_id,
                    article_index=i,
                    run_seo_checklist=True,
                )
                success_n += 1
                written = project_id if isinstance(project_id, dict) else {"project_id": project_id}
                items[i] = {
                    "keyword": kw,
                    "status": "success",
                    "project_id": str(written.get("project_id") or ""),
                    "custom_title": row.get("custom_title") or "",
                    "custom_description": row.get("custom_description") or "",
                    "custom_outline": row.get("custom_outline") or "",
                    "word_count": written.get("word_count"),
                    "seo_score": written.get("seo_score"),
                    "seo_issues": written.get("seo_issues") or [],
                    "seo_status": written.get("seo_status") or "",
                    "seo_issue_count": written.get("seo_issue_count"),
                    "title": written.get("title") or "",
                    "meta_description": written.get("meta_description") or "",
                }
                done_pct = _bulk_article_progress_pct(index=i + 1, total=total, substep=0)
                update_job(
                    job_id,
                    progress=done_pct,
                    message=f"Đã xong bài {i + 1}/{total}: {kw}",
                    result={
                        "total": total,
                        "success": success_n,
                        "failed": sum(1 for x in items if x.get("status") == "error"),
                        "target_website": target_website,
                        "items": items,
                    },
                )
            except Exception as exc:
                items[i] = {"keyword": kw, "status": "error", "error": str(exc)[:800]}
                update_job(
                    job_id,
                    progress=_bulk_article_progress_pct(index=i + 1, total=total, substep=0),
                    message=f"Lỗi bài {i + 1}/{total}: {kw}",
                    result={
                        "total": total,
                        "success": success_n,
                        "failed": sum(1 for x in items if x.get("status") == "error"),
                        "target_website": target_website,
                        "items": items,
                    },
                )

        finish_job(
            job_id,
            result={
                "total": total,
                "success": success_n,
                "failed": total - success_n,
                "target_website": target_website,
                "items": items,
            },
        )
    finally:
        gate_db.close()
