"""Orchestration workflow chatbot: credit, xác nhận, chạy nền, tiến trình."""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.services.chatbot_command_parser import (
    INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
    WorkflowParseResult,
    build_workflow_reply,
)
from app.services.chatbot_workflow_runner import (
    STEP_EXTRACT_PLANNING,
    STEP_INSERT_IMAGES,
    STEP_INTERNAL_LINKS,
    STEP_KEYWORD_CLUSTERING,
    STEP_KEYWORD_RESEARCH,
    STEP_SAVE_HISTORY,
    STEP_SELECT_CLUSTER,
    STEP_SEO_REWRITE,
    STEP_SEO_SCORE_CHECK,
    STEP_WORD_COUNT_CHECK,
    STEP_WRITE_ARTICLE,
    build_workflow_run_reply,
    run_keyword_cluster_to_article_workflow,
    run_quick_keyword_article_workflow,
)
from app.services.chatbot_tab_registry import (
    INTENT_CONTENT_SEO_SCORE,
    INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
    INTENT_KEYWORD_RESEARCH,
    INTENT_KEYWORD_RESEARCH_CLUSTER,
    INTENT_QUICK_KEYWORD_ARTICLE,
    INTENT_TECHNICAL_DEEP_AUDIT,
    INTENT_TECHNICAL_QUICK_AUDIT,
    INTENT_TECHNICAL_SINGLE_URL,
    INTENT_URL_SEO_SCOREBOARD,
    consume_workflow_credits,
    tab_for_intent,
    validate_prepare_params,
)
from app.services.chatbot_write_planner import preview_write_planning
from app.services.chatbot_workflow_runners_extra import (
    build_simple_workflow_reply,
    run_content_seo_score_workflow,
    run_keyword_research_workflow,
    run_keyword_research_cluster_workflow,
    run_technical_deep_audit_workflow,
    run_technical_quick_audit_workflow,
    run_technical_single_url_workflow,
    run_url_seo_scoreboard_workflow,
)
from app.services.chatbot_workflow_credit import (
    CREDIT_STATUS_CANCELLED,
    CREDIT_STATUS_CHARGED,
    CREDIT_STATUS_COMPLETED,
    CREDIT_STATUS_PENDING,
    CREDIT_STATUS_REFUNDED,
    CREDIT_STATUS_RUNNING,
    InsufficientCreditError,
    create_credit_log,
    ensure_workflow_intent_supported,
    format_insufficient_credit_message,
    quote_workflow_credits,
    refund_workflow_credits,
    refund_workflow_credits_in_new_session,
    update_credit_log,
    update_credit_log_in_new_session,
)
from app.services.chatbot_workflow_store import (
    ChatbotWorkflowRecord,
    cancel_workflow as store_cancel_workflow,
    create_workflow_record,
    get_workflow_for_user,
    init_ui_progress,
    set_ui_progress,
    update_workflow,
    _LOCK as _WF_LOCK,
    _JOBS as _WF_JOBS,
)
from app.services.content_ai_image_rules import image_source_label, inline_image_count_for_word_count
from fastapi import HTTPException

from app.services.credits import get_available_balance

def _workflow_feature_codes(intent: str) -> list[str]:
    """Feature codes that must pass SaaS gate before billable workflow starts."""
    intent = str(intent or "").strip()
    if intent in (INTENT_KEYWORD_RESEARCH, INTENT_KEYWORD_RESEARCH_CLUSTER):
        codes = ["keyword_research"]
        if intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
            codes.append("keyword_cluster")
        return codes
    if intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
        return ["keyword_cluster", "content_ai_article"]
    if intent == INTENT_QUICK_KEYWORD_ARTICLE:
        return ["content_ai_article"]
    if intent in (INTENT_URL_SEO_SCOREBOARD, INTENT_CONTENT_SEO_SCORE):
        return ["seo_score"]
    if intent in (INTENT_TECHNICAL_QUICK_AUDIT, INTENT_TECHNICAL_DEEP_AUDIT, INTENT_TECHNICAL_SINGLE_URL):
        return ["technical_audit"]
    return []


