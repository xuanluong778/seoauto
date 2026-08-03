"""Content Auto Update — WordPress REST + AI SEO refresh."""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.cau_ai_fix_entitlement import (
    assert_cau_ai_fix_entitlement,
    resolve_cau_ai_plan_slug,
)
from app.services.content_auto_update_entitlement import (
    build_cau_quota_snapshot,
    assert_cau_feature,
    record_cau_usage,
)
from app.services.cau_modal_content_writer import validate_rewrite_modal_brief
from app.services.cau_modal_update_guard import pick_wp_modified
from app.services.cau_seo_analyzer import evaluate_cau_modal_seo
from app.services.credits import cost_content_ai_article
from app.services.content_auto_update_scan_cache import (
    get_scan_cache,
    priority_from_score,
    save_scan_cache,
    score_level_from_score,
    upsert_post_score,
)
from app.services.content_backup import (
    append_history,
    create_backup,
    get_backup,
    get_session,
    list_history,
    save_session,
)
from app.services.content_diff import build_content_diff, build_preview_summary
from app.services.content_publish import publish_update, restore_from_backup
from app.services.content_update_agent import validate_preserved_markup
from app.services.cost_control.module_gates import cau_ai_fix_gate, content_ai_llm_gate
from app.services.user_api_access import load_llm_config_for_request
from app.services.seo_core_30_score import (
    compare_seo_scores,
    evaluate_publish_gate,
    factors_failed_items,
    factors_not_passed,
    factors_warning_items,
    seo_factor_counts,
)
from app.services.wp_site_connector import (
    connect_site,
    fetch_post_by_id,
    fetch_post_by_url,
    get_site_credentials,
    list_site_categories,
    list_site_posts,
    list_sites,
    test_site_by_id,
)

router = APIRouter(tags=["content-auto-update"])

_SESSION_PUBLIC_KEYS = frozenset({
    "id", "site_id", "post_url", "wp_id", "post_type", "slug", "keyword",
    "backup_id", "created_at", "updated_at", "score_regressed",
})


def _public_session(session: dict[str, Any] | None) -> dict[str, Any]:
    if not session:
        return {}
    return {k: session[k] for k in _SESSION_PUBLIC_KEYS if k in session}


def _pack_html_field(html: str, field: str = "content") -> dict[str, str]:
    """Encode HTML as utf8 base64 so antivirus/web-shield does not block JSON with <script>."""
    raw = str(html or "")
    return {
        field: "",
        f"{field}_b64": base64.b64encode(raw.encode("utf-8")).decode("ascii"),
        f"{field}_encoding": "utf8_b64",
    }


def _post_public_payload(post: dict[str, Any]) -> dict[str, Any]:
    """Sanitize post dict for browser: encode HTML content fields."""
    out = dict(post or {})
    out.update(_pack_html_field(str(out.get("content") or ""), "content"))
    excerpt = str(out.get("excerpt") or "")
    if "<" in excerpt:
        out.update(_pack_html_field(excerpt, "excerpt"))
    return out


def _quota_denied_detail(exc: HTTPException) -> dict[str, Any]:
    d = exc.detail
    return d if isinstance(d, dict) else {"message": str(d), "upgrade_required": True}


class SiteConnectBody(BaseModel):
    url: str = Field(..., min_length=4, max_length=2000)
    username: str = Field(..., min_length=1, max_length=120)
    app_password: str = Field(..., min_length=4, max_length=256)
    label: str = Field(default="", max_length=120)


class SiteTestBody(BaseModel):
    site_id: str = Field(..., min_length=8, max_length=64)


class FetchUrlBody(BaseModel):
    site_id: str = Field(..., min_length=8, max_length=64)
    url: str = Field(..., min_length=4, max_length=2000)
    wp_id: int | None = Field(default=None, ge=1)
    post_type: str = Field(default="", max_length=64)
    rest_base: str = Field(default="", max_length=64)


class GenerateBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    keyword: str = Field(default="", max_length=200)
    focus: str = Field(default="", max_length=500)


class PreviewBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)


class PublishBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    mode: str = Field(default="draft", max_length=16)


class RestoreBody(BaseModel):
    backup_id: str = Field(..., min_length=8, max_length=64)


class ModalScoreBody(BaseModel):
    title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=500)
    content_html: str = Field(default="", max_length=500_000)
    primary_keyword: str = Field(default="", max_length=200)
    slug: str = Field(default="", max_length=200)
    secondary_keywords: str = Field(default="", max_length=500)
    post_url: str = Field(default="", max_length=2000)


class ModalFixFactorBody(BaseModel):
    factor_id: str = Field(..., min_length=2, max_length=64)
    post_id: int | None = Field(default=None, ge=0)
    post_url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=500)
    content_html: str = Field(default="", max_length=500_000)
    primary_keyword: str = Field(default="", max_length=200)
    slug: str = Field(default="", max_length=200)
    secondary_keywords: str = Field(default="", max_length=500)
    category_name: str = Field(default="", max_length=200)


class ModalFixFactorsBody(BaseModel):
    factor_ids: list[str] = Field(..., min_length=1, max_length=20)
    post_id: int | None = Field(default=None, ge=0)
    post_url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=500)
    content_html: str = Field(default="", max_length=500_000)
    primary_keyword: str = Field(default="", max_length=200)
    slug: str = Field(default="", max_length=200)
    secondary_keywords: str = Field(default="", max_length=500)
    category_name: str = Field(default="", max_length=200)


class ModalFixFactorApplyBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    post_url: str = Field(default="", max_length=2000)
    factor_ids: list[str] = Field(default_factory=list)
    change_reports: list[dict[str, Any]] = Field(default_factory=list)
    patch: dict[str, Any] = Field(default_factory=dict)
    seo_before_score: int | None = None
    seo_after_score: int | None = None


class ModalRewriteContentBody(ModalScoreBody):
    post_id: int | None = Field(default=None, ge=0)
    outline_content: str = Field(default="", max_length=50_000)
    target_word_count: int | None = Field(default=None, ge=200, le=20000)


class ModalAppendHeadingsBody(ModalScoreBody):
    post_id: int | None = Field(default=None, ge=0)
    outline_content: str = Field(default="", max_length=50_000)
    headings: list[str] = Field(default_factory=list, max_length=12)
    auto_generate_heading: bool = Field(default=False)


class ModalAnalyzeBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=500_000)
    excerpt: str = Field(default="", max_length=500)
    keyword: str = Field(default="", max_length=200)
    focus: str = Field(default="", max_length=500)
    slug: str = Field(default="", max_length=200)


class ModalUpdateBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=500_000)
    excerpt: str = Field(default="", max_length=500)
    slug: str = Field(default="", max_length=200)
    keyword: str = Field(default="", max_length=200)
    secondary_keywords: str = Field(default="", max_length=500)
    confirmed: bool = Field(default=False)
    expected_modified: str = Field(default="", max_length=64)
    patches: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class ModalUpdateConfirmBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=500_000)
    excerpt: str = Field(default="", max_length=500)
    slug: str = Field(default="", max_length=200)
    keyword: str = Field(default="", max_length=200)
    secondary_keywords: str = Field(default="", max_length=500)
    expected_modified: str = Field(default="", max_length=64)
    patches: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class AssistantPatchBody(BaseModel):
    session_id: str = Field(default="", max_length=64)
    action: str = Field(..., min_length=2, max_length=64)
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    target_block_id: str | None = Field(default=None, max_length=64)
    selection_html: str = Field(default="", max_length=50_000)
    primary_keyword: str = Field(default="", max_length=200)
    seo_score: int | None = Field(default=None, ge=0, le=100)
    link_url: str = Field(default="", max_length=2000)
    link_anchor: str = Field(default="", max_length=200)
    use_llm: bool = Field(default=False)
    post_id: int | None = Field(default=None, ge=0)
    post_url: str = Field(default="", max_length=2000)


class AssistantRefreshPlanBody(BaseModel):
    level: str = Field(default="standard", max_length=16)
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    seo_score: int | None = Field(default=None, ge=0, le=100)
    primary_keyword: str = Field(default="", max_length=200)


