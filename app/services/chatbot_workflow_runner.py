"""Chạy workflow chatbot (MVP: keyword_cluster_to_article) qua service backend nội bộ."""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.services.chatbot_command_parser import INTENT_KEYWORD_CLUSTER_TO_ARTICLE
from app.services.chatbot_tab_registry import INTENT_QUICK_KEYWORD_ARTICLE
from app.services.cluster_planning_output import suggested_content_type
from app.services.content_ai_bulk_runner import write_content_ai_article
from app.services.content_ai_project_store import get_content_ai_project
from app.services.content_draft_builder import suggest_content_ai_field
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_research_pipeline import build_keyword_research_api_response

_LOG = logging.getLogger(__name__)


def _chatbot_defer_images() -> bool:
    return os.getenv("CONTENT_AI_CHATBOT_DEFER_IMAGES", "1").strip().lower() not in {"0", "false", "no"}

StepStatus = str  # pending | running | done | failed

STEP_KEYWORD_RESEARCH = "keyword_research"
STEP_KEYWORD_CLUSTERING = "keyword_clustering"
STEP_SELECT_CLUSTER = "select_cluster"
STEP_EXTRACT_PLANNING = "extract_planning"
STEP_WRITE_ARTICLE = "write_article"
STEP_WORD_COUNT_CHECK = "word_count_check"
STEP_SEO_SCORE_CHECK = "seo_score_check"
STEP_SEO_REWRITE = "seo_rewrite"
STEP_INTERNAL_LINKS = "internal_links"
STEP_INSERT_IMAGES = "insert_images"
STEP_SAVE_HISTORY = "save_history"

_STEP_DEFS: tuple[tuple[str, str], ...] = (
    (STEP_KEYWORD_RESEARCH, "Research từ khóa"),
    (STEP_KEYWORD_CLUSTERING, "Gom nhóm từ khóa"),
    (STEP_SELECT_CLUSTER, "Chọn cụm keyword"),
    (STEP_EXTRACT_PLANNING, "Tạo outline theo SEO Score"),
    (STEP_WRITE_ARTICLE, "Viết bài chuẩn SEO"),
    (STEP_WORD_COUNT_CHECK, "Kiểm tra số từ"),
    (STEP_SEO_SCORE_CHECK, "Chấm 30 yếu tố SEO Score"),
    (STEP_SEO_REWRITE, "Tối ưu lại bài viết"),
    (STEP_INTERNAL_LINKS, "Chèn internal link"),
    (STEP_INSERT_IMAGES, "Chèn hình ảnh"),
    (STEP_SAVE_HISTORY, "Lưu bài viết"),
)

_USER_ERRORS: dict[str, str] = {
    "seed_keyword_required": "Thiếu từ khóa chính để chạy workflow.",
    "no_keywords": "Không tìm thấy từ khóa liên quan. Thử từ khóa cụ thể hơn.",
    "no_clusters": "Không gom được cụm từ khóa. Thử lại với từ khóa ngắn gọn hơn.",
    "no_cluster_match": "Không chọn được cụm từ khóa phù hợp.",
    "write_failed": "Không viết được bài — vui lòng thử lại sau vài phút.",
    "save_failed": "Bài đã viết nhưng không lưu được vào Content AI.",
    "login_required": "Cần đăng nhập để chạy workflow tự động và lưu bài viết.",
}


@dataclass
class WorkflowStep:
    id: str
    label: str
    status: StepStatus = "pending"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowRunResult:
    intent: str = INTENT_KEYWORD_CLUSTER_TO_ARTICLE
    status: str = "pending"  # pending | running | completed | failed
    steps: list[WorkflowStep] = field(default_factory=list)
    primary_keyword: str | None = None
    cluster: dict[str, Any] | None = None
    planning: dict[str, Any] | None = None
    article: dict[str, Any] | None = None
    actions: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "primary_keyword": self.primary_keyword,
            "cluster": self.cluster,
            "planning": self.planning,
            "article": self.article,
            "actions": self.actions,
            "stats": self.stats,
            "error": self.error,
            "error_code": self.error_code,
        }


def _init_steps() -> list[WorkflowStep]:
    return [WorkflowStep(id=sid, label=label) for sid, label in _STEP_DEFS]


def _step_index(steps: list[WorkflowStep], step_id: str) -> int:
    for i, s in enumerate(steps):
        if s.id == step_id:
            return i
    return -1


def _set_step(
    steps: list[WorkflowStep],
    step_id: str,
    *,
    status: StepStatus,
    message: str = "",
) -> None:
    idx = _step_index(steps, step_id)
    if idx < 0:
        return
    steps[idx].status = status
    if message:
        steps[idx].message = message


def _fail(result: WorkflowRunResult, steps: list[WorkflowStep], step_id: str, code: str, detail: str = "") -> WorkflowRunResult:
    msg = _USER_ERRORS.get(code, detail or "Workflow thất bại.")
    if detail and code not in _USER_ERRORS:
        msg = detail
    _set_step(steps, step_id, status="failed", message=msg)
    result.status = "failed"
    result.error = msg
    result.error_code = code
    result.steps = steps
    return result


def _norm_country(country: str | None) -> str:
    c = str(country or "").strip().upper()
    mapping = {"VN": "vn", "US": "us", "SG": "sg", "TH": "th"}
    if c in mapping:
        return mapping[c]
    return str(country or "vn").strip().lower() or "vn"