def _enforce_workflow_saas_gate(db: Session, user_id: int, intent: str) -> None:
    from app.models.user import User
    from app.services.saas_gate import enforce_saas_access

    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Cần đăng nhập.")
    for code in _workflow_feature_codes(intent):
        enforce_saas_access(db, user, feature_code=code, quantity=1)


_LOG = logging.getLogger(__name__)

_GUEST_WORKFLOW_MSG = (
    "Workflow tự động (research → gom cụm → viết bài SEO) chỉ dành cho **tài khoản đăng nhập**. "
    "Bạn vẫn có thể hỏi FAQ / hỗ trợ bình thường qua chatbot."
)


def _parse_to_params(workflow: WorkflowParseResult) -> dict[str, Any]:
    workflow.sync_image_flags()
    return {
        "primary_keyword": workflow.primary_keyword,
        "word_count": workflow.word_count,
        "language": workflow.language,
        "tone": workflow.tone,
        "country": workflow.country,
        "article_type": workflow.article_type,
        "include_internal_links": bool(workflow.include_internal_links),
        "include_images": bool(workflow.include_images),
        "image_source": workflow.image_source,
        "target_website": str(workflow.target_website or ""),
    }


def build_credit_summary_text(
    credits: dict[str, int],
    balance: int,
    *,
    sufficient: bool,
    workflow: WorkflowParseResult | None = None,
) -> str:
    lines = [
        "Workflow **Research → Gom nhóm → Viết bài SEO**",
        "",
        "**Ước tính credit:**",
        f"- Viết bài AI: **{credits.get('content_ai', 0)}** credit",
        f"- Research keyword: **{credits.get('research', 0)}** credit",
        f"- Gom nhóm từ khóa: **{credits.get('clustering', 0)}** credit",
    ]
    if int(credits.get("internal_links") or 0) > 0:
        lines.append(f"- Internal link: **{credits.get('internal_links', 0)}** credit")
    if workflow and workflow.image_source:
        img_n = inline_image_count_for_word_count(workflow.word_count)
        lines.append(f"- Nguồn ảnh: **{image_source_label(workflow.image_source)}** ({img_n} ảnh inline)")
    if int(credits.get("images_google") or 0) > 0:
        lines.append(f"- Ảnh Google: **{credits.get('images_google', 0)}** credit")
    if int(credits.get("images_ai") or 0) > 0:
        lines.append(f"- Ảnh AI: **{credits.get('images_ai', 0)}** credit")
    elif int(credits.get("images") or 0) > 0 and not credits.get("images_google") and not credits.get("images_ai"):
        lines.append(f"- Hình ảnh: **{credits.get('images', 0)}** credit")
    lines.extend(
        [
            f"- **Tổng:** {credits.get('total', 0)} credit",
            "",
            f"Số dư hiện tại: **{balance}** credit",
        ]
    )
    if not sufficient:
        lines.extend(
            [
                "",
                format_insufficient_credit_message(int(credits.get("total") or 0), int(balance)),
            ]
        )
    else:
        lines.extend(["", "Bấm **Tiếp tục** để chạy workflow hoặc **Hủy** để bỏ qua."])
    return "\n".join(lines)


_WRITE_INTENTS = frozenset({INTENT_QUICK_KEYWORD_ARTICLE, INTENT_KEYWORD_CLUSTER_TO_ARTICLE})