class AssistantRefreshRunBody(AssistantRefreshPlanBody):
    session_id: str = Field(default="", max_length=64)
    use_llm: bool = Field(default=False)
    post_id: int | None = Field(default=None, ge=0)
    post_url: str = Field(default="", max_length=2000)


class AssistantApplyBody(BaseModel):
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    patch: dict[str, Any] = Field(default_factory=dict)


class AssistantUndoBody(BaseModel):
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    patch: dict[str, Any] = Field(default_factory=dict)
    patches: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    undo_all: bool = False


class InsertSuggestBody(BaseModel):
    session_id: str = Field(default="", max_length=64)
    kind: str = Field(..., min_length=2, max_length=32)  # heading | cta | faq
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    insert_index: int = Field(default=0, ge=0)
    title: str = Field(default="", max_length=500)
    primary_keyword: str = Field(default="", max_length=200)
    post_url: str = Field(default="", max_length=1000)
    count: int = Field(default=5, ge=3, le=5)
    use_llm: bool = Field(default=False)


class InsertGenerateBody(BaseModel):
    session_id: str = Field(default="", max_length=64)
    insert_type: str = Field(..., min_length=2, max_length=32)
    content_html: str = Field(default="", max_length=500_000)
    blocks: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    insert_index: int = Field(default=0, ge=0)
    title: str = Field(default="", max_length=500)
    primary_keyword: str = Field(default="", max_length=200)
    post_url: str = Field(default="", max_length=1000)
    options: dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = Field(default=False)
    site_id: str = Field(default="", max_length=64)


class ScanScoreUpsertBody(BaseModel):
    site_id: str = Field(..., min_length=8, max_length=64)
    post_id: int = Field(..., ge=1)
    post_type: str = Field(default="post", max_length=64)
    url: str = Field(default="", max_length=2000)
    slug: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=500)
    status: str = Field(default="", max_length=32)
    modified: str = Field(default="", max_length=64)
    seo_score: int = Field(..., ge=0, le=100)


def _parse_secondary_keywords(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()][:20]


def _modal_llm_gate(db: Session, user: User, *, unit_cost: int) -> dict[str, Any]:
    from app.services.cau_ai_fix_entitlement import PAID_LLM_FREE_MESSAGE
    from app.services.user_api_access import resolve_ai_llm_gate

    gate = resolve_ai_llm_gate(
        db, user, unit_cost=unit_cost, denied_message=PAID_LLM_FREE_MESSAGE,
    )
    if not gate.get("allowed"):
        from fastapi import HTTPException, status

        code = str(gate.get("code") or "denied")
        http_status = status.HTTP_402_PAYMENT_REQUIRED if code == "insufficient_credits" else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=http_status, detail=gate)
    return {
        "use_system_llm": bool(gate.get("use_system_llm")),
        "charge_credits": bool(gate.get("charge_credits")),
        "unit_cost": int(gate.get("unit_cost") or 0),
    }