def _norm_language(language: str | None) -> str:
    lang = str(language or "vi").strip().lower()
    return lang if lang in {"vi", "en"} else "vi"


def _chatbot_cluster_max() -> int:
    try:
        return max(20, min(200, int(os.getenv("CHATBOT_WORKFLOW_CLUSTER_MAX", "80"))))
    except (TypeError, ValueError):
        return 80


def _chatbot_cluster_mode() -> str:
    mode = (os.getenv("CHATBOT_WORKFLOW_CLUSTER_MODE", "tfidf") or "tfidf").strip().lower()
    return mode if mode in {"tfidf", "hybrid", "both"} else "tfidf"


def _chatbot_fetch_serp() -> bool:
    return (os.getenv("CHATBOT_WORKFLOW_FETCH_SERP", "0") or "0").strip().lower() in ("1", "true", "yes")


def _chatbot_bulk_fast() -> bool:
    return (os.getenv("CHATBOT_WORKFLOW_BULK_FAST", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def _row_volume(row: dict[str, Any]) -> int:
    sv = row.get("search_volume")
    if isinstance(sv, dict):
        return int(sv.get("avg_monthly") or sv.get("display_volume") or 0)
    try:
        return int(sv or 0)
    except (TypeError, ValueError):
        return 0


def _cluster_from_engine_item(c: dict[str, Any], idx: int, kw_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    members = [str(x.get("keyword") or "").strip() for x in (c.get("keywords") or []) if x.get("keyword")]
    members = list(dict.fromkeys(m for m in members if m))
    primary = str(c.get("main_keyword") or c.get("cluster_name") or (members[0] if members else "")).strip()
    if primary and primary.lower() not in {m.lower() for m in members}:
        members = [primary, *members]
    total_vol = sum(_row_volume(kw_map.get(m.lower(), {})) for m in members)
    return {
        "cluster_id": f"cluster_{idx + 1}",
        "primary_keyword": primary,
        "variations": members,
        "intent": str(c.get("intent") or "informational"),
        "cluster_size": len(members),
        "total_volume": total_vol,
        "score": float(c.get("score") or 0.0),
        "serp_overlap_score": float(c.get("serp_overlap_score") or 0.0),
        "suggested_content_type": str(c.get("suggested_content_type") or ""),
    }


def _pick_best_cluster(clusters: list[dict[str, Any]], seed: str) -> dict[str, Any] | None:
    if not clusters:
        return None
    seed_l = seed.strip().lower()
    scored = sorted(clusters, key=lambda c: float(c.get("score") or 0.0), reverse=True)

    for c in scored:
        pk = str(c.get("primary_keyword") or "").strip().lower()
        if pk == seed_l or seed_l in pk or pk in seed_l:
            return c

    for c in scored:
        vars_l = [str(v).strip().lower() for v in (c.get("variations") or []) if str(v).strip()]
        if seed_l in vars_l:
            return c
        for v in vars_l:
            if seed_l in v or v in seed_l:
                return c

    return scored[0]


def _build_outline(
    *,
    primary_keyword: str,
    secondary_keywords: list[str],
    intent: str,
    article_type: str | None,
) -> str:
    sec_str = ", ".join(secondary_keywords[:15])
    outline = suggest_content_ai_field(
        field="outline_content",
        primary_keyword=primary_keyword,
        secondary_keywords=sec_str,
    )
    outline = str(outline or "").strip()
    if outline:
        return outline
    lines = [f"# {primary_keyword}"]
    if intent:
        lines.append(f"Intent: {intent}")
    if article_type:
        lines.append(f"Loại bài: {article_type}")
    for kw in secondary_keywords[:8]:
        lines.append(f"## {kw}")
    return "\n".join(lines)


def _content_type_from_cluster(cluster: dict[str, Any], article_type: str | None) -> str:
    if article_type:
        return article_type
    suggested = str(cluster.get("suggested_content_type") or "").strip()
    if suggested:
        return suggested
    return suggested_content_type(
        cluster_intent=str(cluster.get("intent") or "informational"),
        primary_serp_page_type=None,
    )


def _count_links_in_html(html: str) -> int:
    try:
        from bs4 import BeautifulSoup

        return len(BeautifulSoup(str(html or ""), "html.parser").find_all("a"))
    except Exception:
        return 0


def _count_images_in_html(html: str) -> int:
    try:
        from bs4 import BeautifulSoup

        return len(BeautifulSoup(str(html or ""), "html.parser").find_all("img"))
    except Exception:
        return 0


def _apply_internal_links_to_content(
    content_html: str,
    *,
    primary_keyword: str,
    secondary_keywords: list[str],
    target_website: str,
    title: str = "",
) -> tuple[str, int]:
    html = str(content_html or "").strip()
    if not html:
        return html, 0
    before = _count_links_in_html(html)
    site = str(target_website or "").strip()
    if site:
        try:
            from app.routers.pages import (
                _fetch_related_posts_wp,
                _inject_internal_links_contextual,
                _normalize_site_base,
            )

            base = _normalize_site_base(site)
            if base:
                posts = _fetch_related_posts_wp(base, primary_keyword, limit=18)
                if posts:
                    html = _inject_internal_links_contextual(html, posts, max_links=4)
        except Exception:
            _LOG.exception("chatbot workflow wp internal links failed")
    if _count_links_in_html(html) == before:
        try:
            from app.services.content_draft_builder import _inject_related_internal_links

            html = _inject_related_internal_links(
                html,
                title=title,
                primary_keyword=primary_keyword,
                target_website=site,
            )
        except Exception:
            _LOG.exception("chatbot workflow draft internal links failed")
    after = _count_links_in_html(html)
    return html, max(0, after - before)


def _apply_images_to_project(
    project_id: str,
    *,
    user_id: int,
    max_inline: int | None = None,
    word_count_target: int | None = None,
    image_source: str | None = None,
    on_status: Callable[[str], None] | None = None,
) -> tuple[int, dict[str, Any]]:
    from app.services.content_ai_content_images import auto_insert_images_to_project
    from app.services.content_ai_image_rules import inline_image_count_for_word_count, strategy_from_image_source

    strategy = strategy_from_image_source(image_source)
    if not strategy:
        return 0, {"inline_images_count": 0, "warning": "no_image_source"}

    slots = max_inline
    if slots is None and word_count_target:
        slots = inline_image_count_for_word_count(word_count_target)

    out = auto_insert_images_to_project(
        project_id,
        user_id=user_id,
        max_inline=slots,
        word_count_target=word_count_target,
        update_featured=True,
        require_featured=False,
        force=False,
        image_strategy_override=strategy,
        on_status=on_status,
    )
    inserted = int(out.get("inline_images_count") or 0)
    if inserted <= 0 and out.get("featured_image"):
        inserted = 1
    return inserted, out


def _enforce_chatbot_article_word_count(
    *,
    content_html: str,
    validated_wc: int,
    title: str,
    primary_keyword: str,
    target_website: str = "",
    outline: str = "",
    secondary_keywords: list[str] | None = None,
    user_id: int | None = None,
) -> str:
    """Repair/trim chatbot article HTML when deviation exceeds ±15% from validated target."""
    from app.services.content_ai_bulk_runner import ensure_article_content_word_count

    sec_str = ", ".join(str(x).strip() for x in (secondary_keywords or []) if str(x).strip())
    db = None
    user = None
    owns_gate_db = False
    if user_id and int(user_id) > 0:
        from app.services.content_ai_bulk_runner import _open_system_llm_db_user

        db, user = _open_system_llm_db_user(int(user_id))
        owns_gate_db = True
    try:
        return ensure_article_content_word_count(
            content_html=content_html,
            target_word_count=int(validated_wc),
            primary_keyword=primary_keyword,
            title=title,
            target_website=target_website,
            outline_content=outline,
            secondary_keywords=sec_str,
            use_system_llm=True,
            db=db,
            user=user,
            skip_llm_credit_check=True,
        )
    finally:
        if owns_gate_db and db is not None:
            db.close()


def _seo_writing_brief_from_planning(
    planning: dict[str, Any],
    *,
    pk: str,
    secondary: list[str],
    target_wc: int,
    target_website: str,
) -> str:
    brief = str(planning.get("seo_writing_brief") or "").strip()
    if brief:
        return brief
    from app.services.content_ai_publish_checklist import build_seo_score_writing_brief

    return build_seo_score_writing_brief(
        primary_keyword=pk,
        target_word_count=int(target_wc),
        intent=str(planning.get("intent") or "informational"),
        target_website=target_website,
        secondary_keywords=secondary,
    )


def _write_and_finalize_article(
    *,
    user_id: int,
    result: WorkflowRunResult,
    steps: list[WorkflowStep],
    emit: Callable[[str, StepStatus, str], None],
    pk: str,
    secondary: list[str],
    outline: str,
    search_vol: int,
    content_type: str | None,
    target_wc: int,
    requested_wc: int | None = None,
    target_website: str,
    tone: str | None,
    include_internal_links: bool,
    include_images: bool,
    image_source: str | None,
    credits_used: int | None,
    planning: dict[str, Any],
    workflow_id: str = "",
) -> WorkflowRunResult:
    from app.services.content_ai_request_cache import reset_request_cache
    from app.services.content_ai_write_timing import (
        ContentAiWriteTimer,
        STEP_LLM,
        STEP_SAVE,
        bind_write_timer,
        mark_step,
    )

    reset_request_cache()
    timer = ContentAiWriteTimer(
        endpoint="chatbot_write_article",
        user_id=int(user_id),
    )
    bind_write_timer(timer)
    seo_brief = _seo_writing_brief_from_planning(
        planning,
        pk=pk,
        secondary=secondary,
        target_wc=target_wc,
        target_website=target_website,
    )
    emit(STEP_WRITE_ARTICLE, "running", "Đang viết bài chuẩn SEO…")
    mark_step(STEP_LLM)
    try:
        project_id = write_content_ai_article(
            user_id=int(user_id),
            primary_keyword=pk,
            target_website=target_website,
            target_word_count=target_wc,
            secondary_keywords=secondary,
            custom_outline=outline,
            custom_title=str(planning.get("title") or "").strip(),
            custom_description=str(planning.get("meta_description") or "").strip(),
            search_volume=search_vol,
            content_type=content_type,
            bulk_fast=_chatbot_bulk_fast(),
            skip_llm_credit_check=True,
            seo_writing_brief=seo_brief,
        )
    except Exception as exc:
        _LOG.exception("chatbot workflow write failed")
        detail = str(exc)
        if "CostControlBypassError" in type(exc).__name__ or "missing cost gate" in detail.lower():
            detail = "Hệ thống chưa sẵn sàng gọi LLM — vui lòng thử lại."
        return _fail(result, steps, STEP_WRITE_ARTICLE, "write_failed", f"Không viết được bài: {detail}")

    emit(STEP_WRITE_ARTICLE, "done", "Đã tạo nội dung bài viết.")

    project = get_content_ai_project(project_id, user_id=int(user_id))
    if not project:
        return _fail(result, steps, STEP_WRITE_ARTICLE, "save_failed")

    content_html = str(project.get("content") or "").strip()
    title = str(project.get("title") or pk).strip()
    website_context = planning.get("website_context") if isinstance(planning.get("website_context"), dict) else None
    if website_context and content_html:
        from app.services.chatbot_website_context import (
            rewrite_content_for_website_alignment,
            validate_content_alignment,
        )

        aligned, misalign_reason = validate_content_alignment(
            content_html,
            website_context=website_context,
            primary_keyword=pk,
        )
        if not aligned:
            emit(STEP_WRITE_ARTICLE, "running", f"{misalign_reason} — đang viết lại theo website…")
            try:
                content_html = rewrite_content_for_website_alignment(
                    content_html=content_html,
                    primary_keyword=pk,
                    title=title,
                    outline=outline,
                    target_website=target_website,
                    website_context=website_context,
                    target_word_count=target_wc,
                )
                from app.services.content_ai_project_store import update_content_ai_project_fields

                update_content_ai_project_fields(
                    project_id,
                    {"content": content_html},
                    user_id=int(user_id),
                )
                realigned, reason2 = validate_content_alignment(
                    content_html,
                    website_context=website_context,
                    primary_keyword=pk,
                )
                if not realigned:
                    return _fail(
                        result,
                        steps,
                        STEP_WRITE_ARTICLE,
                        "industry_mismatch",
                        reason2 or "Nội dung vẫn lệch ngành so với website.",
                    )
                emit(STEP_WRITE_ARTICLE, "done", "Đã viết lại nội dung đúng ngành website.")
            except Exception as exc:
                _LOG.exception("chatbot workflow realign failed")
                return _fail(
                    result,
                    steps,
                    STEP_WRITE_ARTICLE,
                    "industry_mismatch",
                    f"Nội dung lệch ngành: {misalign_reason}",
                )

    links_inserted = 0

    from app.services.content_ai_word_count_policy import (
        needs_word_count_repair,
        needs_word_count_trim,
        word_count_from_html,
    )
    from app.services.content_ai_bulk_runner import _is_stub_content_html

    pre_enforce_actual = word_count_from_html(content_html)
    emit(STEP_WORD_COUNT_CHECK, "running", "Đang kiểm tra số từ…")
    if (
        _is_stub_content_html(content_html)
        or needs_word_count_repair(pre_enforce_actual, target_wc)
        or needs_word_count_trim(pre_enforce_actual, target_wc)
    ):
        emit(STEP_WORD_COUNT_CHECK, "running", f"Đang chỉnh số từ về ~{target_wc}…")
        try:
            content_html = _enforce_chatbot_article_word_count(
                content_html=content_html,
                validated_wc=target_wc,
                title=title,
                primary_keyword=pk,
                target_website=target_website,
                outline=outline,
                secondary_keywords=secondary,
                user_id=int(user_id),
            )
        except Exception as exc:
            _LOG.exception("chatbot workflow word count enforce failed")
            from app.services.content_ai_project_store import delete_content_ai_project

            delete_content_ai_project(project_id, user_id=int(user_id))
            return _fail(
                result,
                steps,
                STEP_WORD_COUNT_CHECK,
                "word_count_failed",
                str(exc)[:500],
            )
        from app.services.content_ai_project_store import update_content_ai_project_fields

        update_content_ai_project_fields(
            project_id,
            {
                "content": content_html,
                "target_word_count": int(target_wc),
                "validated_word_count": int(target_wc),
            },
            user_id=int(user_id),
        )
        emit(STEP_WORD_COUNT_CHECK, "done", "Đã chỉnh số từ theo mục tiêu.")
    else:
        emit(STEP_WORD_COUNT_CHECK, "done", f"~{pre_enforce_actual} từ (mục tiêu {target_wc}).")

    meta_description = str(project.get("meta_description") or planning.get("meta_description") or "").strip()
    slug = str(project.get("slug") or "").strip()

    emit(STEP_SEO_SCORE_CHECK, "running", "Đang chấm 30 yếu tố SEO Score…")
    from app.services.chatbot_seo_write_enforcer import enforce_chatbot_seo_article

    def _seo_progress(msg: str) -> None:
        if "tối ưu" in msg.lower():
            emit(STEP_SEO_REWRITE, "running", msg)
        elif "số từ" in msg.lower():
            emit(STEP_WORD_COUNT_CHECK, "running", msg)
        else:
            emit(STEP_SEO_SCORE_CHECK, "running", msg)

    seo_out = enforce_chatbot_seo_article(
        user_id=int(user_id),
        workflow_id=workflow_id,
        primary_keyword=pk,
        title=title,
        meta_description=meta_description,
        slug=slug,
        content_html=content_html,
        secondary_keywords=secondary,
        target_website=target_website,
        target_word_count=target_wc,
        on_progress=_seo_progress,
    )
    seo_summary = dict(seo_out.get("seo_summary") or {})
    rewrite_attempts = int(seo_out.get("rewrite_attempts") or 0)
    if rewrite_attempts > 0:
        emit(STEP_SEO_REWRITE, "done", f"Đã tối ưu {rewrite_attempts} lần theo SEO Score.")
    else:
        emit(STEP_SEO_REWRITE, "done", "Không cần tối ưu thêm.")

    if not seo_out.get("ok"):
        from app.services.content_ai_project_store import delete_content_ai_project

        delete_content_ai_project(project_id, user_id=int(user_id))
        emit(STEP_SEO_SCORE_CHECK, "failed", str(seo_out.get("error") or "SEO Score chưa đạt."))
        return _fail(
            result,
            steps,
            STEP_SEO_SCORE_CHECK,
            "seo_score_failed",
            str(seo_out.get("error") or "Bài viết chưa đạt 30 yếu tố SEO Score."),
        )

    title = str(seo_out.get("title") or title).strip()
    meta_description = str(seo_out.get("meta_description") or meta_description).strip()
    content_html = str(seo_out.get("content_html") or content_html).strip()
    slug = str(seo_out.get("slug") or slug).strip()
    from app.services.content_ai_image_guard import repair_content_html_images
    from app.services.content_ai_project_store import update_content_ai_project_fields

    content_html = repair_content_html_images(
        content_html,
        site_base=str(target_website or "").strip().rstrip("/"),
        source="chatbot_post_seo",
        probe_remote=False,
    )

    update_content_ai_project_fields(
        project_id,
        {
            "title": title,
            "meta_description": meta_description,
            "content": content_html,
            "slug": slug,
        },
        user_id=int(user_id),
    )
    passed = int(seo_summary.get("passed_factors") or 0)
    total = int(seo_summary.get("total_factors") or 30)
    emit(
        STEP_SEO_SCORE_CHECK,
        "done",
        f"SEO Score {seo_summary.get('seo_score', 0)}/100 — {passed}/{total} yếu tố đạt.",
    )

    emit(STEP_INTERNAL_LINKS, "running")
    if include_internal_links:
        try:
            content_html, links_inserted = _apply_internal_links_to_content(
                content_html,
                primary_keyword=pk,
                secondary_keywords=secondary,
                target_website=target_website,
                title=title,
            )
            if links_inserted > 0:
                from app.services.content_ai_project_store import update_content_ai_project_fields

                update_content_ai_project_fields(
                    project_id,
                    {"content": content_html},
                    user_id=int(user_id),
                )
            emit(STEP_INTERNAL_LINKS, "done", f"Đã chèn {links_inserted} internal link.")
        except Exception as exc:
            _LOG.exception("chatbot workflow internal links step failed")
            emit(STEP_INTERNAL_LINKS, "done", f"Bỏ qua internal link: {exc}")
    else:
        emit(STEP_INTERNAL_LINKS, "done", "Không yêu cầu internal link.")

    emit(STEP_INSERT_IMAGES, "running")
    use_images = include_images or bool(str(image_source or "").strip() not in ("", "none"))
    images_deferred = False
    if use_images:
        try:
            from app.services.content_ai_image_rules import inline_image_count_for_word_count

            max_inline = inline_image_count_for_word_count(target_wc)

            if _chatbot_defer_images():
                images_deferred = True

                def _bg_images() -> None:
                    try:
                        from app.services.content_ai_write_timing import STEP_IMAGES

                        mark_step(STEP_IMAGES, deferred=True, project_id=project_id[:12])
                        _apply_images_to_project(
                            project_id,
                            user_id=int(user_id),
                            max_inline=max_inline,
                            word_count_target=target_wc,
                            image_source=image_source,
                        )
                    except Exception:
                        _LOG.exception("chatbot deferred images failed")

                threading.Thread(
                    target=_bg_images,
                    daemon=True,
                    name=f"chatbot-img-{project_id[:8]}",
                ).start()
                emit(
                    STEP_INSERT_IMAGES,
                    "done",
                    "Đang xử lý ảnh nền — bài viết đã sẵn sàng.",
                )
            else:

                def _img_status(msg: str) -> None:
                    emit(STEP_INSERT_IMAGES, "running", msg)

                images_inserted, _img_out = _apply_images_to_project(
                    project_id,
                    user_id=int(user_id),
                    max_inline=max_inline,
                    word_count_target=target_wc,
                    image_source=image_source,
                    on_status=_img_status,
                )
                project = get_content_ai_project(project_id, user_id=int(user_id)) or project
                content_html = str(project.get("content") or content_html).strip()
                if images_inserted > 0:
                    emit(STEP_INSERT_IMAGES, "done", f"Đã chèn {images_inserted} ảnh (ALT/filename chuẩn SEO).")
                else:
                    emit(STEP_INSERT_IMAGES, "done", "Không lấy được ảnh phù hợp — bài viết vẫn hoàn tất.")
        except Exception:
            _LOG.exception("chatbot workflow images step failed")
            emit(STEP_INSERT_IMAGES, "done", "Không lấy được ảnh phù hợp — bài viết vẫn hoàn tất.")
    else:
        emit(STEP_INSERT_IMAGES, "done", "Không yêu cầu hình ảnh.")

    project = get_content_ai_project(project_id, user_id=int(user_id))
    if not project:
        return _fail(result, steps, STEP_SAVE_HISTORY, "save_failed")

    title = str(project.get("title") or pk).strip()
    content_html = str(project.get("content") or content_html).strip()
    if not content_html:
        return _fail(result, steps, STEP_SAVE_HISTORY, "save_failed")

    emit(STEP_SAVE_HISTORY, "running")
    mark_step(STEP_SAVE)

    from app.db import SessionLocal
    from app.models.user import User
    from app.services.content_ai_word_count_policy import (
        build_word_count_response,
        log_word_count_event,
    )

    client_wc = requested_wc if requested_wc is not None else target_wc
    wc_db = SessionLocal()
    try:
        bulk_user = wc_db.get(User, int(user_id))
        wc_meta = build_word_count_response(
            client_value=client_wc,
            user=bulk_user,
            db=wc_db,
            html=content_html,
        ) if bulk_user else {
            "requested_word_count": client_wc,
            "validated_word_count": target_wc,
            "actual_word_count": word_count_from_html(content_html),
            "word_count_status": "ok",
        }
        if bulk_user:
            log_word_count_event(
                user_id=int(user_id),
                endpoint="chatbot_write_article",
                requested=int(wc_meta.get("requested_word_count") or target_wc),
                validated=int(wc_meta.get("validated_word_count") or target_wc),
                actual=int(wc_meta.get("actual_word_count") or 0),
                status=str(wc_meta.get("word_count_status") or "ok"),
            )
    finally:
        wc_db.close()

    total_images = _count_images_in_html(content_html)
    result.stats = {
        "primary_keyword": pk,
        "secondary_keywords_count": len(secondary),
        "internal_links_inserted": links_inserted,
        "images_inserted": total_images if use_images and not images_deferred else 0,
        "images_deferred": images_deferred,
        "credits_used": int(credits_used or 0),
        "timing": timer.finish(),
        "seo_score": seo_summary.get("seo_score"),
        "passed_factors": seo_summary.get("passed_factors"),
        "total_factors": seo_summary.get("total_factors", 30),
        "failed_factors": seo_summary.get("failed_factors"),
        "rewrite_attempts": rewrite_attempts,
        "requested_word_count": seo_summary.get("requested_word_count") or wc_meta.get("requested_word_count"),
        "actual_word_count": seo_summary.get("actual_word_count") or wc_meta.get("actual_word_count"),
        "seo_summary": seo_summary,
    }
    result.article = {
        "article_id": project_id,
        "project_id": project_id,
        "title": title,
        "primary_keyword": pk,
        "word_count_target": wc_meta.get("validated_word_count", target_wc),
        "requested_word_count": wc_meta.get("requested_word_count", target_wc),
        "validated_word_count": wc_meta.get("validated_word_count", target_wc),
        "actual_word_count": seo_summary.get("actual_word_count") or wc_meta.get("actual_word_count"),
        "word_count_status": wc_meta.get("word_count_status"),
        "seo_score": seo_summary.get("seo_score"),
        "passed_factors": seo_summary.get("passed_factors"),
        "total_factors": seo_summary.get("total_factors", 30),
        "failed_factor_labels": seo_summary.get("failed_factor_labels") or [],
        "warning_factor_labels": seo_summary.get("warning_factor_labels") or [],
        "seo_summary": seo_summary,
    }
    open_url = f"/content-ai?article_id={project_id}"
    result.actions = [
        {
            "type": "open_url",
            "label": "Mở trong Content AI",
            "url": open_url,
        },
        {
            "type": "load_editor",
            "label": "Tải vào editor",
            "article_id": project_id,
        },
    ]
    emit(STEP_SAVE_HISTORY, "done", f"Đã lưu bài «{title[:80]}».")
    result.status = "completed"
    result.steps = steps
    return result


def run_quick_keyword_article_workflow(
    *,
    user_id: int | None,
    planning_snapshot: dict[str, Any],
    word_count: int | None = None,
    target_website: str = "",
    include_images: bool = False,
    image_source: str | None = None,
    credits_used: int | None = None,
    workflow_id: str = "",
    on_step: Callable[[WorkflowStep], None] | None = None,
) -> WorkflowRunResult:
    """Viết nhanh từ planning đã preview (không research)."""

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            idx = _step_index(steps, step_id)
            if idx >= 0:
                on_step(steps[idx])

    steps = _init_steps()
    plan = dict(planning_snapshot or {})
    pk = str(plan.get("primary_keyword") or "").strip()
    result = WorkflowRunResult(
        intent=INTENT_QUICK_KEYWORD_ARTICLE,
        primary_keyword=pk,
        steps=steps,
        status="running",
        planning=plan,
    )

    if not pk:
        return _fail(result, steps, STEP_WRITE_ARTICLE, "seed_keyword_required")
    if not user_id or int(user_id) <= 0:
        return _fail(result, steps, STEP_WRITE_ARTICLE, "login_required")

    from app.services.content_ai_word_count_policy import chatbot_validated_word_count

    target_wc = chatbot_validated_word_count(int(user_id), word_count)
    secondary = [str(v).strip() for v in (plan.get("secondary_keywords") or []) if str(v).strip()]
    outline = str(plan.get("outline") or "").strip()
    content_type = plan.get("content_type")
    search_vol = int(plan.get("search_volume") or 0)

    try:
        return _write_and_finalize_article(
            user_id=int(user_id),
            result=result,
            steps=steps,
            emit=_emit,
            pk=pk,
            secondary=secondary,
            outline=outline,
            search_vol=search_vol,
            content_type=content_type,
            target_wc=target_wc,
            requested_wc=word_count,
            target_website=target_website,
            tone=plan.get("tone"),
            include_internal_links=False,
            include_images=include_images,
            image_source=image_source,
            credits_used=credits_used,
            planning=plan,
            workflow_id=workflow_id,
        )
    except Exception as exc:
        _LOG.exception("chatbot quick write failed")
        running_id = next((s.id for s in steps if s.status == "running"), STEP_WRITE_ARTICLE)
        return _fail(result, steps, running_id, "workflow_error", f"Lỗi workflow: {exc}")


def run_keyword_cluster_to_article_workflow(
    *,
    user_id: int | None,
    primary_keyword: str,
    word_count: int | None = None,
    language: str | None = None,
    tone: str | None = None,
    country: str | None = None,
    article_type: str | None = None,
    target_website: str = "",
    include_internal_links: bool = False,
    include_images: bool = False,
    image_source: str | None = None,
    credits_used: int | None = None,
    planning_snapshot: dict[str, Any] | None = None,
    workflow_id: str = "",
    on_step: Callable[[WorkflowStep], None] | None = None,
) -> WorkflowRunResult:
    """Chạy workflow keyword → cluster → bài viết Content AI."""

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            idx = _step_index(steps, step_id)
            if idx >= 0:
                on_step(steps[idx])

    seed = re.sub(r"\s+", " ", str(primary_keyword or "").strip())
    steps = _init_steps()
    result = WorkflowRunResult(primary_keyword=seed, steps=steps, status="running")

    if not seed:
        return _fail(result, steps, STEP_KEYWORD_RESEARCH, "seed_keyword_required")

    if not user_id or int(user_id) <= 0:
        return _fail(result, steps, STEP_KEYWORD_RESEARCH, "login_required")

    from app.services.content_ai_word_count_policy import chatbot_validated_word_count

    loc_lang = _norm_language(language)
    loc_country = _norm_country(country)
    target_wc = chatbot_validated_word_count(int(user_id), word_count)

    research_payload: dict[str, Any] | None = None
    keywords_rows: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []
    snapshot = dict(planning_snapshot or {}) if planning_snapshot else {}

    try:
        if snapshot:
            pk = str(snapshot.get("primary_keyword") or seed).strip()
            secondary = [str(v).strip() for v in (snapshot.get("secondary_keywords") or []) if str(v).strip()]
            intent_kw = str(snapshot.get("intent") or "informational")
            outline = str(snapshot.get("outline") or "").strip()
            content_type = snapshot.get("content_type")
            search_vol = int(snapshot.get("search_volume") or 0)
            result.cluster = snapshot.get("cluster")
            result.planning = snapshot
            for sid in (
                STEP_KEYWORD_RESEARCH,
                STEP_KEYWORD_CLUSTERING,
                STEP_SELECT_CLUSTER,
                STEP_EXTRACT_PLANNING,
            ):
                _emit(sid, "done", "Đã hoàn tất ở bước preview.")
            return _write_and_finalize_article(
                user_id=int(user_id),
                result=result,
                steps=steps,
                emit=_emit,
                pk=pk,
                secondary=secondary,
                outline=outline,
                search_vol=search_vol,
                content_type=content_type,
                target_wc=target_wc,
                requested_wc=word_count,
                target_website=target_website,
                tone=tone or snapshot.get("tone"),
                include_internal_links=include_internal_links,
                include_images=include_images,
                image_source=image_source,
                credits_used=credits_used,
                planning=snapshot,
                workflow_id=workflow_id,
            )

        _emit(STEP_KEYWORD_RESEARCH, "running", "Đang mở rộng từ khóa…")

        research_payload = build_keyword_research_api_response(
            seed_keyword=seed,
            language=loc_lang,
            country=loc_country,
            cluster_mode=_chatbot_cluster_mode(),
            cluster_fetch_serp=_chatbot_fetch_serp(),
            cluster_max_keywords=_chatbot_cluster_max(),
        )
        meta_err = (research_payload.get("meta") or {}).get("error")
        if meta_err:
            return _fail(result, steps, STEP_KEYWORD_RESEARCH, str(meta_err))

        keywords_rows = list(research_payload.get("keywords") or [])
        if not keywords_rows:
            return _fail(result, steps, STEP_KEYWORD_RESEARCH, "no_keywords")

        kw_count = len(keywords_rows)
        _emit(
            STEP_KEYWORD_RESEARCH,
            "done",
            f"Đã tìm {kw_count} từ khóa liên quan.",
        )

        _emit(STEP_KEYWORD_CLUSTERING, "running", "Đang gom cụm…")

        clusters = list(research_payload.get("clusters") or [])
        if not clusters:
            kw_map = {str(r.get("keyword") or "").strip().lower(): r for r in keywords_rows if r.get("keyword")}
            records = [{"keyword": str(r.get("keyword") or "").strip(), "source": "chatbot_workflow"} for r in keywords_rows[: _chatbot_cluster_max()] if r.get("keyword")]
            raw_clusters = build_keyword_clusters(
                records,
                fetch_serp=_chatbot_fetch_serp(),
                serp_country=loc_country,
                serp_language=loc_lang,
            )
            clusters = [_cluster_from_engine_item(c, i, kw_map) for i, c in enumerate(raw_clusters)]

        if not clusters:
            return _fail(result, steps, STEP_KEYWORD_CLUSTERING, "no_clusters")

        _emit(
            STEP_KEYWORD_CLUSTERING,
            "done",
            f"Đã gom {len(clusters)} cụm từ khóa.",
        )

        _emit(STEP_SELECT_CLUSTER, "running")
        best = _pick_best_cluster(clusters, seed)
        if not best:
            return _fail(result, steps, STEP_SELECT_CLUSTER, "no_cluster_match")

        pk = str(best.get("primary_keyword") or seed).strip()
        variations = [str(v).strip() for v in (best.get("variations") or []) if str(v).strip()]
        secondary = [v for v in variations if v.lower() != pk.lower()][:12]
        intent = str(best.get("intent") or "informational")
        result.cluster = {
            "cluster_id": best.get("cluster_id"),
            "primary_keyword": pk,
            "secondary_keywords": secondary,
            "intent": intent,
            "total_volume": int(best.get("total_volume") or 0),
            "score": float(best.get("score") or 0.0),
        }
        _emit(
            STEP_SELECT_CLUSTER,
            "done",
            f"Chọn cụm «{pk}» ({len(secondary)} keyword phụ).",
        )

        _emit(STEP_EXTRACT_PLANNING, "running")
        content_type = _content_type_from_cluster(best, article_type)
        outline = _build_outline(
            primary_keyword=pk,
            secondary_keywords=secondary,
            intent=intent,
            article_type=article_type,
        )
        search_vol = int(best.get("total_volume") or 0)
        result.planning = {
            "primary_keyword": pk,
            "secondary_keywords": secondary,
            "intent": intent,
            "outline": outline,
            "content_type": content_type,
            "search_volume": search_vol,
            "language": loc_lang,
            "tone": tone,
            "country": loc_country,
            "title": suggest_content_ai_field(field="title", primary_keyword=pk),
            "meta_description": suggest_content_ai_field(field="meta_description", primary_keyword=pk),
        }
        _emit(STEP_EXTRACT_PLANNING, "done", "Đã lập dàn ý và keyword phụ.")

        return _write_and_finalize_article(
            user_id=int(user_id),
            result=result,
            steps=steps,
            emit=_emit,
            pk=pk,
            secondary=secondary,
            outline=outline,
            search_vol=search_vol,
            content_type=content_type,
            target_wc=target_wc,
            requested_wc=word_count,
            target_website=target_website,
            tone=tone,
            include_internal_links=include_internal_links,
            include_images=include_images,
            image_source=image_source,
            credits_used=credits_used,
            planning=result.planning,
            workflow_id=workflow_id,
        )

    except Exception as exc:
        _LOG.exception("chatbot workflow failed")
        running_id = next((s.id for s in steps if s.status == "running"), STEP_KEYWORD_RESEARCH)
        return _fail(result, steps, running_id, "workflow_error", f"Lỗi workflow: {exc}")


def build_workflow_run_reply(run: WorkflowRunResult) -> str:
    """Tạo phản hồi chatbot từ kết quả workflow (plain text + link path)."""
    if run.status == "failed":
        lines = [
            "Workflow **gom nhóm từ khóa → viết bài SEO** không hoàn tất.",
            "",
            f"**Lỗi:** {run.error or 'Không xác định'}",
            "",
            "**Tiến trình:**",
        ]
        for s in run.steps:
            icon = {"done": "✓", "failed": "✗", "running": "…", "pending": "○"}.get(s.status, "·")
            msg = f" — {s.message}" if s.message else ""
            lines.append(f"{icon} {s.label}{msg}")
        lines.append("")
        lines.append("Bạn có thể thử lại với từ khóa cụ thể hơn, hoặc mở thủ công: /keywords/tools/clustering và /content-ai")
        lines.append("")
        lines.append("_(workflow: keyword_cluster_to_article)_")
        return "\n".join(lines)

    if run.status != "completed":
        lines = ["Workflow đang xử lý…"]
        for s in run.steps:
            if s.status in ("running", "done"):
                lines.append(f"- {s.label}: {s.message or s.status}")
        return "\n".join(lines)

    art = run.article or {}
    plan = run.planning or {}
    stats = run.stats or {}
    seo_summary = stats.get("seo_summary") or art.get("seo_summary") or {}
    lines = [
        "Workflow **Research → Gom nhóm → Viết bài SEO** đã hoàn tất.",
        "",
        "**Thống kê:**",
        f"- **Keyword chính:** {stats.get('primary_keyword') or plan.get('primary_keyword') or run.primary_keyword}",
        f"- **Số keyword phụ:** {stats.get('secondary_keywords_count', len(plan.get('secondary_keywords') or []))}",
    ]
    from app.services.chatbot_seo_write_enforcer import format_chatbot_seo_reply_lines

    lines.extend(format_chatbot_seo_reply_lines(seo_summary))
    lines.extend(
        [
            f"- **Internal link đã chèn:** {stats.get('internal_links_inserted', 0)}",
            f"- **Ảnh đã chèn:** {stats.get('images_inserted', 0)}",
            f"- **Credit đã dùng:** {stats.get('credits_used', 0)}",
            "",
            f"- **Tiêu đề bài:** {art.get('title') or '—'}",
            "",
            "**Tiến trình:**",
        ]
    )
    for s in run.steps:
        if s.status == "done":
            msg = f" — {s.message}" if s.message else ""
            lines.append(f"✓ {s.label}{msg}")

    open_url = "/content-ai"
    for act in run.actions:
        if act.get("type") == "open_url" and act.get("url"):
            open_url = str(act["url"])
            break

    lines.extend(
        [
            "",
            f"**Mở trong Content AI:** {open_url}",
            f"(Article ID: `{art.get('article_id') or art.get('project_id') or '—'}`)",
            "",
            "_(workflow: keyword_cluster_to_article)_",
        ]
    )
    return "\n".join(lines)