def preview_workflow_outline(
    db: Session,
    *,
    user_id: int,
    intent: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Tạo preview outline (chưa trừ credit)."""
    clean = validate_prepare_params(intent, params)
    planning = preview_write_planning(intent, clean)
    quote = quote_workflow_credits(db, user_id, intent, clean)
    return {
        "intent": intent,
        "params": clean,
        "planning": planning,
        "credits": quote["credits"],
        "balance": quote["balance"],
        "sufficient": quote["sufficient"],
        "credit_required": quote["credit_required"],
        "credit_balance": quote["credit_balance"],
        "credit_estimate_message": quote["credit_estimate_message"],
        "insufficient_message": quote["insufficient_message"],
        "image_count_preview": inline_image_count_for_word_count(clean.get("word_count")),
    }


def prepare_workflow_from_params(
    db: Session,
    *,
    user_id: int,
    session_id: str,
    intent: str,
    params: dict[str, Any],
    planning_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tạo workflow pending_confirm từ form tab (không qua NLP chat)."""
    merged = dict(params or {})
    if planning_snapshot:
        merged["planning_snapshot"] = planning_snapshot
    _enforce_workflow_saas_gate(db, user_id, intent)
    clean = validate_prepare_params(intent, merged)
    quote = quote_workflow_credits(db, user_id, intent, clean)
    credits = quote["credits"]
    balance = quote["balance"]
    sufficient = quote["sufficient"]

    rec = create_workflow_record(
        user_id=user_id,
        session_id=session_id,
        intent=str(intent),
        params=clean,
        credits=credits,
        balance=balance,
        sufficient=sufficient,
    )

    tab_id = tab_for_intent(intent)
    return {
        "workflow_id": rec.workflow_id,
        "intent": rec.intent,
        "tab_id": tab_id,
        "phase": rec.phase,
        "params": clean,
        "credits": credits,
        "balance": balance,
        "sufficient": sufficient,
        "credit_required": quote["credit_required"],
        "credit_balance": quote["credit_balance"],
        "credit_estimate_message": quote["credit_estimate_message"],
        "insufficient_message": quote["insufficient_message"],
        "image_count_preview": inline_image_count_for_word_count(clean.get("word_count"))
        if intent in _WRITE_INTENTS
        else None,
        "planning": clean.get("planning_snapshot"),
    }


def prepare_workflow_confirmation(
    db: Session,
    *,
    user_id: int,
    session_id: str,
    workflow: WorkflowParseResult,
) -> tuple[str, dict[str, Any]]:
    intent_key = str(workflow.intent or INTENT_KEYWORD_CLUSTER_TO_ARTICLE)
    params = _parse_to_params(workflow)
    quote = quote_workflow_credits(db, user_id, intent_key, params)
    credits = quote["credits"]
    balance = quote["balance"]
    sufficient = quote["sufficient"]

    rec = create_workflow_record(
        user_id=user_id,
        session_id=session_id,
        intent=str(workflow.intent or INTENT_KEYWORD_CLUSTER_TO_ARTICLE),
        params=_parse_to_params(workflow),
        credits=credits,
        balance=balance,
        sufficient=sufficient,
    )

    if not sufficient:
        reply = build_credit_summary_text(credits, balance, sufficient=False, workflow=workflow)
        payload = {
            **workflow.to_dict(),
            **rec.to_public_dict(),
            "phase": "denied",
            "credit_required": quote["credit_required"],
            "credit_balance": quote["credit_balance"],
            "credit_estimate_message": quote["credit_estimate_message"],
            "insufficient_message": quote["insufficient_message"],
        }
        return reply, payload

    pk = str(workflow.primary_keyword or "").strip()
    img_n = inline_image_count_for_word_count(workflow.word_count)
    extras: list[str] = []
    if workflow.include_internal_links:
        extras.append("internal link")
    if workflow.image_source:
        extras.append(image_source_label(workflow.image_source))
    reply_lines = [
        f"Đã nhận lệnh workflow với từ khóa **{pk}**.",
        f"- **Số từ:** {workflow.word_count}",
    ]
    if workflow.image_source and workflow.image_source != "none":
        reply_lines.append(f"- **Ảnh dự kiến:** {img_n} ảnh inline")
    if extras:
        reply_lines.append(f"- **Tính năng thêm:** {', '.join(extras)}")
    reply_lines.extend(
        ["", build_credit_summary_text(credits, balance, sufficient=True, workflow=workflow)]
    )
    payload = {
        **workflow.to_dict(),
        **rec.to_public_dict(),
        "phase": "pending_confirm",
        "image_count_preview": img_n,
        "credit_required": quote["credit_required"],
        "credit_balance": quote["credit_balance"],
        "credit_estimate_message": quote["credit_estimate_message"],
        "insufficient_message": quote["insufficient_message"],
        "actions": [
            {"type": "confirm", "label": "Tiếp tục", "workflow_id": rec.workflow_id},
            {"type": "cancel", "label": "Hủy", "workflow_id": rec.workflow_id},
        ],
    }
    return "\n".join(reply_lines), payload


def handle_workflow_intent(
    db: Session,
    *,
    user_id: int | None,
    session_id: str,
    workflow: WorkflowParseResult,
) -> tuple[str, dict[str, Any]]:
    if not user_id and workflow.is_workflow:
        return (
            _GUEST_WORKFLOW_MSG + "\n\n" + build_workflow_reply(workflow),
            {**workflow.to_dict(), "phase": "guest_denied"},
        )

    if workflow.needs_keyword or workflow.needs_word_count or workflow.needs_image_source:
        reply = build_workflow_reply(workflow)
        payload = workflow.to_dict()
        if workflow.needs_word_count:
            payload["phase"] = "pending_word_count"
            payload["word_count_options"] = [1000, 1500, 2000]
        elif workflow.needs_image_source or workflow.awaiting_image_source:
            payload["phase"] = "pending_image_source"
            payload["image_count_preview"] = inline_image_count_for_word_count(workflow.word_count)
        return reply, payload

    return prepare_workflow_confirmation(
        db,
        user_id=int(user_id),
        session_id=session_id,
        workflow=workflow,
    )


def _map_internal_to_ui(internal_step_id: str, status: str, *, intent: str = "") -> list[tuple[str, str]]:
    if intent in _WRITE_INTENTS:
        if internal_step_id == STEP_EXTRACT_PLANNING:
            return [("outline", status)]
        if internal_step_id == STEP_WRITE_ARTICLE:
            return [("writing", status)]
        if internal_step_id == STEP_WORD_COUNT_CHECK:
            return [("word_count", status)]
        if internal_step_id == STEP_SEO_SCORE_CHECK:
            return [("seo_score", status)]
        if internal_step_id == STEP_SEO_REWRITE:
            return [("seo_rewrite", status)]
        if internal_step_id == STEP_INSERT_IMAGES:
            return [("images", status)]
        if internal_step_id in (STEP_SAVE_HISTORY, "complete"):
            return [("complete", status)]
        return []

    if internal_step_id == STEP_KEYWORD_RESEARCH:
        return [("research", status)]
    if internal_step_id in (STEP_KEYWORD_CLUSTERING, STEP_SELECT_CLUSTER):
        return [("clustering", status)]
    if internal_step_id == STEP_EXTRACT_PLANNING:
        return [("outline", status)]
    if internal_step_id == STEP_WRITE_ARTICLE:
        return [("writing", status)]
    if internal_step_id == STEP_INTERNAL_LINKS:
        return [("internal_links", status)]
    if internal_step_id == STEP_INSERT_IMAGES:
        return [("images", status)]
    if internal_step_id == STEP_SAVE_HISTORY:
        return [("saving", status)]
    if internal_step_id in ("analyze", "crawl"):
        return [(internal_step_id, status)]
    if internal_step_id == "complete":
        return [("complete", status)]
    return []


_UI_ORDER = [
    "research",
    "clustering",
    "outline",
    "writing",
    "internal_links",
    "images",
    "saving",
    "complete",
]


def _apply_ui_step(workflow_id: str, internal_step_id: str, status: str, message: str = "", *, intent: str = "") -> None:
    label = message.strip() or None
    mapped = _map_internal_to_ui(internal_step_id, status, intent=intent)
    targets = mapped if mapped else [(internal_step_id, status)]
    for ui_id, ui_status in targets:
        set_ui_progress(workflow_id, ui_id, ui_status, label=label if ui_id == internal_step_id or len(targets) == 1 else None)
    if status != "running":
        return
    active_id = targets[0][0] if targets else internal_step_id
    with _WF_LOCK:
        raw = _WF_JOBS.get(workflow_id)
        if not raw:
            return
        progress = [dict(x) for x in (raw.get("progress") or [])]
        found = False
        for item in progress:
            if item.get("id") == active_id:
                found = True
                item["status"] = "running"
                if label:
                    item["label"] = label
                continue
            if not found and item.get("status") not in ("done", "failed"):
                item["status"] = "done"
        raw["progress"] = progress


def _refund_failed_workflow(*, workflow_id: str, user_id: int, error_reason: str) -> int:
    """Hoàn credit đã trừ khi workflow thất bại (lỗi hệ thống, thiếu số từ, v.v.)."""
    refunded = refund_workflow_credits_in_new_session(
        user_id=int(user_id),
        task_id=str(workflow_id),
        reason=str(error_reason or "workflow_failed")[:2000],
    )
    if refunded > 0:
        from app.db import SessionLocal
        from app.services.credits import get_available_balance

def _workflow_feature_codes(intent: str) -> list[str]:
    """Feature codes that must pass SaaS gate before billable workflow starts."""
    intent = str(intent or "").strip()
    if intent in (INTENT_KEYWORD_RESEARCH, INTENT_KEYWORD_RESEARCH_CLUSTER):
        codes = ["keyword_research"]
        if intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
            codes.append("keyword_cluster")
        return codes
    if intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
        return ["keyword_cluster", "content_ai_article"]
    if intent == INTENT_QUICK_KEYWORD_ARTICLE:
        return ["content_ai_article"]
    if intent in (INTENT_URL_SEO_SCOREBOARD, INTENT_CONTENT_SEO_SCORE):
        return ["seo_score"]
    if intent in (INTENT_TECHNICAL_QUICK_AUDIT, INTENT_TECHNICAL_DEEP_AUDIT, INTENT_TECHNICAL_SINGLE_URL):
        return ["technical_audit"]
    return []


def _enforce_workflow_saas_gate(db: Session, user_id: int, intent: str) -> None:
    from app.models.user import User
    from app.services.saas_gate import enforce_saas_access

    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Cần đăng nhập.")
    for code in _workflow_feature_codes(intent):
        enforce_saas_access(db, user, feature_code=code, quantity=1)


        db = SessionLocal()
        try:
            update_workflow(workflow_id, balance=get_available_balance(db, int(user_id)))
        finally:
            db.close()
    return refunded


def _run_workflow_thread(
    workflow_id: str,
    user_id: int,
    params: dict[str, Any],
    credits_used: int,
    intent: str,
) -> None:
    def on_internal_step(step) -> None:
        _apply_ui_step(
            workflow_id,
            step.id,
            step.status,
            message=str(getattr(step, "message", "") or ""),
            intent=intent,
        )

    try:
        intent = str(intent or "").strip()
        update_credit_log_in_new_session(task_id=workflow_id, status=CREDIT_STATUS_RUNNING)
        if intent == INTENT_QUICK_KEYWORD_ARTICLE:
            run = run_quick_keyword_article_workflow(
                user_id=user_id,
                planning_snapshot=dict(params.get("planning_snapshot") or {}),
                word_count=params.get("word_count"),
                target_website=str(params.get("website_url") or params.get("target_website") or ""),
                include_images=bool(params.get("include_images")),
                image_source=params.get("image_source"),
                credits_used=credits_used,
                workflow_id=workflow_id,
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_KEYWORD_CLUSTER_TO_ARTICLE:
            run = run_keyword_cluster_to_article_workflow(
                user_id=user_id,
                primary_keyword=str(params.get("primary_keyword") or ""),
                word_count=params.get("word_count"),
                language=params.get("language"),
                tone=params.get("tone"),
                country=params.get("country"),
                article_type=params.get("article_type"),
                target_website=str(params.get("website_url") or params.get("target_website") or ""),
                include_internal_links=bool(params.get("include_internal_links")),
                include_images=bool(params.get("include_images")),
                image_source=params.get("image_source"),
                credits_used=credits_used,
                planning_snapshot=params.get("planning_snapshot"),
                workflow_id=workflow_id,
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_KEYWORD_RESEARCH:
            run = run_keyword_research_workflow(
                user_id=user_id,
                seed_keyword=str(params.get("seed_keyword") or ""),
                language=str(params.get("language") or "vi"),
                country=str(params.get("country") or "VN"),
                max_keywords=int(params.get("max_keywords") or 100),
                include_clustering=False,
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
            run = run_keyword_research_cluster_workflow(
                user_id=user_id,
                seed_keyword=str(params.get("seed_keyword") or ""),
                language=str(params.get("language") or "vi"),
                country=str(params.get("country") or "VN"),
                max_keywords=int(params.get("max_keywords") or 100),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_URL_SEO_SCOREBOARD:
            run = run_url_seo_scoreboard_workflow(
                user_id=user_id,
                url=str(params.get("url") or ""),
                keyword=str(params.get("keyword") or params.get("primary_keyword") or ""),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_CONTENT_SEO_SCORE:
            run = run_content_seo_score_workflow(
                user_id=user_id,
                content_html=str(params.get("content_html") or ""),
                primary_keyword=str(params.get("primary_keyword") or ""),
                title=str(params.get("title") or ""),
                meta_description=str(params.get("meta_description") or ""),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_TECHNICAL_QUICK_AUDIT:
            run = run_technical_quick_audit_workflow(
                user_id=user_id,
                url=str(params.get("url") or ""),
                max_pages=int(params.get("max_pages") or 10),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_TECHNICAL_DEEP_AUDIT:
            run = run_technical_deep_audit_workflow(
                user_id=user_id,
                url=str(params.get("url") or ""),
                max_pages=int(params.get("max_pages") or 50),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        elif intent == INTENT_TECHNICAL_SINGLE_URL:
            run = run_technical_single_url_workflow(
                user_id=user_id,
                url=str(params.get("url") or ""),
                on_step=on_internal_step,
            )
            run_dict = run.to_dict()
        else:
            err = f"Intent không hỗ trợ: {intent}"
            update_workflow(workflow_id, phase="failed", error=err)
            _refund_failed_workflow(workflow_id=workflow_id, user_id=user_id, error_reason=err)
            return

        if run.status == "completed":
            _apply_ui_step(workflow_id, "complete", "done", intent=intent)
            rec = get_workflow_for_user(workflow_id, user_id)
            progress = rec.progress if rec else init_ui_progress(intent)
            update_workflow(
                workflow_id,
                phase="completed",
                run=run_dict,
                error=None,
                progress=progress,
            )
            update_credit_log_in_new_session(task_id=workflow_id, status=CREDIT_STATUS_COMPLETED)
        else:
            err = run.error or "Workflow thất bại."
            update_workflow(
                workflow_id,
                phase="failed",
                run=run_dict,
                error=err,
            )
            _refund_failed_workflow(workflow_id=workflow_id, user_id=user_id, error_reason=str(err))
    except Exception as exc:
        err = str(exc)[:500]
        _LOG.exception("chatbot workflow thread failed wf=%s reason=%s", workflow_id, err)
        update_workflow(workflow_id, phase="failed", error=err)
        _refund_failed_workflow(workflow_id=workflow_id, user_id=user_id, error_reason=err)


def start_workflow(
    db: Session,
    *,
    user_id: int,
    workflow_id: str,
) -> ChatbotWorkflowRecord:
    rec = get_workflow_for_user(workflow_id, user_id)
    if not rec:
        raise PermissionError("Workflow không tồn tại.")
    if rec.phase == "cancelled":
        raise ValueError("Workflow đã bị hủy.")
    if rec.phase in ("running", "completed", "failed"):
        return rec

    params = dict(rec.params)
    intent = str(rec.intent or "")
    quote = quote_workflow_credits(db, user_id, intent, params)

    if rec.phase == "denied" or not quote["sufficient"]:
        update_workflow(
            workflow_id,
            phase="denied",
            sufficient=False,
            balance=quote["credit_balance"],
        )
        raise InsufficientCreditError(
            required=quote["credit_required"],
            balance=quote["credit_balance"],
        )

    ensure_workflow_intent_supported(intent)
    _enforce_workflow_saas_gate(db, user_id, intent)

    total = int(quote["credit_required"] or 0)
    create_credit_log(
        db,
        user_id=user_id,
        workflow=intent,
        task_id=workflow_id,
        credit_used=total,
        status=CREDIT_STATUS_PENDING,
    )

    try:
        charged = consume_workflow_credits(
            db,
            user_id=user_id,
            intent=intent,
            params=params,
            workflow_id=workflow_id,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        balance = int(detail.get("balance", quote["credit_balance"]))
        required = int(detail.get("required", total))
        update_credit_log(
            db,
            task_id=workflow_id,
            status=CREDIT_STATUS_CANCELLED,
            credit_used=0,
            error_reason=str(detail.get("message") or exc.detail)[:2000],
        )
        update_workflow(workflow_id, phase="denied", sufficient=False, balance=balance)
        db.commit()
        raise InsufficientCreditError(required=required, balance=balance) from exc

    credits_used = int(charged.get("total") or 0)
    update_credit_log(
        db,
        task_id=workflow_id,
        status=CREDIT_STATUS_CHARGED,
        credit_used=credits_used,
    )
    db.commit()

    progress = init_ui_progress(intent)
    if intent in _WRITE_INTENTS:
        for item in progress:
            if item.get("id") in ("outline", "credits"):
                item["status"] = "done"

    update_workflow(
        workflow_id,
        phase="running",
        progress=progress,
        balance=get_available_balance(db, user_id),
        error=None,
        credits=charged,
    )

    thread = threading.Thread(
        target=_run_workflow_thread,
        args=(workflow_id, user_id, params, credits_used, intent),
        daemon=True,
        name=f"chatbot-wf-{workflow_id[:12]}",
    )
    thread.start()
    updated = get_workflow_for_user(workflow_id, user_id)
    if not updated:
        raise PermissionError("Workflow không tồn tại.")
    return updated


def get_workflow_status(user_id: int, workflow_id: str) -> dict[str, Any]:
    rec = get_workflow_for_user(workflow_id, user_id)
    if not rec:
        raise PermissionError("Workflow không tồn tại.")
    return rec.to_public_dict(include_run=False)


def get_workflow_result(user_id: int, workflow_id: str) -> dict[str, Any]:
    rec = get_workflow_for_user(workflow_id, user_id)
    if not rec:
        raise PermissionError("Workflow không tồn tại.")
    if rec.phase not in ("completed", "failed"):
        return {
            **rec.to_public_dict(include_run=False),
            "ready": False,
        }
    payload = rec.to_public_dict(include_run=True)
    payload["ready"] = True
    if rec.run:
        payload["reply"] = build_workflow_run_reply_from_dict(rec.run)
        payload["stats"] = (rec.run or {}).get("stats")
        art = (rec.run or {}).get("article") or {}
        payload["article_id"] = art.get("article_id") or art.get("project_id")
        for act in (rec.run or {}).get("actions") or []:
            if act.get("type") == "load_editor" and act.get("article_id"):
                payload["load_editor_article_id"] = act.get("article_id")
        run_result = (rec.run or {}).get("result") or {}
        if run_result.get("seo_report"):
            payload["seo_report"] = run_result.get("seo_report")
        if run_result.get("technical_report"):
            payload["technical_report"] = run_result.get("technical_report")
        if run_result.get("research_report"):
            payload["research_report"] = run_result.get("research_report")
    return payload


def build_workflow_run_reply_from_dict(run: dict[str, Any]) -> str:
    intent = str(run.get("intent") or "")
    if intent in (
        INTENT_KEYWORD_RESEARCH,
        INTENT_KEYWORD_RESEARCH_CLUSTER,
        INTENT_URL_SEO_SCOREBOARD,
        INTENT_CONTENT_SEO_SCORE,
        INTENT_TECHNICAL_QUICK_AUDIT,
        INTENT_TECHNICAL_DEEP_AUDIT,
        INTENT_TECHNICAL_SINGLE_URL,
    ):
        from app.services.chatbot_workflow_runners_extra import SimpleWorkflowResult, SimpleWorkflowStep

        steps = [SimpleWorkflowStep(**s) for s in (run.get("steps") or [])]
        obj = SimpleWorkflowResult(
            intent=intent,
            status=str(run.get("status") or ""),
            steps=steps,
            stats=run.get("stats"),
            result=run.get("result"),
            actions=list(run.get("actions") or []),
            error=run.get("error"),
        )
        return build_simple_workflow_reply(obj)

    from app.services.chatbot_workflow_runner import WorkflowRunResult, WorkflowStep

    steps = [WorkflowStep(**s) for s in (run.get("steps") or [])]
    obj = WorkflowRunResult(
        intent=intent,
        status=str(run.get("status") or ""),
        steps=steps,
        primary_keyword=run.get("primary_keyword"),
        cluster=run.get("cluster"),
        planning=run.get("planning"),
        article=run.get("article"),
        actions=list(run.get("actions") or []),
        stats=run.get("stats"),
        error=run.get("error"),
        error_code=run.get("error_code"),
    )
    return build_workflow_run_reply(obj)


def cancel_workflow(user_id: int, workflow_id: str) -> bool:
    return store_cancel_workflow(workflow_id, user_id)