def _ensure_session_backup(*, user_id: int, session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    backup_id = str(session.get("backup_id") or "").strip()
    if backup_id:
        return backup_id, session
    orig = session.get("original") or {}
    backup = create_backup(
        user_id=user_id,
        session_id=str(session.get("id")),
        site_id=str(session.get("site_id")),
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        post_url=str(session.get("post_url") or ""),
        snapshot={
            "old_title": orig.get("title") or "",
            "old_content": orig.get("content") or "",
            "old_excerpt": orig.get("excerpt") or "",
            "old_status": orig.get("status") or "draft",
        },
    )
    session = dict(session)
    session["backup_id"] = backup["id"]
    session = save_session(user_id, session)
    return str(backup["id"]), session


@router.post("/content-ai/sites/connect")
def api_sites_connect(
    body: SiteConnectBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    item = connect_site(
        user_id=current_user.id,
        url=body.url,
        username=body.username,
        app_password=body.app_password,
        label=body.label,
    )
    return JSONResponse({"item": item})


@router.get("/content-ai/sites")
def api_sites_list(current_user: User = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({"items": list_sites(current_user.id)})


@router.post("/content-ai/sites/test")
def api_sites_test(
    body: SiteTestBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    result = test_site_by_id(body.site_id, current_user.id)
    return JSONResponse(result)


@router.get("/content-ai/auto-update/quota")
def api_cau_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    return JSONResponse(build_cau_quota_snapshot(db, current_user))


@router.get("/content-ai/auto-update/categories")
def api_list_categories(
    site_id: str = Query(..., min_length=8, max_length=64),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    result = list_site_categories(site_id=site_id, user_id=current_user.id)
    items = result.get("categories") or result.get("items") or []
    return JSONResponse({
        "ok": True,
        "categories": items,
        "items": items,
        "has_uncategorized": result.get("has_uncategorized", False),
    })


@router.get("/content-ai/auto-update/posts")
def api_list_posts(
    site_id: str = Query(..., min_length=8, max_length=64),
    page: int = Query(default=1, ge=1, le=500),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=200),
    status: str = Query(default="all", max_length=16),
    category_id: str = Query(default="", max_length=128),
    fetch_all: bool = Query(default=False),
    refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    cat_raw = category_id.strip()
    search_raw = search.strip()
    status_raw = status.strip() or "all"

    if fetch_all and not refresh:
        cached = get_scan_cache(
            user_id=current_user.id,
            site_id=site_id,
            category_id=cat_raw,
            status=status_raw,
            search=search_raw,
        )
        if cached:
            return JSONResponse({
                "ok": True,
                "posts": cached.get("posts") or [],
                "page": 1,
                "per_page": len(cached.get("posts") or []),
                "has_more": False,
                "total": len(cached.get("posts") or []),
                "type_counts": cached.get("type_counts") or {},
                "from_cache": True,
                "scanned_at": cached.get("scanned_at"),
            })
        return JSONResponse({
            "ok": True,
            "posts": [],
            "page": 1,
            "per_page": 0,
            "has_more": False,
            "total": 0,
            "type_counts": {},
            "from_cache": False,
            "scanned_at": None,
        })

    if fetch_all:
        # Sync scan via WordPress REST (Celery crawl_routed_jobs path removed / unavailable).
        result = list_site_posts(
            site_id=site_id,
            user_id=current_user.id,
            page=page,
            per_page=per_page,
            search=search_raw,
            status=status_raw,
            category_id=cat_raw,
            fetch_all=True,
        )
        posts = result.get("posts") or []
        type_counts = result.get("type_counts") or {}
        cached = save_scan_cache(
            user_id=current_user.id,
            site_id=site_id,
            category_id=cat_raw,
            status=status_raw,
            search=search_raw,
            posts=posts,
            type_counts=type_counts,
        )
        return JSONResponse({
            "ok": True,
            "posts": posts,
            "page": 1,
            "per_page": len(posts),
            "has_more": bool(result.get("has_more")),
            "total": result.get("total", len(posts)),
            "type_counts": type_counts,
            "from_cache": False,
            "scanned_at": cached.get("scanned_at"),
        })

    result = list_site_posts(
        site_id=site_id,
        user_id=current_user.id,
        page=page,
        per_page=per_page,
        search=search_raw,
        status=status_raw,
        category_id=cat_raw,
        fetch_all=False,
    )
    posts = result.get("posts") or []

    return JSONResponse({
        "ok": True,
        "posts": posts,
        "page": result["page"],
        "per_page": result["per_page"],
        "has_more": result["has_more"],
        "total": result.get("total"),
        "type_counts": result.get("type_counts") or {},
        "from_cache": False,
        "scanned_at": None,
    })


@router.get("/content-ai/auto-update/jobs/{job_id}")
def api_cau_crawl_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Legacy poll endpoint — CAU list posts now runs synchronously."""
    from app.services.job_store import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    payload = job.payload if isinstance(job.payload, dict) else {}
    if int(payload.get("user_id") or 0) != int(current_user.id):
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    state = str(job.state or "").upper()
    return JSONResponse({
        "job_id": job_id,
        "state": state or "FAILED",
        "message": job.message or (
            "Job nền CAU đã tắt — hãy bấm Quét bài viết lại (đồng bộ)."
        ),
        "result": job.result,
    })


@router.post("/content-ai/auto-update/scan-cache/score")
def api_upsert_scan_score(
    body: ScanScoreUpsertBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    entry = upsert_post_score(
        user_id=current_user.id,
        site_id=body.site_id,
        post_id=body.post_id,
        post_type=body.post_type,
        url=body.url,
        slug=body.slug,
        title=body.title,
        status=body.status,
        modified=body.modified,
        seo_score=body.seo_score,
    )
    return JSONResponse({
        "ok": True,
        "post_score": entry,
        "score_level": score_level_from_score(body.seo_score),
        "priority": priority_from_score(body.seo_score),
    })


@router.post("/content-ai/auto-update/fetch-url")
def api_fetch_url(
    body: FetchUrlBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        assert_cau_feature(db, current_user, "content_auto_update_fetch", quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc

    from app.services.url_safety import assert_public_http_url

    safe_url = assert_public_http_url(body.url, label="URL bài viết")
    wp_id = int(body.wp_id or 0)
    if wp_id > 0:
        post = fetch_post_by_id(
            site_id=body.site_id,
            user_id=current_user.id,
            wp_id=wp_id,
            post_type=str(body.post_type or ""),
            rest_base=str(body.rest_base or ""),
            post_url=safe_url,
        )
    else:
        post = fetch_post_by_url(
            site_id=body.site_id,
            user_id=current_user.id,
            post_url=safe_url,
            post_type=str(body.post_type or ""),
            rest_base=str(body.rest_base or ""),
        )
    seo_before = evaluate_cau_modal_seo(
        title=str(post.get("title") or ""),
        meta_description=str(post.get("excerpt") or ""),
        content_html=str(post.get("content") or ""),
        primary_keyword="",
        slug=str(post.get("slug") or ""),
        post_url=str(body.url or ""),
    )
    session = save_session(
        current_user.id,
        {
            "site_id": body.site_id,
            "post_url": body.url,
            "wp_id": post["wp_id"],
            "post_type": post["post_type"],
            "slug": post.get("slug") or "",
            "original": {
                "title": post["title"],
                "content": post["content"],
                "excerpt": post["excerpt"],
                "status": post["status"],
                "modified": pick_wp_modified(post),
            },
            "wp_modified": pick_wp_modified(post),
            "proposal": None,
            "backup_id": None,
            "seo_before": seo_before,
            "seo_after": None,
            "seo_comparison": None,
        },
    )
    failed_items = factors_failed_items(seo_before)
    warning_items = factors_warning_items(seo_before)
    record_cau_usage(
        db,
        current_user,
        "content_auto_update_fetch",
        metadata={"site_id": body.site_id, "url": body.url[:500]},
        idempotency_key=f"cau-fetch:{session.get('id')}",
    )

    seo_score = int(seo_before.get("score") or 0)
    upsert_post_score(
        user_id=current_user.id,
        site_id=body.site_id,
        post_id=int(post.get("wp_id") or 0),
        post_type=str(post.get("post_type") or "post"),
        url=str(post.get("link") or body.url),
        slug=str(post.get("slug") or ""),
        title=str(post.get("title") or ""),
        status=str(post.get("status") or ""),
        modified=str(post.get("modified") or ""),
        seo_score=seo_score,
    )

    return JSONResponse({
        "session": _public_session(session),
        "post": _post_public_payload(post),
        "seo_before": seo_before,
        "seo_summary": seo_factor_counts(seo_before),
        "failed_items": failed_items,
        "warning_items": warning_items,
        "failed_factors": factors_not_passed(seo_before),
    })


@router.post("/content-ai/auto-update/generate")
def api_generate(
    body: GenerateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        assert_cau_feature(db, current_user, "content_auto_update_generate", quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc

    session = get_session(body.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")

    from app.services.llm_routed_jobs import enqueue_llm_routed

    with cau_ai_fix_gate(
        db,
        current_user,
        action="cau_generate",
        llm_cfg=load_llm_config_for_request(db, current_user),
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_generate",
            payload={
                "session_id": body.session_id,
                "keyword": body.keyword.strip(),
                "focus": body.focus,
            },
            credit_cost=0,
            credit_reason="cau_generate",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/preview")
def api_preview(
    body: PreviewBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    session = get_session(body.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")
    orig = session.get("original") or {}
    prop = session.get("proposal") or {}
    if not prop:
        raise HTTPException(status_code=400, detail="Chưa có đề xuất AI — bấm Generate trước.")

    diff = build_content_diff(
        old_title=str(orig.get("title") or ""),
        new_title=str(prop.get("title") or ""),
        old_content=str(orig.get("content") or ""),
        new_content=str(prop.get("content") or ""),
        old_excerpt=str(orig.get("excerpt") or ""),
        new_excerpt=str(prop.get("excerpt") or ""),
    )

    backup_id = session.get("backup_id")
    if not backup_id:
        backup = create_backup(
            user_id=current_user.id,
            session_id=str(session.get("id")),
            site_id=str(session.get("site_id")),
            wp_id=int(session.get("wp_id") or 0),
            post_type=str(session.get("post_type") or "post"),
            post_url=str(session.get("post_url") or ""),
            snapshot={
                "old_title": orig.get("title") or "",
                "old_content": orig.get("content") or "",
                "old_excerpt": orig.get("excerpt") or "",
                "old_status": orig.get("status") or "draft",
            },
        )
        backup_id = backup["id"]
        session = dict(session)
        session["backup_id"] = backup_id
        save_session(current_user.id, session)

    comparison = session.get("seo_comparison") or {}
    gate = evaluate_publish_gate(
        backup_id=str(backup_id) if backup_id else None,
        seo_before=session.get("seo_before"),
        seo_after=session.get("seo_after"),
        old_content=str(orig.get("content") or ""),
        new_content=str(prop.get("content") or ""),
        preserve_warnings=session.get("preserve_warnings") or [],
    )
    if not comparison and gate.get("comparison"):
        comparison = gate["comparison"]
    preview_summary = build_preview_summary(
        diff=diff,
        comparison=comparison,
        backup_id=str(backup_id),
    )

    return JSONResponse({
        "diff": diff,
        "preview_summary": preview_summary,
        "backup_id": backup_id,
        "warnings": session.get("preserve_warnings") or [],
        "seo_comparison": comparison,
        "publish_checklist": gate.get("checklist"),
        "can_publish": gate.get("can_publish_live", gate.get("can_publish")),
        "can_publish_live": gate.get("can_publish_live", gate.get("can_publish")),
        "can_save_draft": gate.get("can_save_draft"),
        "score_regressed": gate.get("score_regressed", session.get("score_regressed")),
        "publish_blockers": gate.get("blockers"),
        "draft_block_reasons": (gate.get("checklist") or {}).get("draft_block_reasons"),
        "live_block_reasons": (gate.get("checklist") or {}).get("live_block_reasons"),
    })


@router.post("/content-ai/auto-update/publish")
def api_publish(
    body: PublishBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    session = get_session(body.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")
    backup_id = session.get("backup_id")
    if not backup_id:
        raise HTTPException(status_code=400, detail="Chưa backup — chạy Preview trước khi publish.")

    prop = session.get("proposal") or {}
    if not prop:
        raise HTTPException(status_code=400, detail="Chưa có đề xuất AI.")

    orig = session.get("original") or {}
    gate = evaluate_publish_gate(
        backup_id=str(backup_id) if backup_id else None,
        seo_before=session.get("seo_before"),
        seo_after=session.get("seo_after"),
        old_content=str(orig.get("content") or ""),
        new_content=str(prop.get("content") or ""),
        preserve_warnings=session.get("preserve_warnings") or [],
    )
    mode = "publish" if str(body.mode).lower() == "publish" else "draft"
    new_content = str(prop.get("content") or "")
    can_live = gate.get("can_publish_live", gate.get("can_publish"))
    can_draft = gate.get("can_save_draft", False)

    if mode == "publish":
        try:
            assert_cau_feature(db, current_user, "content_auto_update_publish", quantity=1)
        except HTTPException as exc:
            raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc
        if not can_live:
            blockers = gate.get("checklist", {}).get("live_block_reasons") or gate.get("blockers") or []
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Không đủ điều kiện publish live.",
                    "blockers": blockers,
                    "checklist": gate.get("checklist"),
                    "score_regressed": gate.get("score_regressed"),
                },
            )
    else:
        if not can_draft:
            reasons = (gate.get("checklist") or {}).get("draft_block_reasons") or []
            if not new_content.strip():
                reasons = reasons or ["Nội dung mới rỗng."]
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Không đủ điều kiện lưu nháp (cần backup + nội dung).",
                    "blockers": reasons,
                    "checklist": gate.get("checklist"),
                },
            )

    result = publish_update(
        user_id=current_user.id,
        site_id=str(session.get("site_id")),
        backup_id=str(backup_id),
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        title=str(prop.get("title") or ""),
        content=str(prop.get("content") or ""),
        excerpt=str(prop.get("excerpt") or ""),
        mode=mode,
        slug=str(session.get("slug") or ""),
    )

    comp = session.get("seo_comparison") or {}
    job_id = str(uuid.uuid4())
    history_row = append_history(
        current_user.id,
        {
            "job_id": job_id,
            "action": mode,
            "mode": mode,
            "session_id": session.get("id"),
            "backup_id": backup_id,
            "site_id": session.get("site_id"),
            "wp_id": session.get("wp_id"),
            "post_url": session.get("post_url") or result.get("link"),
            "title": prop.get("title"),
            "link": result.get("link"),
            "status": "success",
            "message": f"Publish {mode} thành công.",
            "seo_before_score": comp.get("before_score"),
            "seo_after_score": comp.get("after_score"),
            "seo_delta": comp.get("delta"),
        },
    )
    record_cau_usage(
        db,
        current_user,
        "content_auto_update_publish",
        metadata={"job_id": job_id, "mode": mode, "wp_id": session.get("wp_id")},
        idempotency_key=f"cau-pub:{job_id}",
    )
    return JSONResponse({"result": result, "job": history_row})


@router.post("/content-ai/auto-update/restore")
def api_restore(
    body: RestoreBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        assert_cau_feature(db, current_user, "content_auto_update_restore", quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc

    backup = get_backup(body.backup_id, current_user.id)
    result = restore_from_backup(user_id=current_user.id, backup_id=body.backup_id)
    job_id = str(uuid.uuid4())
    history_row = append_history(
        current_user.id,
        {
            "job_id": job_id,
            "action": "restore",
            "mode": "restore",
            "backup_id": body.backup_id,
            "site_id": backup.get("site_id") if backup else None,
            "wp_id": backup.get("wp_id") if backup else result.get("wp_id"),
            "post_url": (backup or {}).get("post_url") or result.get("link"),
            "title": (backup or {}).get("old_title"),
            "link": result.get("link"),
            "status": "success",
            "message": result.get("message"),
        },
    )
    record_cau_usage(
        db,
        current_user,
        "content_auto_update_restore",
        metadata={"backup_id": body.backup_id, "job_id": job_id},
        idempotency_key=f"cau-restore:{body.backup_id}:{job_id}",
    )
    return JSONResponse({"result": result, "job": history_row})


@router.post("/content-ai/auto-update/modal/score")
def api_modal_score(
    body: ModalScoreBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    seo = evaluate_cau_modal_seo(
        title=body.title.strip(),
        meta_description=body.meta_description.strip(),
        content_html=body.content_html,
        primary_keyword=body.primary_keyword.strip(),
        slug=body.slug.strip(),
        secondary_keywords=secondary or None,
        post_url=body.post_url.strip(),
    )
    return JSONResponse({
        "seo": seo,
        "summary": seo_factor_counts(seo),
        "failed_items": factors_failed_items(seo),
        "warning_items": factors_warning_items(seo),
    })


@router.post("/content-ai/auto-update/modal/rewrite-content")
def api_modal_rewrite_content(
    body: ModalRewriteContentBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        validate_rewrite_modal_brief(
            title=body.title,
            meta_description=body.meta_description,
            slug=body.slug,
            primary_keyword=body.primary_keyword,
            secondary_keywords=body.secondary_keywords,
            outline_content=body.outline_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    unit_cost = cost_content_ai_article(db=db)
    gate = _modal_llm_gate(db, current_user, unit_cost=unit_cost)
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    llm_cfg = None
    try:
        llm_cfg = load_llm_config_for_request(db, current_user)
    except Exception:
        llm_cfg = None
    from app.services.llm_routed_jobs import enqueue_llm_routed

    with content_ai_llm_gate(
        db,
        current_user,
        action="cau_modal_rewrite",
        field="content",
        use_system_llm=bool(gate.get("use_system_llm")),
        llm_cfg=llm_cfg,
        feature_key="content_auto_update_generate",
        credit_cost=unit_cost,
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_modal_rewrite",
            payload={
                "title": body.title.strip(),
                "meta_description": body.meta_description.strip(),
                "slug": body.slug.strip(),
                "primary_keyword": body.primary_keyword.strip(),
                "secondary_keywords": secondary or None,
                "outline_content": body.outline_content,
                "content_html": body.content_html,
                "post_url": body.post_url.strip(),
                "target_word_count": body.target_word_count,
                "post_id": body.post_id,
                "use_system_llm": bool(gate.get("use_system_llm")),
            },
            credit_cost=unit_cost if gate.get("charge_credits") else 0,
            credit_reason="cau_modal_rewrite",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/modal/append-headings")
def api_modal_append_headings(
    body: ModalAppendHeadingsBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    if not body.primary_keyword.strip():
        raise HTTPException(status_code=400, detail="Cần focus keyword.")
    headings = [str(h or "").strip() for h in (body.headings or []) if str(h or "").strip()]
    auto_mode = bool(body.auto_generate_heading) or not headings
    from app.services.credit_cost_registry import resolve_credit_cost

    unit_cost = resolve_credit_cost("cau", "modal_append", db=db) * (
        2 if auto_mode else max(1, min(len(headings), 8))
    )
    gate = _modal_llm_gate(db, current_user, unit_cost=unit_cost)
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    outline = str(body.outline_content or "")
    llm_cfg = None
    try:
        llm_cfg = load_llm_config_for_request(db, current_user)
    except Exception:
        llm_cfg = None
    from app.services.llm_routed_jobs import enqueue_llm_routed

    with content_ai_llm_gate(
        db,
        current_user,
        action="cau_modal_append_headings",
        field="content",
        use_system_llm=bool(gate.get("use_system_llm")),
        llm_cfg=llm_cfg,
        feature_key="content_auto_update_generate",
        credit_cost=unit_cost,
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_modal_append_headings",
            payload={
                "headings": headings,
                "title": body.title.strip(),
                "meta_description": body.meta_description.strip(),
                "slug": body.slug.strip(),
                "primary_keyword": body.primary_keyword.strip(),
                "secondary_keywords": secondary or None,
                "outline_content": outline,
                "content_html": body.content_html,
                "post_url": body.post_url.strip(),
                "post_id": body.post_id,
                "use_system_llm": bool(gate.get("use_system_llm")),
                "auto_generate_heading": auto_mode,
            },
            credit_cost=unit_cost if gate.get("charge_credits") else 0,
            credit_reason="cau_modal_append_headings",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/modal/fix-factor")
def api_modal_fix_factor(
    body: ModalFixFactorBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        ent = assert_cau_ai_fix_entitlement(db, current_user, quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=_quota_denied_detail(exc)) from exc

    plan_slug = str(ent.get("plan_slug") or resolve_cau_ai_plan_slug(db, current_user) or "")
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    from app.services.llm_routed_jobs import enqueue_llm_routed

    with cau_ai_fix_gate(
        db,
        current_user,
        action="cau_modal_fix_factor",
        llm_cfg=load_llm_config_for_request(db, current_user),
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_modal_fix_factor",
            payload={
                "factor_id": body.factor_id.strip(),
                "post_id": body.post_id,
                "post_url": body.post_url.strip(),
                "title": body.title.strip(),
                "meta_description": body.meta_description.strip(),
                "content_html": body.content_html,
                "primary_keyword": body.primary_keyword.strip(),
                "slug": body.slug.strip(),
                "secondary_keywords": secondary or None,
                "category_name": body.category_name.strip(),
                "plan_slug": plan_slug,
                "ai_fix": ent,
            },
            credit_cost=0,
            credit_reason="cau_modal_fix_factor",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/modal/fix-factors")
def api_modal_fix_factors(
    body: ModalFixFactorsBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    factor_ids = [str(x).strip() for x in body.factor_ids if str(x).strip()][:20]
    try:
        ent = assert_cau_ai_fix_entitlement(db, current_user, quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=_quota_denied_detail(exc)) from exc

    plan_slug = str(ent.get("plan_slug") or resolve_cau_ai_plan_slug(db, current_user) or "")
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    from app.services.llm_routed_jobs import enqueue_llm_routed

    with cau_ai_fix_gate(
        db,
        current_user,
        action="cau_modal_fix_factors",
        llm_cfg=load_llm_config_for_request(db, current_user),
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_modal_fix_factors",
            payload={
                "factor_ids": factor_ids,
                "post_id": body.post_id,
                "post_url": body.post_url.strip(),
                "title": body.title.strip(),
                "meta_description": body.meta_description.strip(),
                "content_html": body.content_html,
                "primary_keyword": body.primary_keyword.strip(),
                "slug": body.slug.strip(),
                "secondary_keywords": secondary or None,
                "category_name": body.category_name.strip(),
                "plan_slug": plan_slug,
                "ai_fix": ent,
            },
            credit_cost=0,
            credit_reason="cau_modal_fix_factors",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/modal/fix-factor/apply")
def api_modal_fix_factor_apply(
    body: ModalFixFactorApplyBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    session = get_session(body.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")

    reports = body.change_reports or []
    factor_ids = body.factor_ids or [str(r.get("factor_id") or "") for r in reports if r.get("factor_id")]
    factor_ids = [f for f in factor_ids if f]
    labels = [str(r.get("factor_label") or r.get("factor_id") or "") for r in reports if r]
    score_before = body.seo_before_score
    score_after = body.seo_after_score
    delta = None
    if score_before is not None and score_after is not None:
        delta = int(score_after) - int(score_before)

    job_id = str(uuid.uuid4())
    history_row = append_history(
        current_user.id,
        {
            "job_id": job_id,
            "action": "seo_ai_fix",
            "mode": "form_apply",
            "session_id": session.get("id"),
            "backup_id": session.get("backup_id"),
            "site_id": session.get("site_id"),
            "wp_id": session.get("wp_id"),
            "post_url": body.post_url.strip() or session.get("post_url"),
            "title": (reports[0] or {}).get("factor_label") if reports else "SEO AI fix",
            "link": body.post_url.strip() or session.get("post_url"),
            "status": "success",
            "message": "Đã áp dụng sửa SEO bằng AI vào form (chưa publish WordPress).",
            "seo_before_score": score_before,
            "seo_after_score": score_after,
            "seo_delta": delta,
            "factor_ids": factor_ids,
            "factor_labels": labels,
            "change_reports": reports[:20],
            "applied_fields": list((body.patch or {}).keys()),
        },
    )
    return JSONResponse({"ok": True, "job": history_row})


@router.post("/content-ai/auto-update/modal/analyze")
def api_modal_analyze(
    body: ModalAnalyzeBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        assert_cau_feature(db, current_user, "content_auto_update_generate", quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc

    session = get_session(body.session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")

    from app.services.llm_routed_jobs import enqueue_llm_routed

    with cau_ai_fix_gate(
        db,
        current_user,
        action="cau_modal_analyze",
        llm_cfg=load_llm_config_for_request(db, current_user),
    ):
        queued = enqueue_llm_routed(
            db=db,
            user=current_user,
            action="cau_modal_analyze",
            payload={
                "session_id": body.session_id,
                "title": body.title.strip(),
                "content": body.content,
                "excerpt": body.excerpt.strip(),
                "keyword": body.keyword.strip(),
                "focus": body.focus,
                "slug": body.slug.strip() or str(session.get("slug") or ""),
            },
            credit_cost=0,
            credit_reason="cau_modal_analyze",
            poll_url_prefix="/content-ai/llm/jobs",
        )
    try:
        record_cau_usage(
            db,
            current_user,
            "content_auto_update_generate",
            metadata={"session_id": body.session_id, "source": "modal", "queued": True},
            idempotency_key=f"cau-modal-analyze:{body.session_id}:{queued.get('job_id')}",
        )
    except Exception:
        pass
    db.commit()
    return JSONResponse(content=queued)


@router.post("/content-ai/auto-update/modal/update-confirm")
def api_modal_update_confirm(
    body: ModalUpdateConfirmBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Build confirm summary + validate + conflict check. Does NOT update WordPress."""
    from app.services.cau_modal_update_guard import (
        assert_session_owned,
        build_change_summary,
        detect_wp_conflict,
        pick_wp_modified,
        resolve_expected_modified,
        validate_modal_content,
    )

    session = assert_session_owned(get_session(body.session_id, current_user.id), current_user.id)
    # Site ownership: credentials lookup fails if not owned
    get_site_credentials(str(session.get("site_id") or ""), current_user.id)

    orig = session.get("original") or {}
    old_content = str(orig.get("content") or "")
    new_content = body.content
    validation = validate_modal_content(
        title=body.title.strip(),
        content_html=new_content,
        old_content=old_content,
    )
    if not validation["ok"]:
        raise HTTPException(status_code=400, detail={"message": "Nội dung không hợp lệ.", "errors": validation["errors"]})

    expected = resolve_expected_modified(session=session, client_expected=body.expected_modified)
    remote = fetch_post_by_id(
        site_id=str(session.get("site_id")),
        user_id=current_user.id,
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        post_url=str(session.get("post_url") or ""),
    )
    # Post ownership: wp_id in session must match remote
    if int(remote.get("wp_id") or 0) != int(session.get("wp_id") or 0):
        raise HTTPException(status_code=403, detail="post_id không khớp bài trên WordPress.")

    conflict = detect_wp_conflict(
        expected_modified=expected,
        remote_modified=pick_wp_modified(remote),
        remote_modified_alt=str(remote.get("modified") or "").strip(),
        baseline_content=old_content,
        remote_content=str(remote.get("content") or ""),
    )

    if conflict is None:
        session = dict(session)
        session["wp_modified"] = pick_wp_modified(remote)
        session = save_session(current_user.id, session)

    slug = body.slug.strip() or str(session.get("slug") or "")
    keyword = body.keyword.strip()
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    post_url = str(session.get("post_url") or "")
    seo_before = session.get("seo_before") or evaluate_cau_modal_seo(
        title=str(orig.get("title") or ""),
        meta_description=str(orig.get("excerpt") or ""),
        content_html=old_content,
        primary_keyword=keyword,
        slug=slug,
        secondary_keywords=secondary or None,
        post_url=post_url,
    )
    seo_after = evaluate_cau_modal_seo(
        title=body.title.strip(),
        meta_description=body.excerpt.strip(),
        content_html=new_content,
        primary_keyword=keyword,
        slug=slug,
        secondary_keywords=secondary or None,
        post_url=post_url,
    )
    summary = build_change_summary(
        old_title=str(orig.get("title") or ""),
        new_title=body.title.strip(),
        old_content=old_content,
        new_content=new_content,
        old_excerpt=str(orig.get("excerpt") or ""),
        new_excerpt=body.excerpt.strip(),
        seo_before=seo_before,
        seo_after=seo_after,
        post_status=str(orig.get("status") or remote.get("status") or ""),
        patches=body.patches,
    )
    return JSONResponse({
        "ok": True,
        "can_update": conflict is None and validation["ok"],
        "conflict": conflict,
        "validation": validation,
        "summary": summary,
        "remote_modified": pick_wp_modified(remote),
        "expected_modified": expected,
        "post_status": str(orig.get("status") or remote.get("status") or ""),
        "backup_required": True,
        "message": "Xác nhận trước khi cập nhật WordPress. Chưa publish.",
    })


@router.post("/content-ai/auto-update/modal/update")
def api_modal_update(
    body: ModalUpdateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    from app.services.cau_modal_update_guard import (
        assert_session_owned,
        build_change_summary,
        detect_wp_conflict,
        pick_wp_modified,
        resolve_expected_modified,
        validate_modal_content,
    )

    if not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Cần xác nhận cuối trước khi cập nhật WordPress (confirmed=true).",
        )

    try:
        assert_cau_feature(db, current_user, "content_auto_update_publish", quantity=1)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail=_quota_denied_detail(exc)) from exc

    session = assert_session_owned(get_session(body.session_id, current_user.id), current_user.id)
    get_site_credentials(str(session.get("site_id") or ""), current_user.id)

    orig = session.get("original") or {}
    old_content = str(orig.get("content") or "")
    new_content = body.content
    if not new_content.strip():
        raise HTTPException(status_code=400, detail="Nội dung không được để trống.")

    validation = validate_modal_content(
        title=body.title.strip(),
        content_html=new_content,
        old_content=old_content,
    )
    if not validation["ok"]:
        raise HTTPException(status_code=400, detail={"message": "Nội dung không hợp lệ.", "errors": validation["errors"]})

    expected = resolve_expected_modified(session=session, client_expected=body.expected_modified)
    remote = fetch_post_by_id(
        site_id=str(session.get("site_id")),
        user_id=current_user.id,
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        post_url=str(session.get("post_url") or ""),
    )
    if int(remote.get("wp_id") or 0) != int(session.get("wp_id") or 0):
        raise HTTPException(status_code=403, detail="post_id không khớp bài trên WordPress.")

    conflict = detect_wp_conflict(
        expected_modified=expected,
        remote_modified=pick_wp_modified(remote),
        remote_modified_alt=str(remote.get("modified") or "").strip(),
        baseline_content=old_content,
        remote_content=str(remote.get("content") or ""),
    )
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)

    preserve_warnings = list(validation.get("warnings") or [])
    # Always create a fresh backup before update (mandatory)
    backup = create_backup(
        user_id=current_user.id,
        session_id=str(session.get("id")),
        site_id=str(session.get("site_id")),
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        post_url=str(session.get("post_url") or ""),
        snapshot={
            "old_title": str(orig.get("title") or remote.get("title") or ""),
            "old_content": old_content or str(remote.get("content") or ""),
            "old_excerpt": str(orig.get("excerpt") or remote.get("excerpt") or ""),
            "old_status": str(orig.get("status") or remote.get("status") or "draft"),
        },
    )
    backup_id = str(backup["id"])
    session = dict(session)
    session["backup_id"] = backup_id
    session = save_session(current_user.id, session)

    slug = body.slug.strip() or str(session.get("slug") or "")
    keyword = body.keyword.strip()
    secondary = _parse_secondary_keywords(body.secondary_keywords)
    post_url = str(session.get("post_url") or "")
    seo_before = session.get("seo_before") or evaluate_cau_modal_seo(
        title=str(orig.get("title") or ""),
        meta_description=str(orig.get("excerpt") or ""),
        content_html=old_content,
        primary_keyword=keyword,
        slug=slug,
        secondary_keywords=secondary or None,
        post_url=post_url,
    )
    seo_after = evaluate_cau_modal_seo(
        title=body.title.strip(),
        meta_description=body.excerpt.strip(),
        content_html=new_content,
        primary_keyword=keyword,
        slug=slug,
        secondary_keywords=secondary or None,
        post_url=post_url,
    )
    seo_comparison = compare_seo_scores(seo_before, seo_after)
    summary = build_change_summary(
        old_title=str(orig.get("title") or ""),
        new_title=body.title.strip(),
        old_content=old_content,
        new_content=new_content,
        old_excerpt=str(orig.get("excerpt") or ""),
        new_excerpt=body.excerpt.strip(),
        seo_before=seo_before,
        seo_after=seo_after,
        post_status=str(orig.get("status") or remote.get("status") or ""),
        patches=body.patches,
    )

    orig_status = str(orig.get("status") or remote.get("status") or "draft")
    mode = "publish" if orig_status == "publish" else "draft"

    result = publish_update(
        user_id=current_user.id,
        site_id=str(session.get("site_id")),
        backup_id=str(backup_id),
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        title=body.title.strip(),
        content=new_content,
        excerpt=body.excerpt.strip(),
        mode=mode,
        slug=slug,
        preserve_wp_status=True,
        status=orig_status,
    )

    wp_mod = pick_wp_modified(result)
    session = dict(session)
    session["original"] = {
        "title": body.title.strip(),
        "content": new_content,
        "excerpt": body.excerpt.strip(),
        "status": result.get("status") or orig_status,
        "modified": wp_mod,
    }
    session["wp_modified"] = wp_mod
    session["keyword"] = keyword
    session["slug"] = slug
    session["seo_before"] = seo_after
    session["seo_after"] = None
    session["proposal"] = None
    session["preserve_warnings"] = preserve_warnings
    session["seo_comparison"] = seo_comparison
    session["last_summary"] = summary
    session = save_session(current_user.id, session)

    job_id = str(uuid.uuid4())
    history_row = append_history(
        current_user.id,
        {
            "job_id": job_id,
            "action": "modal_update",
            "mode": mode,
            "session_id": session.get("id"),
            "backup_id": backup_id,
            "site_id": session.get("site_id"),
            "wp_id": session.get("wp_id"),
            "post_url": session.get("post_url") or result.get("link"),
            "title": body.title.strip(),
            "link": result.get("link"),
            "status": "success",
            "message": "Đã cập nhật bài viết thành công.",
            "seo_before_score": seo_comparison.get("before_score"),
            "seo_after_score": seo_comparison.get("after_score"),
            "seo_delta": seo_comparison.get("delta"),
            "patches": body.patches[:50],
            "patches_count": len(body.patches or []),
            "operator": str(getattr(current_user, "email", None) or current_user.id),
            "actor_user_id": int(current_user.id),
            "wp_modified_before": expected,
        },
    )
    record_cau_usage(
        db,
        current_user,
        "content_auto_update_publish",
        metadata={"job_id": job_id, "source": "modal", "wp_id": session.get("wp_id")},
        idempotency_key=f"cau-modal-update:{job_id}",
    )
    upsert_post_score(
        user_id=current_user.id,
        site_id=str(session.get("site_id") or ""),
        post_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        url=str(session.get("post_url") or result.get("link") or ""),
        slug=slug,
        title=body.title.strip(),
        status=str(result.get("status") or orig_status),
        modified=str(result.get("modified") or ""),
        seo_score=int(seo_after.get("score") or 0),
    )
    return JSONResponse({
        "ok": True,
        "message": "Đã cập nhật bài viết thành công",
        "link": result.get("link"),
        "backup_id": backup_id,
        "result": result,
        "job": history_row,
        "warnings": preserve_warnings,
        "seo_after": seo_after,
        "seo_summary": seo_factor_counts(seo_after),
        "summary": summary,
        "auto_published": False,
    })


@router.get("/content-ai/auto-update/modal/snapshots")
def api_modal_snapshots(
    wp_id: int = Query(default=0, ge=0),
    site_id: str = Query(default="", max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.cau_modal_snapshots import list_modal_snapshots

    if site_id:
        get_site_credentials(site_id, current_user.id)
    items = list_modal_snapshots(
        current_user.id,
        wp_id=wp_id or None,
        site_id=site_id or None,
        limit=limit,
    )
    return JSONResponse({"items": items})


@router.get("/content-ai/auto-update/modal/snapshots/{snapshot_id}")
def api_modal_snapshot_detail(
    snapshot_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.cau_modal_snapshots import get_modal_snapshot_detail

    item = get_modal_snapshot_detail(snapshot_id, current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy backup.")
    return JSONResponse({"item": item})


@router.get("/content-ai/auto-update/modal/action-history")
def api_modal_action_history(
    wp_id: int = Query(default=0, ge=0),
    site_id: str = Query(default="", max_length=64),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.cau_modal_snapshots import list_modal_action_history

    if site_id:
        get_site_credentials(site_id, current_user.id)
    return JSONResponse({
        "items": list_modal_action_history(
            current_user.id,
            wp_id=wp_id or None,
            site_id=site_id or None,
            limit=limit,
        )
    })


@router.post("/content-ai/auto-update/modal/reload-remote")
def api_modal_reload_remote(
    body: PreviewBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Reload latest WP content into session after conflict (does not publish)."""
    from app.services.cau_modal_update_guard import assert_session_owned, pick_wp_modified

    session = assert_session_owned(get_session(body.session_id, current_user.id), current_user.id)
    get_site_credentials(str(session.get("site_id") or ""), current_user.id)
    remote = fetch_post_by_id(
        site_id=str(session.get("site_id")),
        user_id=current_user.id,
        wp_id=int(session.get("wp_id") or 0),
        post_type=str(session.get("post_type") or "post"),
        post_url=str(session.get("post_url") or ""),
    )
    seo_before = evaluate_cau_modal_seo(
        title=str(remote.get("title") or ""),
        meta_description=str(remote.get("excerpt") or ""),
        content_html=str(remote.get("content") or ""),
        primary_keyword=str(session.get("keyword") or ""),
        slug=str(remote.get("slug") or session.get("slug") or ""),
        post_url=str(session.get("post_url") or ""),
    )
    wp_mod = pick_wp_modified(remote)
    session = dict(session)
    session["original"] = {
        "title": remote.get("title"),
        "content": remote.get("content"),
        "excerpt": remote.get("excerpt"),
        "status": remote.get("status"),
        "modified": wp_mod,
    }
    session["wp_modified"] = wp_mod
    session["slug"] = remote.get("slug") or session.get("slug")
    session["seo_before"] = seo_before
    session["proposal"] = None
    session = save_session(current_user.id, session)
    return JSONResponse({
        "ok": True,
        "session": _public_session(session),
        "post": _post_public_payload(remote),
        "seo_before": seo_before,
        "message": "Đã tải lại bản WordPress mới vào phiên. Chưa cập nhật WP.",
    })


@router.get("/content-ai/auto-update/history")
def api_history(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return JSONResponse({"items": list_history(current_user.id, limit=limit)})


def _cau_assistant_blocks(content_html: str, blocks: list[dict[str, Any]]) -> list[Any]:
    from app.services.cau_block_model import ContentBlock, parse_blocks

    if blocks:
        return [ContentBlock.from_dict(b) for b in blocks]
    return parse_blocks(content_html or "")


def _cau_charge_on_success(
    db: Session,
    user: User,
    *,
    amount: int,
    reason: str,
    request_id: str,
) -> int:
    """Charge only after a successful AI result. Apply/undo must not call this."""
    from app.services.credits import consume_credits, credits_enforced

    amt = max(0, int(amount or 0))
    if amt <= 0 or not credits_enforced():
        return 0
    consume_credits(
        db,
        user_id=int(user.id),
        amount=amt,
        reason=reason[:64],
        note="cau_assistant_success",
        module="cau",
        action="assistant_patch",
        request_id=request_id[:128],
    )
    return amt


@router.post("/content-ai/auto-update/modal/assistant/patch")
def api_modal_assistant_patch(
    body: AssistantPatchBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Generate one structured patch. Credit only if LLM refine succeeds."""
    from app.services.cau_assistant_generate import (
        ACTION_CREDIT_EST,
        generate_template_patch,
        try_llm_refine_patch,
    )

    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    credit_est = int(ACTION_CREDIT_EST.get(body.action, 5))
    try:
        patch = generate_template_patch(
            action=body.action.strip(),
            blocks=blocks,
            target_block_id=body.target_block_id,
            selection_html=body.selection_html,
            keyword=body.primary_keyword.strip(),
            seo_score=body.seo_score,
            link_url=body.link_url.strip(),
            link_anchor=body.link_anchor.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    charged = 0
    if body.use_llm:
        gate = _modal_llm_gate(db, current_user, unit_cost=credit_est)
        refined = try_llm_refine_patch(
            patch,
            user_id=int(current_user.id),
            use_system_llm=bool(gate.get("use_system_llm")),
            keyword=body.primary_keyword.strip(),
        )
        if (refined.meta or {}).get("source") == "llm" and not (refined.meta or {}).get("llm_error"):
            patch = refined
            if gate.get("charge_credits"):
                rid = f"cau_asst:{patch.patch_id}"
                charged = _cau_charge_on_success(
                    db,
                    current_user,
                    amount=credit_est,
                    reason="cau_assistant_patch",
                    request_id=rid,
                )
                db.commit()
        else:
            patch = refined

    patch.credit_charged = charged
    patch.credit_estimate = credit_est
    return JSONResponse({
        "ok": True,
        "patch": patch.to_dict(),
        "credits_charged": charged,
        "charge_on_apply": False,
        "message": "Đã tạo patch. Áp dụng preview không trừ credit thêm.",
    })


@router.post("/content-ai/auto-update/modal/assistant/refresh-plan")
def api_modal_assistant_refresh_plan(
    body: AssistantRefreshPlanBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.cau_assistant_patches import build_refresh_plan

    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    plan = build_refresh_plan(level=body.level.strip() or "standard", blocks=blocks, seo_score=body.seo_score)
    return JSONResponse({"ok": True, "plan": plan})


@router.post("/content-ai/auto-update/modal/assistant/refresh-run")
def api_modal_assistant_refresh_run(
    body: AssistantRefreshRunBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Làm mới Content — structured patches only (never full HTML overwrite)."""
    from app.services.cau_assistant_generate import generate_refresh_patches, try_llm_refine_patch

    level = (body.level or "standard").strip()
    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    plan, patches = generate_refresh_patches(
        level=level,
        blocks=blocks,
        keyword=body.primary_keyword.strip(),
        seo_score=body.seo_score,
    )
    charged_total = 0
    out_patches: list[dict[str, Any]] = []
    gate = None
    if body.use_llm and patches:
        credit_cap = int(plan.get("credit_max") or 25)
        gate = _modal_llm_gate(db, current_user, unit_cost=min(credit_cap, sum(p.credit_estimate for p in patches) or 1))

    for p in patches:
        final = p
        if body.use_llm and gate is not None:
            refined = try_llm_refine_patch(
                p,
                user_id=int(current_user.id),
                use_system_llm=bool(gate.get("use_system_llm")),
                keyword=body.primary_keyword.strip(),
            )
            if (refined.meta or {}).get("source") == "llm" and not (refined.meta or {}).get("llm_error"):
                final = refined
                if gate.get("charge_credits"):
                    amt = _cau_charge_on_success(
                        db,
                        current_user,
                        amount=int(final.credit_estimate or 0),
                        reason="cau_assistant_refresh",
                        request_id=f"cau_refresh:{final.patch_id}",
                    )
                    charged_total += amt
                    final.credit_charged = amt
            else:
                final = refined
                final.credit_charged = 0
        else:
            final.credit_charged = 0
        out_patches.append(final.to_dict())

    if charged_total:
        db.commit()

    return JSONResponse({
        "ok": True,
        "plan": plan,
        "patches": out_patches,
        "credits_charged": charged_total,
        "charge_on_apply": False,
        "message": "Đã tạo patch làm mới. Áp dụng không trừ credit thêm.",
    })


def _insert_assert_owned(session_id: str, site_id: str, user_id: int) -> None:
    """Ownership guard for insert endpoints: session and/or site must belong to user."""
    from app.services.cau_modal_update_guard import assert_session_owned, assert_site_matches_session

    sid = str(session_id or "").strip()
    if sid:
        session = assert_session_owned(get_session(sid, user_id), user_id)
        if site_id:
            assert_site_matches_session(session, site_id)
    if site_id:
        get_site_credentials(str(site_id), user_id)


@router.post("/content-ai/auto-update/modal/insert/suggest")
def api_modal_insert_suggest(
    body: InsertSuggestBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """AI gợi ý heading/CTA/FAQ cho modal «Thêm nội dung». Template = 0 credit;
    chỉ trừ credit khi LLM trả kết quả thành công."""
    from app.services.cau_insert_generate import (
        INSERT_CREDIT_EST,
        build_insert_context,
        suggest_insert,
        try_llm_suggest,
    )

    _insert_assert_owned(body.session_id, "", int(current_user.id))
    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    context = build_insert_context(
        blocks=blocks,
        insert_index=body.insert_index,
        title=body.title,
        keyword=body.primary_keyword,
        url=body.post_url,
    )
    kind = body.kind.strip()
    try:
        suggestions = suggest_insert(kind=kind, context=context, count=body.count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    charged = 0
    source = "template"
    if body.use_llm:
        unit = int(INSERT_CREDIT_EST.get("suggest", 2))
        gate = _modal_llm_gate(db, current_user, unit_cost=unit)
        llm_cfg = None
        try:
            llm_cfg = load_llm_config_for_request(db, current_user)
        except Exception:
            llm_cfg = None
        with content_ai_llm_gate(
            db,
            current_user,
            action="cau_insert_suggest",
            field="content",
            use_system_llm=bool(gate.get("use_system_llm")),
            llm_cfg=llm_cfg,
            feature_key="content_auto_update_generate",
            credit_cost=unit,
        ):
            refined = try_llm_suggest(
                kind=kind,
                context=context,
                count=body.count,
                user_id=int(current_user.id),
                use_system_llm=bool(gate.get("use_system_llm")),
            )
        if refined:
            suggestions = refined
            source = "llm"
            if gate.get("charge_credits"):
                charged = _cau_charge_on_success(
                    db,
                    current_user,
                    amount=unit,
                    reason="cau_insert_suggest",
                    request_id=f"cau_ins_sug:{uuid.uuid4().hex[:12]}",
                )
                db.commit()

    return JSONResponse({
        "ok": True,
        "kind": kind,
        "suggestions": suggestions,
        "context": {
            "prev_heading": context["prev_heading"],
            "next_heading": context["next_heading"],
            "insert_index": context["insert_index"],
        },
        "source": source,
        "credits_charged": charged,
    })


@router.post("/content-ai/auto-update/modal/insert/generate")
def api_modal_insert_generate(
    body: InsertGenerateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Tạo preview cho một khối «Thêm nội dung». Không ghi vào bài, không publish —
    client chèn tại vị trí «+» khi người dùng bấm Áp dụng. Credit chỉ trừ khi LLM
    trả kết quả thành công; áp dụng lại không trừ."""
    from app.services.cau_insert_generate import (
        _body_word_count,
        build_insert_context,
        estimate_insert_credit,
        generate_insert_preview,
        insert_word_target,
        try_llm_insert_html,
    )

    _insert_assert_owned(body.session_id, body.site_id, int(current_user.id))
    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    context = build_insert_context(
        blocks=blocks,
        insert_index=body.insert_index,
        title=body.title,
        keyword=body.primary_keyword,
        url=body.post_url,
    )
    options = dict(body.options or {})
    if body.insert_type.strip() == "internal_link" and body.site_id:
        try:
            cred = get_site_credentials(body.site_id, int(current_user.id))
            options["site_base"] = str(cred.get("url") or "")
        except HTTPException:
            raise
    try:
        preview = generate_insert_preview(
            insert_type=body.insert_type.strip(),
            options=options,
            context=context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    charged = 0
    if body.use_llm:
        unit = estimate_insert_credit(body.insert_type.strip(), options)
        gate = _modal_llm_gate(db, current_user, unit_cost=unit)
        llm_cfg = None
        try:
            llm_cfg = load_llm_config_for_request(db, current_user)
        except Exception:
            llm_cfg = None
        with content_ai_llm_gate(
            db,
            current_user,
            action="cau_insert_generate",
            field="content",
            use_system_llm=bool(gate.get("use_system_llm")),
            llm_cfg=llm_cfg,
            feature_key="content_auto_update_generate",
            credit_cost=unit,
        ):
            refined = try_llm_insert_html(
                insert_type=body.insert_type.strip(),
                options=options,
                context=context,
                draft_html=preview["html"],
                user_id=int(current_user.id),
                use_system_llm=bool(gate.get("use_system_llm")),
            )
        if refined:
            preview["html"] = refined
            preview["source"] = "llm"
            from app.services.cau_insert_generate import _word_count as _wc

            preview["word_count"] = _wc(refined)
            preview["word_count_body"] = _body_word_count(refined)
            if gate.get("charge_credits"):
                charged = _cau_charge_on_success(
                    db,
                    current_user,
                    amount=unit,
                    reason="cau_insert_generate",
                    request_id=f"cau_ins_gen:{uuid.uuid4().hex[:12]}",
                )
                db.commit()

    preview["credits_charged"] = charged
    preview["word_target"] = insert_word_target(body.insert_type.strip(), options)
    if "word_count_body" not in preview:
        preview["word_count_body"] = _body_word_count(preview.get("html") or "")
    return JSONResponse({
        "ok": True,
        "preview": preview,
        "credits_charged": charged,
        "charge_on_apply": False,
        "message": "Preview đã tạo. Áp dụng vào bài không trừ credit thêm.",
    })


@router.get("/content-ai/auto-update/modal/insert/site-links")
def api_modal_insert_site_links(
    site_id: str = Query(..., min_length=8, max_length=64),
    q: str = Query(default="", max_length=200),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """URL thật của website (cho Internal link). Ownership qua get_site_credentials."""
    result = list_site_posts(
        site_id=site_id,
        user_id=int(current_user.id),
        page=1,
        per_page=20,
        search=q,
        status="publish",
    )
    items = []
    for p in result.get("items") or []:
        link = str(p.get("link") or p.get("url") or "").strip()
        if not link:
            continue
        title = p.get("title")
        if isinstance(title, dict):
            title = title.get("rendered") or ""
        items.append({
            "url": link,
            "title": str(title or "")[:200],
            "slug": str(p.get("slug") or ""),
        })
    return JSONResponse({"ok": True, "items": items})


@router.post("/content-ai/auto-update/modal/assistant/apply")
def api_modal_assistant_apply(
    body: AssistantApplyBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Apply one structured patch. Never charges credit."""
    from app.services.cau_assistant_patches import ContentPatch, apply_patch
    from app.services.cau_block_model import serialize_blocks

    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    patch = ContentPatch.from_dict(body.patch or {})
    new_blocks, updated, err = apply_patch(blocks, patch)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse({
        "ok": True,
        "patch": updated.to_dict(),
        "blocks": [b.to_dict() for b in new_blocks],
        "content_html": serialize_blocks(new_blocks),
        "credits_charged": 0,
    })


@router.post("/content-ai/auto-update/modal/assistant/undo")
def api_modal_assistant_undo(
    body: AssistantUndoBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Undo one or all applied patches. Never charges credit."""
    from app.services.cau_assistant_patches import ContentPatch, undo_all_patches, undo_patch
    from app.services.cau_block_model import serialize_blocks

    blocks = _cau_assistant_blocks(body.content_html, body.blocks)
    if body.undo_all or body.patches:
        new_blocks, updated = undo_all_patches(blocks, body.patches or ([body.patch] if body.patch else []))
        return JSONResponse({
            "ok": True,
            "patches": [p.to_dict() for p in updated],
            "blocks": [b.to_dict() for b in new_blocks],
            "content_html": serialize_blocks(new_blocks),
            "credits_charged": 0,
        })
    patch = ContentPatch.from_dict(body.patch or {})
    new_blocks, updated, err = undo_patch(blocks, patch)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse({
        "ok": True,
        "patch": updated.to_dict(),
        "blocks": [b.to_dict() for b in new_blocks],
        "content_html": serialize_blocks(new_blocks),
        "credits_charged": 0,
    })
