"""Chatbot Viết bài SEO — tích hợp 30 yếu tố SEO Score (evaluate_publish_checklist)."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from app.services.content_ai_publish_checklist import (
    build_seo_score_writing_brief,
    evaluate_publish_checklist,
)
from app.services.content_ai_word_count_policy import word_count_from_html
from app.services.seo_core_30_score import (
    factors_failed_items,
    factors_not_passed,
    score_seo_core_30,
    seo_factor_counts,
)

_LOG = logging.getLogger(__name__)

# Yếu tố bắt buộc phải đạt (failed) trước khi lưu bài chatbot.
MANDATORY_FACTOR_IDS: frozenset[str] = frozenset(
    {
        "heading_single_h1",
        "title_keyword",
        "meta_quality",
        "heading_h2_count",
        "heading_hierarchy",
        "helpful_faq_conclusion",
        "intent_h1_keyword",
        "keyword_in_body",
        "depth_word_count",
        "helpful_word_count",
    }
)

MIN_WORD_RATIO_HARD = 0.60
MIN_WORD_RATIO_TARGET = 0.90
MIN_SEO_SCORE_SAVE = 50
MAX_SEO_REWRITE_ATTEMPTS = 2


def _status_norm(st: str) -> str:
    s = str(st or "").lower()
    if s in ("failed", "fail"):
        return "failed"
    if s in ("warning", "warn"):
        return "warning"
    return "passed" if s in ("passed", "ok") else s


def mandatory_failures(score_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Yếu tố bắt buộc đang failed."""
    out: list[dict[str, Any]] = []
    for f in score_result.get("factors") or []:
        fid = str(f.get("id") or "")
        if fid in MANDATORY_FACTOR_IDS and _status_norm(f.get("status")) == "failed":
            out.append(f)
    return out


def word_count_gate(*, actual: int, target: int) -> dict[str, Any]:
    tgt = max(200, int(target or 1000))
    act = max(0, int(actual or 0))
    hard_min = max(200, int(tgt * MIN_WORD_RATIO_HARD))
    target_min = max(200, int(tgt * MIN_WORD_RATIO_TARGET))
    return {
        "target": tgt,
        "actual": act,
        "hard_min": hard_min,
        "target_min": target_min,
        "below_hard": act < hard_min,
        "below_target": act < target_min,
    }


def build_seo_result_summary(
    *,
    score_result: dict[str, Any],
    target_word_count: int,
    actual_word_count: int,
) -> dict[str, Any]:
    counts = seo_factor_counts(score_result)
    failed = factors_failed_items(score_result)
    warnings = [f for f in factors_not_passed(score_result) if _status_norm(f.get("status")) == "warning"]
    return {
        "seo_score": int(score_result.get("score") or 0),
        "grade_label": str(score_result.get("grade_label") or ""),
        "grade_tier": str(score_result.get("grade_tier") or ""),
        "passed_factors": int(counts.get("passed") or 0),
        "warning_factors": int(counts.get("warning") or 0),
        "failed_factors": int(counts.get("failed") or 0),
        "total_factors": int(counts.get("total") or 30),
        "requested_word_count": int(target_word_count),
        "actual_word_count": int(actual_word_count),
        "failed_factor_ids": [str(f.get("id") or "") for f in failed if f.get("id")],
        "failed_factor_labels": [str(f.get("label") or "") for f in failed],
        "warning_factor_labels": [str(f.get("label") or "") for f in warnings[:8]],
        "groups": score_result.get("groups") or [],
    }


def _log_debug(
    *,
    workflow_id: str,
    keyword: str,
    target_word_count: int,
    actual_word_count: int,
    seo_score: int,
    passed_factors: int,
    failed_factors: list[str],
    rewrite_attempts: int,
    extra: str = "",
) -> None:
    _LOG.info(
        "chatbot_seo_write workflow_id=%s keyword=%s target_wc=%s actual_wc=%s "
        "seo_score=%s passed=%s failed=%s rewrite_attempts=%s %s",
        (workflow_id or "")[:32],
        (keyword or "")[:80],
        int(target_word_count),
        int(actual_word_count),
        int(seo_score),
        int(passed_factors),
        ",".join(failed_factors[:12]),
        int(rewrite_attempts),
        extra.strip(),
    )


