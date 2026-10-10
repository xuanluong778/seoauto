"""Queue long CAU / Content-AI LLM calls via job_store (poll contract for SeoautoAwaitQueued)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User

_LOG = logging.getLogger(__name__)
_RUN_GUARD = threading.Lock()
_RUNNING: set[str] = set()


def enqueue_llm_routed(
    db: Session,
    user: User,
    *,
    action: str,
    payload: dict[str, Any],
    credit_cost: int = 0,
    credit_reason: str = "",
    poll_url_prefix: str = "/content-ai/llm/jobs",
) -> dict[str, Any]:
    """Create a persisted job and run the LLM action in a background thread."""
    from app.services.job_store import create_job, ensure_job_schema

    ensure_job_schema()
    merged = dict(payload or {})
    merged.update(
        {
            "action": str(action or "").strip(),
            "credit_cost": int(credit_cost or 0),
            "credit_reason": str(credit_reason or "")[:64],
        }
    )
    job = create_job(
        job_type="llm_routed",
        message="Đang xếp hàng…",
        payload=merged,
        user_id=int(user.id),
    )
    if not _begin_run(job.job_id):
        _LOG.warning("llm_routed duplicate run skipped job=%s", job.job_id)
    else:
        threading.Thread(
            target=_run_llm_job_safe,
            args=(job.job_id, int(user.id)),
            daemon=True,
            name=f"llm-routed-{job.job_id[:8]}",
        ).start()
    prefix = str(poll_url_prefix or "/content-ai/llm/jobs").rstrip("/")
    return {
        "job_id": job.job_id,
        "poll_url": f"{prefix}/{job.job_id}",
        "state": job.state,
        "message": job.message,
    }


def poll_llm_job(job_id: str, *, user_id: int) -> dict[str, Any] | None:
    """Return poll payload for GET /content-ai/llm/jobs/{id} (None if not found / wrong user)."""
    from app.services.job_store import get_job_for_user

    job = get_job_for_user(job_id, user_id=user_id)
    if not job:
        return None
    state = str(job.state or "QUEUED").upper()
    out: dict[str, Any] = {
        "job_id": job.job_id,
        "state": state,
        "progress": int(job.progress or 0),
        "message": job.message or "",
    }
    if state == "SUCCESS" and isinstance(job.result, dict):
        out.update(job.result)
    elif state == "ERROR":
        out["error"] = job.error or job.message or "Job failed"
    return out


def _begin_run(job_id: str) -> bool:
    jid = str(job_id or "").strip()
    if not jid:
        return False
    with _RUN_GUARD:
        if jid in _RUNNING:
            return False
        _RUNNING.add(jid)
        return True


def _end_run(job_id: str) -> None:
    jid = str(job_id or "").strip()
    if not jid:
        return
    with _RUN_GUARD:
        _RUNNING.discard(jid)


def _run_llm_job_safe(job_id: str, user_id: int) -> None:
    try:
        _run_llm_job(job_id, user_id)
    except Exception:
        _LOG.exception("llm_routed job failed job_id=%s", job_id)
    finally:
        _end_run(job_id)


def _run_llm_job(job_id: str, user_id: int) -> None:
    from app.services.job_store import fail_job, finish_job, get_job, update_job

    job = get_job(job_id)
    if not job:
        return
    payload = dict(job.payload or {})
    action = str(payload.get("action") or job.job_type or "").strip()
    update_job(job_id, state="RUNNING", progress=5, message="Đang xử lý AI…")

    db = SessionLocal()
    try:
        user = db.get(User, int(user_id))
        if not user:
            fail_job(job_id, error="User not found")
            db.commit()
            return
        result = _dispatch_action(db, user, action, payload)
        finish_job(job_id, result=result)
        db.commit()
    except Exception as exc:
        db.rollback()
        fail_job(job_id, error=str(exc)[:500])
        db2 = SessionLocal()
        try:
            db2.commit()
        finally:
            db2.close()
        raise
    finally:
        db.close()


def _dispatch_action(db: Session, user: User, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "cau_generate":
        return _run_cau_generate(db, user, payload)
    if action == "cau_modal_rewrite":
        return _run_cau_modal_rewrite(user, payload)
    if action == "cau_modal_append_headings":
        return _run_cau_modal_append(user, payload)
    if action == "cau_modal_fix_factor":
        return _run_cau_modal_fix_factor(user, payload, parallel=False)
    if action == "cau_modal_fix_factors":
        return _run_cau_modal_fix_factor(user, payload, parallel=True)
    if action == "cau_modal_analyze":
        return _run_cau_modal_analyze(user, payload)
    raise ValueError(f"Unknown llm_routed action: {action}")


def _run_cau_generate(db: Session, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.content_auto_update_entitlement import record_cau_usage
    from app.services.content_backup import get_session, save_session
    from app.services.content_update_agent import _fallback_update, generate_seo_update, validate_preserved_markup
    from app.services.seo_core_30_score import (
        build_seo_update_summary,
        compare_seo_scores,
        factors_failed_items,
        factors_not_passed,
        factors_warning_items,
        score_seo_core_30,
        seo_factor_counts,
    )

    session_id = str(payload.get("session_id") or "").strip()
    keyword = str(payload.get("keyword") or "").strip()
    focus = str(payload.get("focus") or "")
    session = get_session(session_id, user.id)
    if not session:
        raise ValueError("Không tìm thấy session.")

    orig = session.get("original") or {}
    slug = str(session.get("slug") or "")
    seo_before = score_seo_core_30(
        title=str(orig.get("title") or ""),
        meta_description=str(orig.get("excerpt") or ""),
        content_html=str(orig.get("content") or ""),
        primary_keyword=keyword,
        slug=slug,
    )
    failed_items = factors_failed_items(seo_before)
    warning_items = factors_warning_items(seo_before)
    old_title = str(orig.get("title") or "")
    old_content = str(orig.get("content") or "")
    old_excerpt = str(orig.get("excerpt") or "")

    proposal = generate_seo_update(
        user_id=user.id,
        title=old_title,
        content=old_content,
        excerpt=old_excerpt,
        keyword=keyword,
        focus=focus,
        seo_before=seo_before,
        failed_factors=failed_items,
        warning_factors=warning_items,
    )
    warnings = validate_preserved_markup(old_content, str(proposal.get("content") or ""))

    def _score_proposal(prop: dict[str, Any]) -> dict[str, Any]:
        return score_seo_core_30(
            title=str(prop.get("title") or ""),
            meta_description=str(prop.get("excerpt") or prop.get("meta_description") or ""),
            content_html=str(prop.get("content") or ""),
            primary_keyword=keyword,
            slug=slug,
        )

    seo_after = _score_proposal(proposal)
    before_score = int(seo_before.get("score") or 0)
    after_score = int(seo_after.get("score") or 0)
    score_regressed = after_score < before_score

    if score_regressed:
        safe = _fallback_update(
            title=old_title,
            content=old_content,
            excerpt=old_excerpt,
            keyword=keyword,
        )
        safe["content"] = old_content
        safe["summary"] = "Điểm SEO giảm sau AI — giữ nguyên HTML gốc, chỉ giữ title/excerpt an toàn."
        proposal = safe
        seo_after = _score_proposal(proposal)
        after_score = int(seo_after.get("score") or 0)
        score_regressed = after_score < before_score

    seo_comparison = compare_seo_scores(seo_before, seo_after)
    ai_summary = build_seo_update_summary(
        comparison=seo_comparison,
        preserve_warnings=warnings,
        score_regressed=score_regressed,
    )
    if proposal.get("summary"):
        ai_summary = f"{proposal.get('summary')} | {ai_summary}"

    session = dict(session)
    session["proposal"] = proposal
    session["keyword"] = keyword
    session["preserve_warnings"] = warnings
    session["seo_before"] = seo_before
    session["seo_after"] = seo_after
    session["seo_comparison"] = seo_comparison
    session["score_regressed"] = score_regressed
    session = save_session(user.id, session)
    record_cau_usage(
        db,
        user,
        "content_auto_update_generate",
        metadata={"session_id": session_id},
        idempotency_key=f"cau-gen:{session_id}:{session.get('updated_at')}",
    )

    pub_keys = (
        "id", "site_id", "post_url", "wp_id", "post_type", "slug", "keyword",
        "backup_id", "created_at", "updated_at", "score_regressed",
    )
    public_session = {k: session[k] for k in pub_keys if k in session}

    return {
        "session": public_session,
        "proposal": {
            "title": proposal.get("title"),
            "excerpt": proposal.get("excerpt"),
            "meta_description": proposal.get("meta_description"),
            "summary": proposal.get("summary"),
            "notes": proposal.get("notes"),
        },
        "warnings": warnings,
        "ai_summary": ai_summary,
        "seo_before": seo_before,
        "seo_after": seo_after,
        "seo_summary_before": seo_factor_counts(seo_before),
        "seo_summary_after": seo_factor_counts(seo_after),
        "seo_comparison": seo_comparison,
        "failed_items": failed_items,
        "warning_items": warning_items,
        "failed_factors": factors_not_passed(seo_before),
        "failed_after": seo_comparison.get("failed_after") or [],
        "improved_factors": seo_comparison.get("improved_factors") or [],
        "score_regressed": score_regressed,
    }


def _run_cau_modal_rewrite(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.cau_modal_content_writer import preview_rewrite_modal_content

    secondary = payload.get("secondary_keywords")
    if isinstance(secondary, str):
        secondary = [x.strip() for x in secondary.split(",") if x.strip()]
    return preview_rewrite_modal_content(
        title=str(payload.get("title") or ""),
        meta_description=str(payload.get("meta_description") or ""),
        slug=str(payload.get("slug") or ""),
        primary_keyword=str(payload.get("primary_keyword") or ""),
        secondary_keywords=secondary if isinstance(secondary, list) else None,
        outline_content=str(payload.get("outline_content") or ""),
        content_html=str(payload.get("content_html") or ""),
        post_url=str(payload.get("post_url") or ""),
        target_word_count=payload.get("target_word_count"),
        user_id=int(user.id),
        use_system_llm=bool(payload.get("use_system_llm")),
    )


def _run_cau_modal_append(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.cau_modal_content_writer import preview_append_headings_modal_content

    secondary = payload.get("secondary_keywords")
    if isinstance(secondary, str):
        secondary = [x.strip() for x in secondary.split(",") if x.strip()]
    headings = payload.get("headings") or []
    if not isinstance(headings, list):
        headings = []
    return preview_append_headings_modal_content(
        headings=[str(h) for h in headings],
        title=str(payload.get("title") or ""),
        meta_description=str(payload.get("meta_description") or ""),
        slug=str(payload.get("slug") or ""),
        primary_keyword=str(payload.get("primary_keyword") or ""),
        secondary_keywords=secondary if isinstance(secondary, list) else None,
        outline_content=str(payload.get("outline_content") or ""),
        content_html=str(payload.get("content_html") or ""),
        post_url=str(payload.get("post_url") or ""),
        user_id=int(user.id),
        use_system_llm=bool(payload.get("use_system_llm")),
        auto_generate_heading=bool(payload.get("auto_generate_heading")),
    )


def _run_cau_modal_fix_factor(user: User, payload: dict[str, Any], *, parallel: bool) -> dict[str, Any]:
    from app.services.cau_seo_fix_engine import fix_cau_factor_fast, fix_cau_factors_parallel

    secondary = payload.get("secondary_keywords")
    if isinstance(secondary, str):
        secondary = [x.strip() for x in secondary.split(",") if x.strip()]
    common = dict(
        post_url=str(payload.get("post_url") or ""),
        title=str(payload.get("title") or ""),
        meta_description=str(payload.get("meta_description") or ""),
        content_html=str(payload.get("content_html") or ""),
        primary_keyword=str(payload.get("primary_keyword") or ""),
        slug=str(payload.get("slug") or ""),
        secondary_keywords=secondary if isinstance(secondary, list) else None,
        category_name=str(payload.get("category_name") or ""),
        user_id=int(user.id),
        use_system_llm=bool((payload.get("ai_fix") or {}).get("use_system_llm")),
    )
    if parallel:
        factor_ids = payload.get("factor_ids") or []
        if not isinstance(factor_ids, list):
            factor_ids = []
        return fix_cau_factors_parallel(factor_ids=[str(x) for x in factor_ids], **common)
    return fix_cau_factor_fast(factor_id=str(payload.get("factor_id") or ""), **common)


def _run_cau_modal_analyze(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.cau_seo_analyzer import evaluate_cau_modal_seo
    from app.services.cau_seo_fix_engine import _suggested_internal_links
    from app.services.content_backup import get_session
    from app.services.content_update_agent import validate_preserved_markup
    from app.services.seo_core_30_score import factors_failed_items, factors_warning_items

    session_id = str(payload.get("session_id") or "").strip()
    session = get_session(session_id, user.id) if session_id else None
    slug = str(payload.get("slug") or (session or {}).get("slug") or "")
    keyword = str(payload.get("keyword") or "").strip()
    title = str(payload.get("title") or "")
    content = str(payload.get("content") or "")
    excerpt = str(payload.get("excerpt") or "")

    seo_after = evaluate_cau_modal_seo(
        title=title,
        meta_description=excerpt,
        content_html=content,
        primary_keyword=keyword,
        slug=slug,
    )
    failed_items = factors_failed_items(seo_after)
    warning_items = factors_warning_items(seo_after)
    suggestions: list[str] = []
    for item in failed_items + warning_items:
        sug = str(item.get("suggestion") or item.get("message") or "").strip()
        if sug:
            label = str(item.get("label") or item.get("id") or "SEO")
            suggestions.append(f"{label}: {sug}")

    post_url = str((session or {}).get("post_url") or "")
    internal_links = _suggested_internal_links(post_url, keyword)[:5]
    for link in internal_links:
        url = str(link.get("url") or "").strip()
        anchor = str(link.get("anchor") or keyword).strip()
        if url:
            suggestions.append(f"Internal link: {anchor} → {url}")

    orig_content = str(((session or {}).get("original") or {}).get("content") or content)
    warnings = validate_preserved_markup(orig_content, content) if content else []

    return {
        "proposal": {
            "summary": f"Phân tích SEO — điểm {seo_after.get('score', 0)}/100",
            "notes": suggestions[:12],
        },
        "suggestions": suggestions[:20],
        "failed_items": failed_items,
        "warning_items": warning_items,
        "seo_after": seo_after,
        "internal_links": internal_links,
        "warnings": warnings,
    }