def _apply_autofix_patch(
    *,
    title: str,
    meta: str,
    slug: str,
    content_html: str,
    patch: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        str(patch.get("title") or title).strip(),
        str(patch.get("meta_description") or meta).strip()[:320],
        str(patch.get("slug") or slug).strip(),
        str(patch.get("content_html") or content_html).strip(),
    )


def _rewrite_with_seo_autofix(
    *,
    user_id: int,
    title: str,
    meta: str,
    content_html: str,
    slug: str,
    primary_keyword: str,
    secondary_keywords: list[str],
    target_website: str,
    mode: str = "severe",
) -> dict[str, Any]:
    from app.services.content_ai_bulk_runner import _open_system_llm_db_user
    from app.services.content_ai_seo_autofix import run_seo_autofix_preview

    db, user = _open_system_llm_db_user(int(user_id))
    try:
        preview = run_seo_autofix_preview(
            user_id=int(user_id),
            db=db,
            user=user,
            title=title,
            meta_description=meta,
            content_html=content_html,
            primary_keyword=primary_keyword,
            slug=slug,
            secondary_keywords=secondary_keywords,
            target_website=target_website,
            mode=mode,
            use_system_llm=True,
            skip_llm_credit_check=True,
        )
        db.commit()
        return preview
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def enforce_chatbot_seo_article(
    *,
    user_id: int,
    workflow_id: str = "",
    primary_keyword: str,
    title: str,
    meta_description: str,
    slug: str,
    content_html: str,
    secondary_keywords: list[str] | None = None,
    target_website: str = "",
    target_word_count: int,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Chấm SEO Core 30, kiểm tra số từ, tự sửa yếu tố bắt buộc.
    Trả dict: ok, title, meta_description, slug, content_html, seo_summary, error.
    """
    sec = list(secondary_keywords or [])
    t = str(title or "").strip()
    m = str(meta_description or "").strip()
    s = str(slug or "").strip()
    html = str(content_html or "").strip()
    pk = str(primary_keyword or "").strip()
    rewrite_attempts = 0

    def _progress(msg: str) -> None:
        if callable(on_progress):
            on_progress(msg)

    if not html:
        return {
            "ok": False,
            "error": "Nội dung bài viết trống.",
            "title": t,
            "meta_description": m,
            "slug": s,
            "content_html": html,
            "rewrite_attempts": rewrite_attempts,
        }

    _progress("Đang kiểm tra số từ…")
    wc_gate = word_count_gate(actual=word_count_from_html(html), target=target_word_count)
    if wc_gate["below_hard"]:
        return {
            "ok": False,
            "error": (
                f"Bài chỉ ~{wc_gate['actual']} từ (<{wc_gate['hard_min']} từ, "
                f"dưới 60% mục tiêu {wc_gate['target']})."
            ),
            "title": t,
            "meta_description": m,
            "slug": s,
            "content_html": html,
            "rewrite_attempts": rewrite_attempts,
            "word_count_gate": wc_gate,
        }

    score = score_seo_core_30(
        title=t,
        meta_description=m,
        content_html=html,
        primary_keyword=pk,
        slug=s,
        secondary_keywords=sec,
    )
    counts = seo_factor_counts(score)
    _log_debug(
        workflow_id=workflow_id,
        keyword=pk,
        target_word_count=target_word_count,
        actual_word_count=wc_gate["actual"],
        seo_score=int(score.get("score") or 0),
        passed_factors=int(counts.get("passed") or 0),
        failed_factors=[str(f.get("id") or "") for f in factors_failed_items(score)],
        rewrite_attempts=rewrite_attempts,
        extra="initial_score",
    )

    while rewrite_attempts < MAX_SEO_REWRITE_ATTEMPTS:
        mandatory = mandatory_failures(score)
        wc_gate = word_count_gate(actual=word_count_from_html(html), target=target_word_count)
        score_val = int(score.get("score") or 0)
        needs_rewrite = bool(mandatory) or wc_gate["below_target"] or score_val < MIN_SEO_SCORE_SAVE
        if not needs_rewrite:
            break

        rewrite_attempts += 1
        _progress("Đang chấm 30 yếu tố SEO Score…")
        _progress("Đang tối ưu lại bài viết…")
        try:
            preview = _rewrite_with_seo_autofix(
                user_id=int(user_id),
                title=t,
                meta=m,
                content_html=html,
                slug=s,
                primary_keyword=pk,
                secondary_keywords=sec,
                target_website=target_website,
                mode="severe",
            )
        except Exception as exc:
            _LOG.exception("chatbot seo rewrite failed wf=%s", workflow_id[:32])
            return {
                "ok": False,
                "error": f"Không tối ưu được bài theo SEO Score: {exc}",
                "title": t,
                "meta_description": m,
                "slug": s,
                "content_html": html,
                "rewrite_attempts": rewrite_attempts,
                "seo_summary": build_seo_result_summary(
                    score_result=score,
                    target_word_count=target_word_count,
                    actual_word_count=wc_gate["actual"],
                ),
            }

        if not preview.get("success"):
            patch = preview.get("patch") or {}
            if patch.get("content_html"):
                t, m, html, s = _apply_autofix_patch(
                    title=t, meta=m, slug=s, content_html=html, patch=patch
                )
            else:
                break

        patch = preview.get("patch") or {}
        t, m, html, s = _apply_autofix_patch(
            title=t, meta=m, slug=s, content_html=html, patch=patch
        )
        score = score_seo_core_30(
            title=t,
            meta_description=m,
            content_html=html,
            primary_keyword=pk,
            slug=s,
            secondary_keywords=sec,
        )

    wc_gate = word_count_gate(actual=word_count_from_html(html), target=target_word_count)
    mandatory = mandatory_failures(score)
    score_val = int(score.get("score") or 0)
    counts = seo_factor_counts(score)
    failed_ids = [str(f.get("id") or "") for f in factors_failed_items(score)]

    _log_debug(
        workflow_id=workflow_id,
        keyword=pk,
        target_word_count=target_word_count,
        actual_word_count=wc_gate["actual"],
        seo_score=score_val,
        passed_factors=int(counts.get("passed") or 0),
        failed_factors=failed_ids,
        rewrite_attempts=rewrite_attempts,
        extra="final",
    )

    seo_summary = build_seo_result_summary(
        score_result=score,
        target_word_count=target_word_count,
        actual_word_count=wc_gate["actual"],
    )
    seo_summary["rewrite_attempts"] = rewrite_attempts

    if wc_gate["below_hard"]:
        return {
            "ok": False,
            "error": (
                f"Sau tối ưu vẫn chỉ ~{wc_gate['actual']} từ "
                f"(cần ≥{wc_gate['hard_min']} từ)."
            ),
            "title": t,
            "meta_description": m,
            "slug": s,
            "content_html": html,
            "rewrite_attempts": rewrite_attempts,
            "seo_summary": seo_summary,
            "word_count_gate": wc_gate,
        }

    if mandatory or score_val < MIN_SEO_SCORE_SAVE:
        labels = [str(f.get("label") or f.get("id")) for f in mandatory[:6]]
        return {
            "ok": False,
            "error": (
                f"SEO Score {score_val}/100 — chưa đạt yếu tố bắt buộc: "
                + (", ".join(labels) if labels else f"điểm < {MIN_SEO_SCORE_SAVE}")
            ),
            "title": t,
            "meta_description": m,
            "slug": s,
            "content_html": html,
            "rewrite_attempts": rewrite_attempts,
            "seo_summary": seo_summary,
        }

    return {
        "ok": True,
        "title": t,
        "meta_description": m,
        "slug": s,
        "content_html": html,
        "rewrite_attempts": rewrite_attempts,
        "seo_summary": seo_summary,
        "word_count_gate": wc_gate,
    }


def format_chatbot_seo_reply_lines(seo_summary: dict[str, Any]) -> list[str]:
    """Dòng hiển thị SEO trong kết quả chatbot."""
    if not seo_summary:
        return []
    passed = int(seo_summary.get("passed_factors") or 0)
    total = int(seo_summary.get("total_factors") or 30)
    lines = [
        f"- **Số từ yêu cầu:** {seo_summary.get('requested_word_count', '—')}",
        f"- **Số từ thực tế:** {seo_summary.get('actual_word_count', '—')}",
        f"- **SEO Score:** {seo_summary.get('seo_score', '—')}/100 ({seo_summary.get('grade_label', '')})",
        f"- **Yếu tố đạt:** {passed}/{total}",
    ]
    warn = seo_summary.get("warning_factor_labels") or []
    fail = seo_summary.get("failed_factor_labels") or []
    if fail:
        lines.append(f"- **Chưa đạt:** {', '.join(fail[:5])}")
    elif warn:
        lines.append(f"- **Cần tối ưu thêm:** {', '.join(warn[:5])}")
    return lines
