import re
import csv
import io
import random
import mimetypes
import unicodedata
import base64
import os
import json
import time
import html as py_html
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import dotenv_values

from app.db import get_db, SessionLocal
from app.models.user import User
from sqlalchemy.orm import Session

from app.services.saas_pricing_service import get_pricing_plans
from app.seo_pipeline.constants import CHECKLIST_TITLE_VI
from app.services.auth import get_current_user
from app.services.rbac import require_write_user
from app.services.trial_access import require_active_trial
from app.services.content_ai_entitlement import (
    assert_content_ai_feature,
    build_content_ai_usage,
    feature_for_suggest_field,
    record_content_ai_usage,
)
from app.schemas.saas import ContentAiUsageResponse
from app.services.security_audit_log import log_audit_event
from app.services.user_data_paths import user_upload_dir, user_upload_relative_path
from app.services.user_scope import assert_job_access
from app.services.content_ai_project_store import (
    delete_content_ai_project,
    get_content_ai_project,
    list_content_ai_projects,
    save_content_ai_project,
    upsert_bulk_setup_projects,
)
from app.services.content_ai_content_images import (
    auto_insert_images_to_project,
    count_content_images,
    _resolve_project_content,
)
from app.services.content_ai_google_thumbnail import fetch_and_attach_google_thumbnail
from app.services.content_ai_thumbnail import generate_and_attach_project_thumbnail
from app.services.content_ai_image_studio import (
    generate_professional_previews,
    insert_selected_image,
    studio_catalog,
)
from app.services.google_cse_images import import_remote_image_url
from app.services.web_image_search import image_search_status, search_web_images
from app.services.content_draft_builder import build_draft_payload, detect_search_intent, suggest_content_ai_field
from app.services.llm_content_writer import (
    generate_content_ai_suggestion,
    generate_seo_article_json,
    load_llm_config,
    optimize_seo_content_html,
    rewrite_html_insert_internal_links,
    suggest_internal_link_row_keywords,
)
from app.services.wp_internal_link_apply import apply_merged_internal_links
from app.services.wp_internal_link_scoring import (
    compute_relevance_score,
    suggest_natural_anchor,
)
from app.routers.settings_api import (
    HaravanConnectionBody,
    WordPressConnectionBody,
    _check_haravan_site,
    _check_wp_site,
    _haravan_sync_blogs_count,
    _wp_posts_count,
)

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "technical_audit_catalog.json"


def _load_technical_audit_catalog() -> dict[str, Any]:
    """Đọc khung tiêu chí audit (sidebar + pillar view) — không chặn trang nếu file lỗi."""
    try:
        if not _CATALOG_PATH.is_file():
            return {}
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_llm_transient_error(exc: BaseException) -> bool:
    """Network/DNS/timeouts — fall back to rule-based suggest instead of 502."""
    msg = str(exc or "").lower()
    needles = (
        "nameresolution",
        "name resolution",
        "failed to resolve",
        "temporary failure in name resolution",
        "max retries exceeded",
        "connection refused",
        "connection reset",
        "connection timed out",
        "connect timeout",
        "read timed out",
        "readtimeout",
        "network is unreachable",
        "nodename nor servname",
        "getaddrinfo failed",
    )
    return any(n in msg for n in needles)


_BRIEF_SUGGEST_FIELDS = frozenset(
    {
        "title",
        "meta_description",
        "slug",
        "tags",
        "primary_keyword",
        "secondary_keywords",
        "outline_content",
        "outline",
        "target_website",
    }
)


def _content_ai_suggest_fast_enabled(request: Request) -> bool:
    q = (request.query_params.get("fast") or "").strip().lower()
    if q in {"0", "false", "no", "off"}:
        return False
    if q in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("CONTENT_AI_SUGGEST_FAST", "1").strip().lower() in ("1", "true", "yes", "on")


def _content_ai_suggest_force_llm(request: Request) -> bool:
    return (request.query_params.get("llm") or "").strip().lower() in {"1", "true", "yes", "on"}


def _should_use_llm_for_suggest(
    request: Request,
    requested: str,
    *,
    llm_cfg: object | None,
    llm_fields: set[str],
) -> bool:
    if not llm_cfg or requested not in llm_fields:
        return False
    if requested in _BRIEF_SUGGEST_FIELDS:
        if _content_ai_suggest_force_llm(request):
            return True
        if _content_ai_suggest_fast_enabled(request):
            return False
    return True


def _content_ai_llm_enabled_fields(llm_mode: str) -> set[str]:
    """
    Một nguồn cấu hình: field nào dùng LLM theo CONTENT_AI_LLM_MODE.
    Field không nằm trong tập này sẽ đi qua lớp rule (`suggest_content_ai_field`), trừ content body
    (không còn sinh rule — chỉ LLM hoặc dán qua `content_ai_normalize_pasted_body`).
    """
    m = (llm_mode or "auto").strip().lower()
    if m not in {"off", "auto", "title_meta_only", "content_only"}:
        m = "auto"
    if m == "off":
        return set()
    if m == "title_meta_only":
        return {"title", "meta_description"}
    if m == "content_only":
        return {"content", "outline_content"}
    return {"title", "meta_description", "outline_content", "content"}


@router.get("/tool", response_class=HTMLResponse)
def seo_tool_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="seo_tool.html",
        context={
            "checklist_title_vi": CHECKLIST_TITLE_VI,
            "technical_audit_catalog": _load_technical_audit_catalog(),
        },
    )


@router.get("/tool/seo-score", response_class=HTMLResponse)
def seo_url_scoreboard_page(request: Request) -> HTMLResponse:
    """Tab/dashboard chấm điểm SEO 1 URL + opportunity."""
    return templates.TemplateResponse(request=request, name="seo_url_score.html", context={})


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    """Trang cài đặt (tài khoản, API, AI, tích hợp…)."""
    resp = templates.TemplateResponse(request=request, name="settings.html", context={})
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Bảng giá SaaS — đọc từ DB, chưa thanh toán trực tuyến."""
    return templates.TemplateResponse(
        request=request,
        name="pricing.html",
        context={"plans": get_pricing_plans(db)},
    )


@router.get("/content-ai", response_class=HTMLResponse)
def content_ai_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="content_ai.html", context={})


@router.get("/social-auto", response_class=HTMLResponse)
def social_auto_page(request: Request) -> HTMLResponse:
    """Social Auto — demo UI (mock data, no backend)."""
    return templates.TemplateResponse(request=request, name="social_auto.html", context={})


@router.get("/rank-tracking", response_class=RedirectResponse)
def rank_tracking_page() -> RedirectResponse:
    return RedirectResponse(url="/keywords/tools/rank-tracking", status_code=302)


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request) -> HTMLResponse:
    """Chính sách bảo mật — yêu cầu Google OAuth verification."""
    return templates.TemplateResponse(request=request, name="privacy.html", context={})


@router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request) -> HTMLResponse:
    """Điều khoản sử dụng — yêu cầu Google OAuth verification."""
    return templates.TemplateResponse(request=request, name="terms.html", context={})


class ContentDraftRequest(BaseModel):
    title: str
    content: str
    slug: str | None = None
    tags: list[str] | None = None
    meta_description: str | None = None
    target_website: str | None = None
    primary_keyword: str | None = None
    secondary_keywords: list[str] | None = None
    outline_content: str | None = None
    target_word_count: int | None = None
    featured_image: str | None = None
    gallery_images: list[str] | None = None
    scheduled_at: str | None = None
    categories: list[int] | None = None


@router.post("/content-ai/draft")
def content_ai_draft(
    request: Request,
    payload: ContentDraftRequest,
    current_user: User = Depends(require_active_trial),
) -> Response:
    out = build_draft_payload(
        title=payload.title,
        content=payload.content,
        slug=payload.slug,
        tags=payload.tags,
        meta_description=payload.meta_description,
        target_website=payload.target_website,
        primary_keyword=payload.primary_keyword,
        secondary_keywords=payload.secondary_keywords,
        outline_content=payload.outline_content,
        featured_image=payload.featured_image,
        gallery_images=payload.gallery_images,
        scheduled_at=payload.scheduled_at,
        categories=payload.categories,
    )
    project_id = save_content_ai_project(
        user_id=current_user.id,
        source_payload=payload.model_dump(),
        draft_payload=out,
    )
    log_audit_event(
        action="project.create",
        user_id=current_user.id,
        resource_type="content_ai_project",
        resource_id=str(project_id or ""),
        request=request,
    )
    out_response = dict(out)
    out_response["project_id"] = project_id
    fmt = (request.query_params.get("format") or "").strip().lower()
    if fmt == "text":
        # Return the generated article body only (useful for copying/pasting)
        return Response(content=str(out.get("content") or ""), media_type="text/plain; charset=utf-8")
    return JSONResponse(content=out_response)


@router.post("/content-ai/upload-image")
async def content_ai_upload_image(
    file: UploadFile = File(...),
    project_id: str | None = None,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="Chi ho tro file anh jpg/jpeg/png/webp/gif.")

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-").lower() or "image"
    target_name = f"{safe_stem}-{uuid4().hex[:8]}{suffix}"
    target_dir = user_upload_dir(current_user.id, project_id=project_id)
    target_file = target_dir / target_name

    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File anh vuot qua 10MB.")
    target_file.write_bytes(data)
    rel = user_upload_relative_path(project_id=project_id, filename=target_name)
    return JSONResponse(
        content={
            "url": f"/api/user-files/{current_user.id}/{rel}",
            "name": target_name,
        }
    )


class GoogleImageSearchResponse(BaseModel):
    items: list[dict]
    source: str = "google_cse_image"


def _web_image_search(*, q: str, num: int = 8) -> tuple[list[dict], str]:
    try:
        return search_web_images(q=q, num=num)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/content-ai/google-images/status")
def content_ai_google_images_status(
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Kiểm tra Google CSE + Bing fallback."""
    return JSONResponse(content=image_search_status())


@router.get("/content-ai/google-images/search")
def content_ai_google_images_search(
    q: str = "",
    num: int = 8,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    items, source = _web_image_search(q=q, num=num)
    return JSONResponse(content={"items": items, "source": source})


class GoogleImageImportRequest(BaseModel):
    url: str


@router.post("/content-ai/google-images/import")
def content_ai_google_images_import(
    payload: GoogleImageImportRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    try:
        local_url = import_remote_image_url(
            str(payload.url or "").strip(),
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Không tải được ảnh: {exc}") from exc
    name = Path(local_url).name
    return JSONResponse(content={"url": local_url, "name": name})


@router.get("/content-ai/projects")
def content_ai_projects(
    limit: int = 30,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return JSONResponse(
        content={"items": list_content_ai_projects(user_id=current_user.id, limit=max(1, min(limit, 500)))}
    )


@router.get("/content-ai/usage", response_model=ContentAiUsageResponse)
def content_ai_usage(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContentAiUsageResponse:
    """Current Content AI quota snapshot for the usage widget."""
    snap = build_content_ai_usage(db, current_user)
    return ContentAiUsageResponse(
        user_id=snap["user_id"],
        usage_month=snap["usage_month"],
        plan_slug=snap.get("plan_slug"),
        plan_name=snap.get("plan_name"),
        enforcement_enabled=bool(snap.get("enforcement_enabled")),
        bypass_entitlement=bool(snap.get("bypass_entitlement")),
        items=snap.get("items") or [],
        any_warning=bool(snap.get("any_warning")),
        any_over_quota=bool(snap.get("any_over_quota")),
    )


class ContentAiBulkItemRequest(BaseModel):
    keyword: str
    custom_title: str | None = None
    custom_description: str | None = None
    custom_outline: str | None = None
    search_volume: int | None = None
    content_type: str | None = None
    competitor_url: str | None = None
    target_word_count: int | None = None
    secondary_keywords: list[str] | None = None
    wp_category_id: int | None = None


class ContentAiBulkStartRequest(BaseModel):
    keywords: list[str] = []
    items: list[ContentAiBulkItemRequest] | None = None
    target_website: str | None = None
    target_word_count: int | None = 1000
    secondary_keywords: list[str] | None = None
    brand_name: str | None = None
    wp_category_id: int | None = None


@router.get("/content-ai/bulk-jobs/ping")
def content_ai_bulk_jobs_ping() -> JSONResponse:
    return JSONResponse(content={"ok": True, "feature": "content_ai_bulk"})


@router.post("/content-ai/bulk-import/file")
async def content_ai_bulk_import_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Upload .xlsx / .txt / .csv → danh sách bulk items theo form Content AI."""
    from app.services.content_ai_bulk_import import parse_bulk_upload_file

    name = str(file.filename or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu tên file.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File trống.")
    if len(raw) > 12_000_000:
        raise HTTPException(status_code=413, detail="File quá lớn (tối đa 12MB).")
    try:
        items, fmt = parse_bulk_upload_file(filename=name, raw=raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Không đọc được file: {exc}") from exc
    if not items:
        raise HTTPException(
            status_code=422,
            detail="Không tìm thấy dòng từ khóa hợp lệ. Kiểm tra cột keyword / từ khóa.",
        )
    return JSONResponse(
        content={
            "items": items,
            "meta": {"count": len(items), "format": fmt, "filename": name},
        }
    )


@router.post("/content-ai/bulk-setup/save")
def content_ai_bulk_setup_save(
    payload: ContentAiBulkStartRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Lưu danh sách setup bulk (chưa content) vào dự án — hiển thị tab Lưu nháp."""
    site = str(payload.target_website or "").strip()
    if not site:
        raise HTTPException(status_code=400, detail="Thiếu Target website.")
    item_dicts: list[dict[str, Any]] = []
    if payload.items:
        for it in payload.items:
            kw = str(it.keyword or "").strip()
            if not kw:
                continue
            try:
                wpc_it = int(it.wp_category_id or 0)
            except (TypeError, ValueError):
                wpc_it = 0
            item_dicts.append(
                {
                    "keyword": kw,
                    "custom_title": str(it.custom_title or "").strip(),
                    "custom_description": str(it.custom_description or "").strip(),
                    "custom_outline": str(it.custom_outline or "").strip(),
                    "search_volume": int(it.search_volume or 0),
                    "content_type": str(it.content_type or "").strip(),
                    "competitor_url": str(it.competitor_url or "").strip(),
                    "target_word_count": int(it.target_word_count or 0),
                    "secondary_keywords": list(it.secondary_keywords or []),
                    "wp_category_id": wpc_it if wpc_it > 0 else 0,
                }
            )
    if not item_dicts:
        kw_raw = [str(k or "").strip() for k in (payload.keywords or []) if str(k or "").strip()]
        item_dicts = [{"keyword": k} for k in kw_raw]
    if not item_dicts:
        raise HTTPException(status_code=400, detail="Danh sách từ khóa trống.")
    saved = upsert_bulk_setup_projects(
        user_id=current_user.id,
        target_website=site,
        items=item_dicts,
    )
    return JSONResponse(content={"saved": len(saved), "items": saved})


@router.post("/content-ai/bulk-jobs/start")
def content_ai_bulk_jobs_start(
    payload: ContentAiBulkStartRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    from app.services.job_store import (
        cleanup_expired,
        create_job,
        ensure_job_schema,
        get_job,
        mark_stale_jobs_failed,
        mark_stale_queued_failed,
    )

    from app.services.content_ai_bulk_parse import normalize_bulk_job_items

    kw_raw = [str(k or "").strip() for k in (payload.keywords or []) if str(k or "").strip()]
    item_dicts: list[dict[str, Any]] = []
    if payload.items:
        for it in payload.items:
            kw = str(it.keyword or "").strip()
            if not kw:
                continue
            try:
                wpc_it = int(it.wp_category_id or 0)
            except (TypeError, ValueError):
                wpc_it = 0
            item_dicts.append(
                {
                    "keyword": kw,
                    "custom_title": str(it.custom_title or "").strip(),
                    "custom_description": str(it.custom_description or "").strip(),
                    "custom_outline": str(it.custom_outline or "").strip(),
                    "search_volume": int(it.search_volume or 0),
                    "content_type": str(it.content_type or "").strip(),
                    "competitor_url": str(it.competitor_url or "").strip(),
                    "target_word_count": int(it.target_word_count or 0),
                    "secondary_keywords": list(it.secondary_keywords or []),
                    "wp_category_id": wpc_it if wpc_it > 0 else 0,
                }
            )
    bulk_rows = normalize_bulk_job_items(keywords=kw_raw, items=item_dicts or None)
    keywords = [r["keyword"] for r in bulk_rows]
    if not keywords:
        raise HTTPException(status_code=400, detail="Cần ít nhất một từ khóa.")
    if len(keywords) > 200:
        raise HTTPException(status_code=400, detail="Tối đa 200 từ khóa mỗi lần chạy.")

    assert_content_ai_feature(db, current_user, "content_ai_bulk_article", quantity=1)

    ensure_job_schema()
    cleanup_expired(ttl_seconds=int(os.getenv("JOB_TTL_SECONDS", "86400")))
    mark_stale_jobs_failed(stale_seconds=int(os.getenv("JOB_WATCHDOG_SECONDS", "900")))
    mark_stale_queued_failed(stale_seconds=int(os.getenv("JOB_QUEUE_STALE_SECONDS", "180")))

    try:
        wpc = int(payload.wp_category_id or 0)
    except (TypeError, ValueError):
        wpc = 0
    job_payload: dict[str, Any] = {
        "user_id": current_user.id,
        "keywords": keywords,
        "items": bulk_rows,
        "target_website": (payload.target_website or "").strip(),
        "target_word_count": payload.target_word_count or 1000,
        "secondary_keywords": payload.secondary_keywords or [],
        "brand_name": (payload.brand_name or "").strip(),
        "wp_category_id": wpc if wpc > 0 else 0,
    }
    job = create_job(job_type="content_ai_bulk", message="Đã xếp hàng — chờ viết bài", payload=job_payload)
    st = get_job(job.job_id)
    record_content_ai_usage(
        db,
        current_user,
        "content_ai_bulk_article",
        quantity=1,
        metadata={"job_id": job.job_id, "keyword_count": len(keywords)},
        idempotency_key=f"bulk-start:{job.job_id}",
    )
    db.commit()
    return JSONResponse(
        content={
            "job_id": job.job_id,
            "state": st.state if st else job.state,
            "progress": st.progress if st else job.progress,
            "message": st.message if st else job.message,
            "keyword_count": len(keywords),
            "poll_url": f"/content-ai/bulk-jobs/{job.job_id}",
            "note": "Job chạy trên server — có thể tắt trình duyệt/máy cá nhân nếu server (Laragon) vẫn bật.",
        }
    )


@router.get("/content-ai/bulk-jobs/{job_id}")
def content_ai_bulk_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.job_store import (
        cleanup_expired,
        ensure_job_schema,
        get_job,
        mark_stale_jobs_failed,
        mark_stale_queued_failed,
    )

    ensure_job_schema()
    cleanup_expired(ttl_seconds=int(os.getenv("JOB_TTL_SECONDS", "86400")))
    mark_stale_jobs_failed(stale_seconds=int(os.getenv("JOB_WATCHDOG_SECONDS", "900")))
    mark_stale_queued_failed(stale_seconds=int(os.getenv("JOB_QUEUE_STALE_SECONDS", "180")))
    st = get_job(job_id)
    if not st:
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    assert_job_access(st.payload or {}, current_user.id)
    out: dict[str, Any] = {
        "job_id": st.job_id,
        "job_type": st.job_type,
        "state": st.state,
        "progress": st.progress,
        "message": st.message,
    }
    if st.state == "SUCCESS" and st.result is not None:
        out["result"] = st.result
    if st.state == "ERROR":
        out["error"] = st.error or "Unknown error"
    return JSONResponse(content=out)


@router.get("/content-ai/projects/{project_id}")
def content_ai_project_detail(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    project = get_content_ai_project(project_id, user_id=current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án content.")
    return JSONResponse(content=project)


@router.delete("/content-ai/projects/{project_id}")
def content_ai_project_delete(
    request: Request,
    project_id: str,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    if not delete_content_ai_project(project_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án content để xóa.")
    log_audit_event(
        action="project.delete",
        user_id=current_user.id,
        resource_type="content_ai_project",
        resource_id=project_id,
        request=request,
    )
    return JSONResponse(content={"ok": True})


@router.post("/content-ai/projects/{project_id}/delete")
def content_ai_project_delete_post(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    if not delete_content_ai_project(project_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án content để xóa.")
    return JSONResponse(content={"ok": True})


@router.post("/content-ai/projects/{project_id}/generate-thumbnail")
def content_ai_project_generate_thumbnail(
    project_id: str,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Tự động tìm ảnh theo ngữ cảnh + chèn vào content + thumbnail."""
    try:
        out = fetch_and_attach_google_thumbnail(project_id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lấy ảnh thất bại: {exc}") from exc
    return JSONResponse(content=out)


class ContentAiAutoInsertImagesRequest(BaseModel):
    max_inline: int = 4
    update_featured: bool = True
    force: bool = False


@router.post("/content-ai/projects/{project_id}/auto-insert-images")
def content_ai_project_auto_insert_images(
    project_id: str,
    payload: ContentAiAutoInsertImagesRequest | None = None,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Tự động chèn ảnh minh họa vào bài (theo từ khóa, tiêu đề, các mục H2)."""
    body = payload or ContentAiAutoInsertImagesRequest()
    try:
        out = auto_insert_images_to_project(
            project_id,
            user_id=current_user.id,
            max_inline=max(0, min(int(body.max_inline or 4), 6)),
            update_featured=bool(body.update_featured),
            force=bool(body.force),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chèn ảnh tự động thất bại: {exc}") from exc
    return JSONResponse(content=out)


class ContentAiAutoInsertImagesBatchRequest(BaseModel):
    project_ids: list[str] | None = None
    max_inline: int = 4
    only_without_images: bool = False


@router.post("/content-ai/projects/auto-insert-images")
def content_ai_projects_auto_insert_images_batch(
    payload: ContentAiAutoInsertImagesBatchRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    uid = current_user.id
    ids = [str(x or "").strip() for x in (payload.project_ids or []) if str(x or "").strip()]
    if not ids:
        rows = list_content_ai_projects(user_id=uid, limit=200)
        ids = [str(r.get("id") or "") for r in rows if str(r.get("id") or "")]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for pid in ids:
        if payload.only_without_images:
            row = get_content_ai_project(pid, user_id=uid)
            if row:
                html = _resolve_project_content(row)
                if count_content_images(html) >= 2:
                    results.append({"project_id": pid, "skipped": True, "reason": "already_has_images"})
                    continue
        try:
            out = auto_insert_images_to_project(
                pid,
                user_id=uid,
                max_inline=max(0, min(int(payload.max_inline or 4), 6)),
                update_featured=True,
                force=False,
            )
            results.append(
                {
                    "project_id": pid,
                    "ok": True,
                    "inline_images_count": out.get("inline_images_count"),
                    "featured_image": out.get("featured_image"),
                }
            )
        except Exception as exc:
            errors.append({"project_id": pid, "error": str(exc)})
    return JSONResponse(content={"results": results, "errors": errors})


@router.post("/content-ai/auto-insert-images")
def content_ai_auto_insert_images_live(
    payload: ContentDraftRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Chèn ảnh cho bài đang soạn (chưa cần lưu project) — trả content HTML đã chèn ảnh."""
    from app.services.content_ai_content_images import enrich_project_with_context_images

    project_like = payload.model_dump()
    if not str(project_like.get("content") or "").strip():
        raise HTTPException(status_code=400, detail="Content trống — không thể chèn ảnh.")
    if not str(project_like.get("primary_keyword") or "").strip():
        raise HTTPException(status_code=400, detail="Cần từ khóa chính.")
    try:
        enriched = enrich_project_with_context_images(project_like, max_inline=4, update_featured=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chèn ảnh thất bại: {exc}") from exc
    return JSONResponse(
        content={
            "ok": True,
            "content": enriched.get("content") or "",
            "featured_image": enriched.get("featured_image") or "",
            "gallery_images": enriched.get("gallery_images") or [],
            "inline_images_count": enriched.get("inline_images_count") or 0,
            "source": enriched.get("image_source") or "",
        }
    )


@router.post("/content-ai/projects/{project_id}/generate-thumbnail-ai")
def content_ai_project_generate_thumbnail_ai(
    project_id: str,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    try:
        out = generate_and_attach_project_thumbnail(project_id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tạo thumbnail AI thất bại: {exc}") from exc
    return JSONResponse(content=out)


class ContentAiStudioGenerateRequest(BaseModel):
    project_id: str | None = None
    title: str = ""
    primary_keyword: str = ""
    secondary_keywords: list[str] | None = None
    content_html: str = ""
    outline_content: str = ""
    section_heading: str = ""
    h2_index: int | None = None
    h2_headings: list[str] | None = None
    h2_indices: list[int] | None = None
    target_audience: str = ""
    industry: str = ""
    brand_name: str = ""
    brand_tone: str = "professional"
    image_type: str = "inline_h2"
    style_preset: str = "seo_3d_premium"
    aspect_ratio: str = "16:9"
    custom_width: int | None = None
    custom_height: int | None = None
    count: int = 3
    include_text: bool = False
    text_hint: str = ""


@router.get("/content-ai/images/studio-presets")
def content_ai_images_studio_presets(
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    return JSONResponse(content=studio_catalog())


@router.post("/content-ai/images/generate-professional")
def content_ai_images_generate_professional(
    payload: ContentAiStudioGenerateRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """AI Visual Content Studio — tạo 2–4 preview, không chèn vào bài."""
    assert_content_ai_feature(db, current_user, "image_generate", quantity=1)
    try:
        out = generate_professional_previews(
            user_id=current_user.id,
            title=payload.title,
            primary_keyword=payload.primary_keyword,
            secondary_keywords=payload.secondary_keywords,
            content_html=payload.content_html,
            outline_content=payload.outline_content,
            section_heading=payload.section_heading,
            h2_index=payload.h2_index,
            h2_headings=payload.h2_headings,
            h2_indices=payload.h2_indices,
            target_audience=payload.target_audience,
            industry=payload.industry,
            brand_name=payload.brand_name,
            brand_tone=payload.brand_tone,
            image_type=payload.image_type,
            style_preset=payload.style_preset,
            aspect_ratio=payload.aspect_ratio,
            custom_width=payload.custom_width,
            custom_height=payload.custom_height,
            count=max(2, min(int(payload.count or 3), 4)),
            include_text=bool(payload.include_text),
            text_hint=payload.text_hint,
            project_id=payload.project_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 503 if "OPENAI_API_KEY" in msg or "Model ảnh" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tạo ảnh AI thất bại: {exc}") from exc
    record_content_ai_usage(
        db,
        current_user,
        "image_generate",
        quantity=1,
        metadata={"preview_count": len(out.get("previews") or []) if isinstance(out, dict) else 0},
    )
    db.commit()
    return JSONResponse(content=out)


class ContentAiStudioInsertRequest(BaseModel):
    url: str
    mode: str = "inline"
    project_id: str | None = None
    content_html: str = ""
    title: str = ""
    primary_keyword: str = ""
    section_heading: str = ""
    h2_index: int | None = None
    alt: str = ""
    caption: str = ""


@router.post("/content-ai/images/insert-selected")
def content_ai_images_insert_selected(
    payload: ContentAiStudioInsertRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Chèn ảnh đã chọn từ studio vào content hoặc featured."""
    try:
        out = insert_selected_image(
            user_id=current_user.id,
            url=payload.url,
            mode=payload.mode,
            project_id=payload.project_id,
            content_html=payload.content_html,
            title=payload.title,
            primary_keyword=payload.primary_keyword,
            section_heading=payload.section_heading,
            h2_index=payload.h2_index,
            alt=payload.alt,
            caption=payload.caption,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chèn ảnh thất bại: {exc}") from exc
    return JSONResponse(content=out)


class ContentAiGenerateThumbnailsBatchRequest(BaseModel):
    project_ids: list[str] | None = None
    only_missing: bool = True


@router.post("/content-ai/projects/generate-thumbnails")
def content_ai_projects_generate_thumbnails_batch(
    payload: ContentAiGenerateThumbnailsBatchRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    uid = current_user.id
    ids = [str(x or "").strip() for x in (payload.project_ids or []) if str(x or "").strip()]
    if not ids:
        rows = list_content_ai_projects(user_id=uid, limit=200)
        ids = [str(r.get("id") or "") for r in rows if str(r.get("id") or "")]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for pid in ids:
        if payload.only_missing:
            row = get_content_ai_project(pid, user_id=uid)
            if row and str(row.get("featured_image") or "").strip():
                results.append({"project_id": pid, "skipped": True, "featured_image": row.get("featured_image")})
                continue
        try:
            out = fetch_and_attach_google_thumbnail(pid, user_id=uid)
            results.append(
                {
                    "project_id": pid,
                    "ok": True,
                    "featured_image": out.get("featured_image"),
                    "source": out.get("source"),
                }
            )
        except Exception as exc:
            errors.append({"project_id": pid, "error": str(exc)})
    return JSONResponse(content={"results": results, "errors": errors})


@router.get("/content-ai/projects/{project_id}/export.csv")
def content_ai_project_export_csv(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    project = get_content_ai_project(project_id, user_id=current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án content.")
    out = io.StringIO()
    out.write("\ufeff")
    fields = [
        "id",
        "created_at",
        "title",
        "slug",
        "target_website",
        "primary_keyword",
        "secondary_keywords",
        "meta_description",
        "tags",
        "featured_image",
        "gallery_images",
        "scheduled_at",
        "outline_content",
        "content",
    ]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerow(
        {
            "id": project.get("id") or "",
            "created_at": project.get("created_at") or "",
            "title": project.get("title") or "",
            "slug": project.get("slug") or "",
            "target_website": project.get("target_website") or "",
            "primary_keyword": project.get("primary_keyword") or "",
            "secondary_keywords": ", ".join(project.get("secondary_keywords") or []),
            "meta_description": project.get("meta_description") or "",
            "tags": ", ".join(project.get("tags") or []),
            "featured_image": project.get("featured_image") or "",
            "gallery_images": ", ".join(project.get("gallery_images") or []),
            "scheduled_at": project.get("scheduled_at") or "",
            "outline_content": project.get("outline_content") or "",
            "content": project.get("content") or "",
        }
    )
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(project.get("primary_keyword") or "content-ai")).strip("-").lower()
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="content-ai-{safe}.csv"'},
    )


@router.get("/content-ai/projects/{project_id}/export.gsheet")
def content_ai_project_export_gsheet(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    project = get_content_ai_project(project_id, user_id=current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án content.")
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out, delimiter="\t")
    writer.writerow(
        [
            "id",
            "created_at",
            "title",
            "slug",
            "target_website",
            "primary_keyword",
            "secondary_keywords",
            "meta_description",
            "tags",
            "featured_image",
            "gallery_images",
            "scheduled_at",
            "outline_content",
            "content",
        ]
    )
    writer.writerow(
        [
            project.get("id") or "",
            project.get("created_at") or "",
            project.get("title") or "",
            project.get("slug") or "",
            project.get("target_website") or "",
            project.get("primary_keyword") or "",
            ", ".join(project.get("secondary_keywords") or []),
            project.get("meta_description") or "",
            ", ".join(project.get("tags") or []),
            project.get("featured_image") or "",
            ", ".join(project.get("gallery_images") or []),
            project.get("scheduled_at") or "",
            project.get("outline_content") or "",
            project.get("content") or "",
        ]
    )
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(project.get("primary_keyword") or "content-ai")).strip("-").lower()
    return Response(
        content=out.getvalue(),
        media_type="text/tab-separated-values; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="content-ai-{safe}-gsheet.tsv"'},
    )


class ContentSuggestRequest(BaseModel):
    field: str
    title: str | None = None
    content: str | None = None
    target_website: str | None = None
    slug: str | None = None
    tags: str | None = None
    meta_description: str | None = None
    primary_keyword: str | None = None
    secondary_keywords: str | None = None
    outline_content: str | None = None
    target_word_count: int | None = None


class SeoArticleJsonRequest(BaseModel):
    keyword: str
    secondary_keywords: list[str] | None = None
    intent: str | None = None
    audience: str | None = None
    brand_name: str | None = None
    outline: str | None = None
    context_data: str | None = None


class SeoOptimizeHtmlRequest(BaseModel):
    content_html: str


class ContentPostprocessRequest(BaseModel):
    content_html: str


class PublishChecklistRequest(BaseModel):
    title: str = ""
    meta_description: str = ""
    content_html: str = ""
    primary_keyword: str = ""
    slug: str = ""
    secondary_keywords: list[str] | None = None


@router.post("/content-ai/publish-checklist")
def content_ai_publish_checklist(
    payload: PublishChecklistRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Checklist SEO trước publish — chỉ trả JSON cho UI, không ghi vào bài."""
    from app.services.content_ai_publish_checklist import evaluate_publish_checklist

    data = evaluate_publish_checklist(
        title=payload.title,
        meta_description=payload.meta_description,
        content_html=payload.content_html,
        primary_keyword=payload.primary_keyword,
        slug=payload.slug,
        secondary_keywords=payload.secondary_keywords,
    )
    return JSONResponse(content=data)


@router.post("/content-ai/postprocess-content")
def content_ai_postprocess_content(
    payload: ContentPostprocessRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """Post-process article HTML (auto blockquotes by word count)."""
    from app.services.content_blockquote_postprocess import postprocess_content_blockquotes, postprocess_stats
    from app.services.content_ai_publish_checklist import strip_publish_checklist_from_html
    from app.services.content_table_format import enhance_tables_in_html

    raw = str(payload.content_html or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Thiếu content_html.")
    out = postprocess_content_blockquotes(raw)
    out = strip_publish_checklist_from_html(out)
    out = enhance_tables_in_html(out)
    stats = postprocess_stats(out)
    return JSONResponse(content={"content_html": out, "stats": stats})


@router.post("/content-ai/article-json")
def content_ai_article_json(
    payload: SeoArticleJsonRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    """
    Generate a full SEO article as a strict JSON payload.
    """
    try:
        data = generate_seo_article_json(
            keyword=payload.keyword,
            secondary_keywords=payload.secondary_keywords,
            intent=payload.intent or "",
            audience=payload.audience or "",
            brand_name=payload.brand_name or "",
            outline=payload.outline or "",
            context_data=payload.context_data or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:900]) from exc
    return JSONResponse(content=data)


@router.post("/content-ai/optimize-html")
def content_ai_optimize_html(
    payload: SeoOptimizeHtmlRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    try:
        from app.services.content_ai_publish_checklist import strip_publish_checklist_from_html

        out = optimize_seo_content_html(content_html=payload.content_html)
        out = strip_publish_checklist_from_html(out)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:900]) from exc
    return JSONResponse(content={"content_html": out})


class InternalLinkRequest(BaseModel):
    content_html: str
    target_website: str
    primary_keyword: str | None = None
    current_url: str | None = None
    current_slug: str | None = None
    max_links: int | None = 4


class InternalLinkCandidateRequest(BaseModel):
    target_website: str
    primary_keyword: str | None = None
    secondary_keywords: str | None = None
    content_html: str | None = None  # HTML bài đang soạn: anchor + seed search
    current_url: str | None = None
    current_slug: str | None = None
    limit: int | None = 15


class InternalLinkCustomItem(BaseModel):
    target_url: str
    anchor_text: str
    link_type: str | None = "manual"  # money_page | blog | category | service | course | manual
    priority: str | None = "medium"  # high | medium | low
    max_insert: int | None = 1


class InternalLinkApplyRequest(BaseModel):
    content_html: str
    target_website: str
    selected_posts: list[dict] = []
    custom_links: list[dict] | None = None
    current_url: str | None = None
    article_primary_keyword: str | None = None
    article_secondary_keywords: str | None = None
    use_llm_rewrite: bool | None = False  # True = LLM viết đoạn ngắn + chèn anchor (không dùng popup Tham khảo thêm)
    apply_mode: str | None = "full"  # full | append_only
    append_lead: str | None = "Tham khảo thêm:"
    confirmed_append_urls: list[str] | None = None


class InternalLinkRowHintRequest(BaseModel):
    target_title: str
    target_link: str
    target_categories: str | None = ""
    target_tags: str | None = ""
    article_primary_keyword: str | None = ""
    article_secondary_keywords: str | None = ""
    content_snippet: str | None = ""


def _normalize_site_base(raw: str) -> str:
    v = str(raw or "").strip()
    if not v:
        return ""
    try:
        p = urlparse(v if "://" in v else f"https://{v}")
        if p.scheme not in {"http", "https"} or not p.netloc:
            return ""
        return f"{p.scheme}://{p.netloc}".rstrip("/")
    except Exception:
        return ""


def _norm_url_for_compare(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw if "://" in raw else f"https://x.local/{raw.lstrip('/')}")
        path = re.sub(r"/{2,}", "/", p.path or "/").rstrip("/")
        return f"{(p.netloc or '').lower()}{path.lower()}"
    except Exception:
        return raw.lower().rstrip("/")


def _fetch_wp_term_map(base: str, taxonomy: str, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    out: dict[int, str] = {}
    chunk: list[int] = []
    for i in sorted(ids):
        chunk.append(i)
        if len(chunk) >= 80:
            try:
                r = requests.get(
                    f"{base}/wp-json/wp/v2/{taxonomy}",
                    params={"include": ",".join(str(x) for x in chunk), "per_page": len(chunk), "_fields": "id,name"},
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if r.status_code < 400:
                    data = r.json() if r.content else []
                    if isinstance(data, list):
                        for it in data:
                            try:
                                out[int(it.get("id"))] = str(it.get("name") or "").strip()
                            except Exception:
                                pass
            except Exception:
                pass
            chunk = []
    if chunk:
        try:
            r = requests.get(
                f"{base}/wp-json/wp/v2/{taxonomy}",
                params={"include": ",".join(str(x) for x in chunk), "per_page": len(chunk), "_fields": "id,name"},
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code < 400:
                data = r.json() if r.content else []
                if isinstance(data, list):
                    for it in data:
                        try:
                            out[int(it.get("id"))] = str(it.get("name") or "").strip()
                        except Exception:
                            pass
        except Exception:
            pass
    return out


def _fetch_related_posts_wp(base: str, keyword: str, *, limit: int = 10) -> list[dict]:
    api = f"{base}/wp-json/wp/v2/posts"
    params = {
        "per_page": max(3, min(limit, 30)),
        "_fields": "link,title.rendered,slug,categories,tags,meta",
        "orderby": "date",
        "order": "desc",
    }
    if keyword:
        params["search"] = keyword
    try:
        r = requests.get(api, params=params, timeout=18, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code >= 400:
            return []
        data = r.json() if r.content else []
    except Exception:
        return []
    out: list[dict] = []
    if not isinstance(data, list):
        return out
    cat_ids: set[int] = set()
    tag_ids: set[int] = set()
    for it in data:
        if not isinstance(it, dict):
            continue
        link = str(it.get("link") or "").strip()
        title_obj = it.get("title") or {}
        title = str((title_obj.get("rendered") if isinstance(title_obj, dict) else "") or "").strip()
        title_txt = BeautifulSoup(title, "html.parser").get_text(" ", strip=True)
        cats = [int(x) for x in (it.get("categories") or []) if str(x).isdigit()]
        tags = [int(x) for x in (it.get("tags") or []) if str(x).isdigit()]
        cat_ids.update(cats)
        tag_ids.update(tags)
        slug = str(it.get("slug") or "").strip()
        focus_kw = _focus_keyword_from_wp_item(it)
        if link and title_txt:
            out.append(
                {
                    "link": link,
                    "title": title_txt,
                    "slug": slug,
                    "focus_keyword": focus_kw,
                    "categories": cats,
                    "tags": tags,
                }
            )
    cat_map = _fetch_wp_term_map(base, "categories", cat_ids)
    tag_map = _fetch_wp_term_map(base, "tags", tag_ids)
    for it in out:
        it["category_names"] = [cat_map.get(int(cid), "") for cid in (it.get("categories") or []) if cat_map.get(int(cid), "")]
        it["tag_names"] = [tag_map.get(int(tid), "") for tid in (it.get("tags") or []) if tag_map.get(int(tid), "")]
    return out


def _merge_wp_related_posts(
    base: str,
    seeds: list[str],
    *,
    per_seed: int = 16,
    cap: int = 48,
) -> list[dict]:
    """Gọi WP REST search theo nhiều seed (từ khóa + cụm trong content), gộp theo URL."""
    seen: set[str] = set()
    merged: list[dict] = []
    for s in seeds:
        if len(merged) >= cap:
            break
        chunk = _fetch_related_posts_wp(base, str(s or "").strip(), limit=per_seed)
        for p in chunk:
            if not isinstance(p, dict):
                continue
            link = str(p.get("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            merged.append(p)
    return merged


def _serp_sitemap_wp_posts_fallback(base: str, topic: str, *, limit: int = 15) -> list[dict]:
    """Fallback khi WP REST ít kết quả — SERP site: + sitemap (giống pipeline draft)."""
    from app.services.content_draft_builder import _fetch_related_internal_posts_for_injection

    rows = _fetch_related_internal_posts_for_injection(
        target_website=base,
        topic=str(topic or "").strip() or base,
        max_posts=max(3, min(int(limit or 15), 25)),
    )
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        link = str(r.get("url") or r.get("link") or "").strip()
        title = str(r.get("title") or "").strip()
        if not link:
            continue
        slug = ""
        try:
            slug = (urlparse(link).path or "").strip("/").split("/")[-1]
        except Exception:
            pass
        out.append(
            {
                "link": link,
                "title": title or slug.replace("-", " "),
                "slug": slug,
                "category_names": [],
                "tag_names": [],
            }
        )
    return out


def _merge_posts_by_link(posts: list[dict], extra: list[dict]) -> list[dict]:
    seen = {str(p.get("link") or "").strip() for p in posts if str(p.get("link") or "").strip()}
    merged = list(posts)
    for p in extra:
        if not isinstance(p, dict):
            continue
        link = str(p.get("link") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        merged.append(p)
    return merged


def _scored_item_from_wp_post(
    p: dict,
    *,
    topic_seed: str,
    topic: set[str],
    plain_snip: str,
    content_html: str,
    article_primary_keyword: str = "",
    article_secondary_keywords: str = "",
    relaxed: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(p, dict):
        return None
    link = str(p.get("link") or "").strip()
    if not link:
        return None
    cand_text = " ".join(
        [
            str(p.get("title") or ""),
            " ".join(p.get("category_names") or []),
            " ".join(p.get("tag_names") or []),
            str(p.get("slug") or ""),
        ]
    )
    if not relaxed and not _same_service_topic(topic_seed, cand_text):
        return None
    score = _score_related_post(p, topic, source_text=topic_seed)
    content_kw_score = _content_keyword_match_score(plain_snip, p) if plain_snip else 0
    score += content_kw_score
    art_pk = str(article_primary_keyword or "").strip()
    art_sec = str(article_secondary_keywords or "").strip()
    rel = compute_relevance_score(
        post={**p, "focus_keyword": _focus_keyword_from_wp_item(p)},
        article_primary_keyword=art_pk,
        article_secondary_keywords=art_sec,
        article_search_intent=detect_search_intent(art_pk or topic_seed[:120]),
        content_plain=plain_snip,
        topic_tokens=topic,
    )
    relevance_score = int(rel.get("relevance_score") or 0)
    if not relaxed:
        if score <= 0 and relevance_score < 45:
            return None
        if plain_snip and content_kw_score <= 0 and score < 5 and relevance_score < 55:
            return None
    title = _clean_post_title(str(p.get("title") or ""))
    if not title:
        title = str(p.get("slug") or "").replace("-", " ").strip()
    if not title:
        link_raw = str(p.get("link") or "").strip()
        try:
            up = urlparse(link_raw)
            title = (up.path or "/").strip("/").replace("-", " ").strip()
        except Exception:
            title = link_raw
    if not title:
        title = "(Không có tiêu đề)"
    target_pk = _target_post_primary_keyword(p)
    suggested = suggest_natural_anchor(
        post={**p, "title": title, "focus_keyword": _focus_keyword_from_wp_item(p)},
        content_html=content_html,
        focus_keyword=target_pk,
    )
    anchor = suggested or target_pk or _default_anchor_text_for_post(p, content_html=content_html)
    hints = _heuristic_keyword_hints_for_post(p)
    page_type = str(rel.get("page_type") or "blog")
    priority = str(rel.get("priority") or "medium")
    return {
        "title": title,
        "link": p.get("link") or "",
        "slug": p.get("slug") or "",
        "category_names": p.get("category_names") or [],
        "tag_names": p.get("tag_names") or [],
        "target_primary_keyword": target_pk,
        "score": score,
        "content_keyword_score": content_kw_score,
        "relevance_score": relevance_score,
        "page_type": page_type,
        "priority": priority,
        "anchor_in_body": bool(rel.get("anchor_in_body")),
        "suggested_anchor": suggested or anchor,
        "anchor_text": anchor,
        "kw_hint_primary": hints["primary"] or target_pk,
        "kw_hint_secondary": hints["secondary"],
        "article_search_intent": rel.get("article_search_intent") or "",
        "target_search_intent": rel.get("target_search_intent") or "",
    }


def _extract_phrase_seeds_from_content(plain: str, *, max_phrases: int = 6) -> list[str]:
    """Lấy cụm 2–3 từ trong content (ưu tiên dài) làm seed search WP."""
    words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", str(plain or "").lower())
    if len(words) < 2:
        return []
    stop = {
        "và", "của", "cho", "với", "là", "có", "được", "trong", "này", "đó", "các", "một",
        "the", "for", "with", "from", "that", "this", "your", "you", "are", "was", "will",
    }
    seen: set[str] = set()
    out: list[str] = []
    for n in (3, 2):
        for i in range(0, max(0, len(words) - n + 1)):
            chunk = words[i : i + n]
            if any(w in stop for w in chunk):
                continue
            phrase = " ".join(chunk).strip()
            if len(phrase) < 8 or phrase in seen:
                continue
            seen.add(phrase)
            out.append(phrase)
            if len(out) >= max_phrases:
                return out
    return out


def _internal_link_search_seeds(
    primary_keyword: str,
    secondary_keywords: str,
    content_html: str,
    *,
    max_seeds: int = 5,
) -> list[str]:
    """Tổ hợp seed: từ khóa chính, từ khóa phụ, cụm trong content, token dài."""
    seeds: list[str] = []
    seen: set[str] = set()

    def add_seed(raw: str) -> None:
        t = str(raw or "").strip()
        if len(t) < 2:
            return
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        seeds.append(t)

    add_seed(primary_keyword)
    for part in str(secondary_keywords or "").split(","):
        add_seed(part.strip())

    plain = BeautifulSoup(str(content_html or ""), "html.parser").get_text(" ", strip=True)
    for ph in _extract_phrase_seeds_from_content(plain, max_phrases=5):
        add_seed(ph)
    tokens = [w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{5,}", plain.lower()) if w not in seen]
    tokens.sort(key=len, reverse=True)
    for w in tokens:
        add_seed(w)
        if len(seeds) >= max_seeds:
            break
    return seeds[:max_seeds] if seeds else [""]


def _find_best_anchor_in_content(content_html: str, post: dict) -> str:
    """
    Tìm cụm trong HTML content hiện tại làm anchor: trùng tiêu đề / tag / category / slug của bài đích.
    Trả về đúng casing theo nội dung gốc (để khớp khi chèn link).
    """
    raw_html = str(content_html or "").strip()
    if not raw_html or not isinstance(post, dict):
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    body_text_raw = soup.get_text(" ", strip=True)
    body_lower = body_text_raw.lower()
    if not body_lower.strip():
        return ""

    title = BeautifulSoup(str(post.get("title") or ""), "html.parser").get_text(" ", strip=True)
    title_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", title)
    weak = {
        "nhung", "những", "cach", "cách", "hướng", "dẫn", "guide", "top", "các", "một", "cho",
        "và", "của", "the", "for", "with", "seo",
    }

    for n in (6, 5, 4, 3, 2):
        for i in range(0, max(0, len(title_words) - n + 1)):
            cand = " ".join(title_words[i : i + n]).strip()
            if len(cand) < 6:
                continue
            if all(w.lower() in weak for w in cand.split()):
                continue
            idx = body_lower.find(cand.lower())
            if idx >= 0:
                return body_text_raw[idx : idx + len(cand)]

    for label in list(post.get("category_names") or []) + list(post.get("tag_names") or []):
        phrase = BeautifulSoup(str(label or ""), "html.parser").get_text(" ", strip=True).strip()
        if len(phrase) < 4:
            continue
        idx = body_lower.find(phrase.lower())
        if idx >= 0:
            return body_text_raw[idx : idx + len(phrase)]

    slug_raw = _slug_from_post_dict(post)
    slug_accented = _slug_ascii_to_accented_keyword(slug_raw) if slug_raw else ""
    for slug_try in (slug_accented, slug_raw.replace("-", " ") if slug_raw else ""):
        if len(slug_try) < 6:
            continue
        idx = body_lower.find(slug_try.lower())
        if idx < 0:
            idx_fold = _fold_vi(body_text_raw).find(_fold_vi(slug_try))
            if idx_fold >= 0:
                # Khớp không dấu: dùng tiêu đề có dấu thay vì slug ASCII
                t_clean = _clean_post_title(str(post.get("title") or ""))
                if t_clean and _fold_vi(t_clean) in _fold_vi(body_text_raw):
                    pos = _fold_vi(body_text_raw).find(_fold_vi(t_clean))
                    if pos >= 0:
                        return body_text_raw[pos : pos + len(t_clean)]
                return slug_try
            continue
        return body_text_raw[idx : idx + len(slug_try)]

    return ""


def _fold_vi(s: str) -> str:
    """So khớp không phân biệt dấu (slug ASCII vs tiêu đề/content có dấu)."""
    t = unicodedata.normalize("NFD", str(s or ""))
    folded = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded).casefold().strip()


def _clean_post_title(raw: str) -> str:
    t = BeautifulSoup(str(raw or ""), "html.parser").get_text(" ", strip=True).strip()
    if "|" in t:
        t = t.split("|")[0].strip()
    return t[:120]


def _has_vn_diacritics(s: str) -> bool:
    return bool(
        re.search(
            r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđÀ-Ỹ]",
            str(s or ""),
        )
    )


def _restore_accents_from_title(phrase: str, title: str) -> str:
    """Lấy đúng chữ có dấu từ tiêu đề WP khi tag/slug không dấu."""
    phrase = str(phrase or "").strip()
    title_clean = _clean_post_title(title)
    if not phrase or not title_clean:
        return phrase
    if _has_vn_diacritics(phrase):
        return phrase
    phrase_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", phrase)
    title_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", title_clean)
    if not phrase_words or not title_words:
        return phrase
    pw_fold = [_fold_vi(w) for w in phrase_words]
    tw_fold = [_fold_vi(w) for w in title_words]
    n = len(phrase_words)
    for i in range(0, len(title_words) - n + 1):
        if tw_fold[i : i + n] == pw_fold:
            return " ".join(title_words[i : i + n])
    return phrase


def _accentuate_vn_phrase(text: str) -> str:
    """Thêm dấu tiếng Việt cho cụm không dấu (tag WP / slug)."""
    raw = str(text or "").strip()
    if not raw or _has_vn_diacritics(raw):
        return raw
    slugish = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    slugish = re.sub(r"\s+", "-", slugish.strip().lower())
    slugish = re.sub(r"-+", "-", slugish).strip("-")
    if slugish:
        out = _slug_ascii_to_accented_keyword(slugish)
        if out:
            return out
    return raw


def _normalize_anchor_vn(text: str, *, post: dict | None = None) -> str:
    """Chuẩn hóa anchor: luôn ưu tiên bản có dấu."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    title = _clean_post_title(str((post or {}).get("title") or ""))
    if title:
        from_title = _restore_accents_from_title(raw, title)
        if _has_vn_diacritics(from_title):
            return from_title[:120]
    accented = _accentuate_vn_phrase(raw)
    if accented:
        return accented[:120]
    return raw[:120]


def _focus_keyword_from_wp_item(it: dict) -> str:
    """Focus keyword từ meta Yoast/Rank Math (nếu REST API trả về)."""
    if not isinstance(it, dict):
        return ""
    meta = it.get("meta")
    if isinstance(meta, dict):
        for key in (
            "rank_math_focus_keyword",
            "_rank_math_focus_keyword",
            "yoast_wpseo_focuskw",
            "_yoast_wpseo_focuskw",
            "focus_keyword",
        ):
            v = str(meta.get(key) or "").strip()
            if v:
                return v[:120]
    for key in ("rank_math_focus_keyword", "yoast_wpseo_focuskw", "focus_keyword"):
        v = str(it.get(key) or "").strip()
        if v:
            return v[:120]
    return ""


def _target_post_primary_keyword(post: dict) -> str:
    """
    Từ khóa chính bài viết đích (có dấu).
    Ưu tiên: tiêu đề có dấu -> focus SEO -> tag (khôi phục dấu từ tiêu đề) -> chuyên mục.
    """
    if not isinstance(post, dict):
        return ""
    title = _clean_post_title(str(post.get("title") or ""))
    if title and _has_vn_diacritics(title):
        return title[:120]

    sources: list[str] = []
    for key in ("focus_keyword", "primary_keyword", "target_primary_keyword"):
        v = str(post.get(key) or "").strip()
        if len(v) >= 2:
            sources.append(v)
    tags = [str(t).strip() for t in (post.get("tag_names") or []) if str(t).strip()]
    sources.extend(tags)
    cats = [str(c).strip() for c in (post.get("category_names") or []) if str(c).strip()]
    sources.extend(cats)
    if title:
        sources.append(title)

    seen: set[str] = set()
    for src in sources:
        k = _fold_vi(src)
        if not k or k in seen:
            continue
        seen.add(k)
        normed = _normalize_anchor_vn(src, post=post)
        if normed:
            return normed
    return ""


def _anchor_text_from_target_post(post: dict) -> str:
    """Anchor = từ khóa chính bài viết đích (có dấu)."""
    return _target_post_primary_keyword(post)


def _default_anchor_text_for_post(post: dict, *, content_html: str = "") -> str:
    """Anchor mặc định = từ khóa chính bài đích."""
    _ = content_html
    return _anchor_text_from_target_post(post)


def _content_keyword_match_score(content_plain: str, post: dict) -> int:
    """Điểm cộng khi bài đích chứa cụm/từ khóa xuất hiện trong content nguồn."""
    plain = str(content_plain or "").strip()
    if not plain or not isinstance(post, dict):
        return 0
    plain_fold = _fold_vi(plain)
    title = _clean_post_title(str(post.get("title") or ""))
    post_blob = " ".join(
        [
            title,
            " ".join(str(c) for c in (post.get("category_names") or [])),
            " ".join(str(t) for t in (post.get("tag_names") or [])),
            str(post.get("slug") or "").replace("-", " "),
        ]
    )
    post_fold = _fold_vi(post_blob)
    if not post_fold:
        return 0
    bonus = 0
    for ph in _extract_phrase_seeds_from_content(plain, max_phrases=10):
        if len(ph) < 6:
            continue
        if _fold_vi(ph) in plain_fold and _fold_vi(ph) in post_fold:
            bonus += 14
    for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{4,}", title):
        if len(w) < 4:
            continue
        if _fold_vi(w) in plain_fold and _fold_vi(w) in post_fold:
            bonus += 5
    return bonus


def _slug_from_post_dict(p: dict) -> str:
    """Lấy slug từ WP hoặc từ path URL (segment cuối)."""
    if not isinstance(p, dict):
        return ""
    s = str(p.get("slug") or "").strip().strip("/").lower()
    if s:
        return s
    link = str(p.get("link") or "").strip()
    if not link:
        return ""
    try:
        pu = urlparse(link if "://" in link else f"https://placeholder.local/{link.lstrip('/')}")
        path = (pu.path or "").strip("/")
        if not path:
            return ""
        last = path.split("/")[-1]
        return last.split("?")[0].lower()
    except Exception:
        return ""


def _slug_ascii_to_accented_keyword(slug_ascii: str) -> str:
    """
    Chuyển slug không dấu (vd. seo-onpage-la-gi) -> cụm từ khóa có dấu (vd. seo onpage là gì).
    Dùng cụm thay thế dài trước, sau đó map từng token từ điển nhỏ (SEO/blog thường gặp).
    """
    raw = str(slug_ascii or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("_", "-")
    raw = re.sub(r"-+", "-", raw)
    s = raw.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    padded = f" {s} "
    # Cụm (ưu tiên trước)
    phrases: tuple[tuple[str, str], ...] = (
        (" la gi ", " là gì "),
        (" lam sao ", " làm sao "),
        (" lam the nao ", " làm thế nào "),
        (" the nao ", " thế nào "),
        (" tu khoa ", " từ khóa "),
        (" nghien cuu ", " nghiên cứu "),
        (" phan mem ", " phần mềm "),
        (" toan tap ", " toàn tập "),
        (" don gian ", " đơn giản "),
        (" huong dan ", " hướng dẫn "),
        (" thuat toan ", " thuật toán "),
        (" chuyen muc ", " chuyên mục "),
        (" trang chu ", " trang chủ "),
        (" bai viet ", " bài viết "),
        (" noi dung ", " nội dung "),
        (" tieu chi ", " tiêu chí "),
        (" toi uu ", " tối ưu "),
        (" co ban ", " cơ bản "),
        (" nang cao ", " nâng cao "),
        (" vi du ", " ví dụ "),
        (" moi nhat ", " mới nhất "),
        (" tot nhat ", " tốt nhất "),
        (" can biet ", " cần biết "),
        (" so sanh ", " so sánh "),
        (" danh gia ", " đánh giá "),
        (" chi tiet ", " chi tiết "),
        (" chuyen sau ", " chuyên sâu "),
        (" chuyen gia ", " chuyên gia "),
        (" tang traffic ", " tăng traffic "),
        (" len top ", " lên top "),
        (" bao gia ", " báo giá "),
        (" bang gia ", " bảng giá "),
        (" bang xep hang ", " bảng xếp hạng "),
        (" cai phan mem ", " cài phần mềm "),
        (" may tinh ", " máy tính "),
        (" sua may tinh ", " sửa máy tính "),
        (" sua laptop ", " sửa laptop "),
        (" tai quan ", " tại quận "),
        (" tai nha ", " tại nhà "),
        (" tp hcm ", " TP HCM "),
        (" phu nhuan ", " phú nhuận "),
        (" quan 1 ", " quận 1 "),
        (" quan 3 ", " quận 3 "),
        (" quan 5 ", " quận 5 "),
        (" quan 10 ", " quận 10 "),
        (" quan 11 ", " quận 11 "),
        (" cai win ", " cài win "),
        (" thiet bi ", " thiết bị "),
        (" tai huyen ", " tại huyện "),
        (" hoc mon ", " hóc môn "),
        (" nha be ", " nhà bè "),
        (" tan binh ", " tân bình "),
        (" quan 6 ", " quận 6 "),
        (" quan 4 ", " quận 4 "),
        (" quan 7 ", " quận 7 "),
        (" quan 8 ", " quận 8 "),
        (" quan 9 ", " quận 9 "),
        (" quan 12 ", " quận 12 "),
        (" quan binh tan ", " quận bình tân "),
    )
    for a, b in phrases:
        padded = padded.replace(a, b)
    tokens = padded.strip().split()
    # Token đơn (chỉ thay khi slug tách từ — cụm đã xử lý ở trên)
    word_map: dict[str, str] = {
        "la": "là",
        "gi": "gì",
        "cac": "các",
        "cach": "cách",
        "lam": "làm",
        "the": "thế",
        "nao": "nào",
        "tu": "từ",
        "khoa": "khóa",
        "nghien": "nghiên",
        "cuu": "cứu",
        "tim": "tìm",
        "kiem": "kiếm",
        "phan": "phần",
        "mem": "mềm",
        "huong": "hướng",
        "dan": "dẫn",
        "chuyen": "chuyên",
        "muc": "mục",
        "viet": "viết",
        "bai": "bài",
        "noi": "nội",
        "tieu": "tiêu",
        "toi": "tối",
        "uu": "ưu",
        "thuat": "thuật",
        "toan": "toàn",
        "tap": "tập",
        "don": "đơn",
        "co": "cơ",
        "ban": "bản",
        "nang": "nâng",
        "cao": "cao",
        "vi": "ví",
        "du": "dụ",
        "moi": "mới",
        "nhat": "nhất",
        "tot": "tốt",
        "tang": "tăng",
        "len": "lên",
        "voi": "với",
        "va": "và",
        "de": "để",
        "khi": "khi",
        "nhu": "như",
        "mot": "một",
        "hai": "hai",
        "ba": "ba",
        "buoc": "bước",
        "nam": "năm",
        "giai": "giải",
        "phap": "pháp",
        "dung": "đúng",
        "sai": "sai",
        "loi": "lỗi",
        "thuong": "thường",
        "gap": "gặp",
        "bao": "báo",
        "xep": "xếp",
        "hang": "hạng",
        "cai": "cài",
        "may": "máy",
        "tinh": "tính",
        "sua": "sửa",
        "laptop": "laptop",
        "online": "online",
        "tai": "tại",
        "nha": "nhà",
        "tp": "TP",
        "hcm": "HCM",
        "phu": "phú",
        "nhuan": "nhuận",
        "quan": "quận",
        "thiet": "thiết",
        "bi": "bị",
        "win": "win",
        "dat": "đặt",
        "ve": "về",
        "dich": "dịch",
        "vu": "vụ",
        "gan": "gần",
        "day": "đây",
        "khu": "khu",
        "vuc": "vực",
        "cai": "cài",
        "may": "máy",
        "tinh": "tính",
        "sua": "sửa",
        "laptop": "laptop",
        "online": "online",
        "tai": "tại",
        "nha": "nhà",
        "tp": "TP",
        "hcm": "HCM",
        "phu": "phú",
        "nhuan": "nhuận",
        "quan": "quận",
        "huyen": "huyện",
        "hoc": "hóc",
        "mon": "môn",
        "be": "bè",
        "tan": "tân",
        "binh": "bình",
        "thiet": "thiết",
        "bi": "bị",
    }
    out: list[str] = []
    for w in tokens:
        if not w:
            continue
        if re.fullmatch(r"[0-9]+", w):
            out.append(w)
            continue
        out.append(word_map.get(w, w))
    return " ".join(out).strip()


def _heuristic_keyword_hints_for_post(p: dict) -> dict[str, str]:
    """Gợi ý nhanh (không LLM): TK chính bài đích; TK phụ = tag/category còn lại."""
    if not isinstance(p, dict):
        return {"primary": "", "secondary": ""}
    primary = _target_post_primary_keyword(p)
    cats = [str(c).strip() for c in (p.get("category_names") or []) if str(c).strip()]
    tags = [str(t).strip() for t in (p.get("tag_names") or []) if str(t).strip()]
    sec_list = [t for t in list(dict.fromkeys(tags[1:6] + cats[:4])) if t and t != primary]
    secondary = ", ".join(sec_list)
    if not primary:
        primary = "liên quan"
    return {"primary": primary, "secondary": secondary}


def _topic_tokens(seed: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", str(seed or "").lower())}


def _extract_districts(text: str) -> set[str]:
    s = str(text or "").lower()
    out: set[str] = set()
    for m in re.findall(r"qu(?:a|ậ)n\s*([0-9]{1,2})", s):
        out.add(f"q{m}")
    return out


def _nearby_districts(d: str) -> set[str]:
    # Heuristic map for HCMC central districts (can expand later).
    m = {
        "q1": {"q3", "q4", "q5", "q10", "q11", "qphunhuan"},
        "q3": {"q1", "q10", "q5", "qphunhuan", "qbt"},
        "q5": {"q1", "q3", "q6", "q10", "q11"},
        "q10": {"q1", "q3", "q5", "q11", "qtanbinh"},
    }
    return m.get(d, set())


def _core_topic_terms(seed: str) -> set[str]:
    stop = {
        "tai", "nha", "quan", "quận", "gan", "gần", "uy", "tin", "gia", "re", "giá", "rẻ",
        "tphcm", "hcm", "tp", "dịch", "vụ",
    }
    words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{2,}", str(seed or "").lower())
    return {w for w in words if w not in stop and not w.isdigit()}


def _service_topic_bucket(text: str) -> str:
    s = str(text or "").lower()
    if ("máy tính" in s) or ("may tinh" in s) or ("laptop" in s) or ("pc" in s):
        return "computer"
    if ("máy in" in s) or ("may in" in s) or ("printer" in s):
        return "printer"
    return "generic"


def _same_service_topic(source_text: str, candidate_text: str) -> bool:
    src = _service_topic_bucket(source_text)
    cand = _service_topic_bucket(candidate_text)
    if src == "generic":
        return True
    return src == cand


def _score_related_post(post: dict, topic: set[str], *, source_text: str = "") -> int:
    title = str((post or {}).get("title") or "").lower()
    cat = " ".join((post or {}).get("category_names") or []).lower()
    tags = " ".join((post or {}).get("tag_names") or []).lower()
    s = 0
    for t in topic:
        if t in title:
            s += 3
        if t in cat:
            s += 5
        if t in tags:
            s += 4
    # Stronger topic matching for intent-specific phrase (e.g. "cài win", "sửa máy tính")
    core_terms = _core_topic_terms(source_text)
    if core_terms:
        hit_title = sum(1 for t in core_terms if t in title)
        hit_meta = sum(1 for t in core_terms if t in cat or t in tags)
        s += hit_title * 4 + hit_meta * 2
        if hit_title >= min(2, len(core_terms)):
            s += 8
    src_d = _extract_districts(source_text)
    post_d = _extract_districts(" ".join([title, cat, tags]))
    if src_d and post_d:
        if src_d & post_d:
            s += 14
        else:
            for d in src_d:
                near = _nearby_districts(d)
                if near & post_d:
                    s += 9
                    break
    return s


def _canonical_host_path(url: str) -> tuple[str, str]:
    try:
        u = str(url or "").strip()
        if not u:
            return "", ""
        p = urlparse(u if "://" in u else f"https://x.local/{u.lstrip('/')}")
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "/").rstrip("/").lower() or "/"
        return host, path
    except Exception:
        return "", ""


def _href_matches_job(href: str, job_url: str) -> bool:
    ha, pa = _canonical_host_path(href)
    hb, pb = _canonical_host_path(job_url)
    if hb and ha == hb and pa == pb:
        return True
    raw = str(href or "").strip()
    if hb and pb and raw.startswith("/") and not raw.startswith("//"):
        _, pr = _canonical_host_path(f"https://{hb}{raw}")
        return pr == pb
    return False


def _norm_anchor_cmp(s: str) -> str:
    t = unicodedata.normalize("NFC", str(s or "").strip())
    return re.sub(r"\s+", " ", t).casefold()


def _verify_llm_internal_links_html(html: str, jobs: list[dict]) -> bool:
    """LLM phải chèn đủ link: href khớp URL và text trong <a> khớp anchor_text (Unicode)."""
    if not jobs:
        return False
    soup = BeautifulSoup(str(html or "").strip(), "html.parser")
    for it in jobs:
        if not isinstance(it, dict):
            return False
        url = str(it.get("url") or "").strip()
        anchor_raw = str(it.get("anchor_text") or "").strip() or str(it.get("title") or "").strip()
        if not url or not anchor_raw:
            return False
        want = _norm_anchor_cmp(anchor_raw)
        found = False
        for a in soup.find_all("a", href=True):
            if not _href_matches_job(str(a.get("href") or ""), url):
                continue
            got = _norm_anchor_cmp(a.get_text(" ", strip=True))
            if got == want or (len(want) >= 10 and want in got) or (len(got) >= 10 and got in want):
                found = True
                break
        if not found:
            return False
    return True


def _choose_anchor_from_tag(tag: Any, title: str) -> str:
    tag_text = re.sub(r"\s+", " ", str(tag.get_text(" ", strip=True) or "")).strip()
    if not tag_text:
        return ""
    title_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", str(title or ""))
    # prefer 2-5 words phrase from target title that appears in this section text
    for n in (5, 4, 3, 2):
        for i in range(0, max(0, len(title_words) - n + 1)):
            cand = " ".join(title_words[i : i + n]).strip()
            if len(cand) < 8:
                continue
            if cand.lower() in tag_text.lower():
                return cand
    return ""


def _inject_internal_links_contextual(content_html: str, posts: list[dict], *, max_links: int = 4) -> str:
    raw = str(content_html or "").strip()
    if not raw:
        return raw
    soup = BeautifulSoup(raw, "html.parser")
    body_text = soup.get_text(" ", strip=True).lower()
    used_urls: set[str] = set()
    used_sections: set[str] = set()
    inserted = 0

    for post in posts:
        if inserted >= max_links:
            break
        url = str((post or {}).get("link") or "").strip()
        title = str((post or {}).get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        words = [w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", title.lower()) if len(w) >= 3]
        words = [w for w in words if w not in {"nhung", "những", "cach", "hướng", "dẫn", "guide", "seo"}]
        if not words:
            continue
        phrase = ""
        # prefer 2-4 word phrase in title that appears in content
        title_words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", title)
        for n in (4, 3, 2):
            if phrase:
                break
            for i in range(0, max(0, len(title_words) - n + 1)):
                cand = " ".join(title_words[i : i + n]).strip()
                if len(cand) < 8:
                    continue
                if cand.lower() in body_text:
                    phrase = cand
                    break
        if not phrase:
            continue

        done = False
        for tag in soup.find_all(["p", "li", "h3", "h4"]):
            if tag.find("a"):
                continue
            h2 = tag.find_previous("h2")
            if h2 is not None:
                h2_txt = h2.get_text(" ", strip=True)
                if re.search(r"faq|câu\s*hỏi|hỏi\s*đáp", h2_txt, re.I):
                    continue
            section_key = str(id(h2)) if h2 else "intro"
            if section_key in used_sections:
                continue
            for node in list(tag.descendants):
                if done:
                    break
                if not isinstance(node, NavigableString):
                    continue
                parent = getattr(node, "parent", None)
                if parent and getattr(parent, "name", "") == "a":
                    continue
                text = str(node)
                low = text.lower()
                idx = low.find(phrase.lower())
                if idx < 0:
                    continue
                before = text[:idx]
                match = text[idx : idx + len(phrase)]
                after = text[idx + len(phrase) :]
                frag = BeautifulSoup(
                    f"{py_html.escape(before)}<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(match)}</a>{py_html.escape(after)}",
                    "html.parser",
                )
                node.replace_with(*list(frag.contents))
                done = True
            if done:
                used_sections.add(section_key)
                break
        if done:
            used_urls.add(url)
            inserted += 1

    return str(soup)


def _inject_selected_internal_links(
    *,
    content_html: str,
    selected_posts: list[dict],
    target_website: str = "",
    max_links_per_section: int = 1,
) -> tuple[str, list[dict]]:
    raw = str(content_html or "").strip()
    if not raw:
        return raw, []
    soup = BeautifulSoup(raw, "html.parser")
    updates: list[dict] = []
    sections = soup.find_all(["p", "li"])
    if not sections:
        return raw, updates
    # Do not inject into sapo: skip first opening paragraph block.
    first_p = soup.find("p")
    used_urls: set[str] = set()
    per_section_count: dict[str, int] = {}
    base = _normalize_site_base(target_website)

    def _classify_target(url: str) -> str:
        u = str(url or "").strip()
        if not u:
            return "related"
        try:
            pu = urlparse(u if "://" in u else f"https://x.local/{u.lstrip('/')}")
            path = (pu.path or "/").strip().lower().rstrip("/")
            if base:
                pb = urlparse(base)
                same_host = (pu.netloc or "").lower() == (pb.netloc or "").lower()
            else:
                same_host = True
            if same_host and (path in {"", "/"}):
                return "home"
            if any(x in path for x in ("/category/", "/chuyen-muc/", "/chuyên-mục/")):
                return "category"
            if any(x in path for x in ("/product-category/", "/danh-muc/", "/danh-mục/")):
                return "product_category"
            return "related"
        except Exception:
            return "related"

    group_limit = {"home": 1, "category": 1, "product_category": 1, "related": 999}
    group_used = {"home": 0, "category": 0, "product_category": 0, "related": 0}
    phrase_pool = ["Xem thêm:", "Tham khảo thêm:", "Gợi ý liên quan:", "Lưu ý:"]
    phrase_idx = 0
    for post in selected_posts:
        url = str((post or {}).get("link") or "").strip()
        title = str((post or {}).get("title") or "").strip()
        if not url or not title or url in used_urls:
            continue
        group = _classify_target(url)
        if group_used[group] >= group_limit[group]:
            continue
        title_terms = [w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", title.lower())]
        # Remove weak words so anchor/context stays relevant.
        stop_terms = {"tai", "nha", "quan", "quận", "gan", "gần", "dich", "vu", "dịch", "vụ", "it", "sieu", "viet"}
        title_terms = [w for w in title_terms if w not in stop_terms]
        done = False
        anchor_user = str((post or {}).get("anchor_text") or "").strip()
        anchor_terms = (
            [w for w in re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{3,}", anchor_user.lower())] if anchor_user else []
        )
        # Ưu tiên đoạn có chồng lấn cả tiêu đề bài đích và cụm anchor (slug có dấu).
        scored_sections: list[tuple[int, Any]] = []
        for tag in sections:
            if first_p is not None and tag is first_p:
                continue
            txt = re.sub(r"\s+", " ", str(tag.get_text(" ", strip=True) or "")).lower()
            overlap = sum(1 for t in title_terms if t in txt)
            if anchor_terms:
                overlap += sum(2 for t in anchor_terms if t in txt)
            scored_sections.append((overlap, tag))
        scored_sections.sort(key=lambda x: x[0], reverse=True)

        best_tag = scored_sections[0][1] if scored_sections else None
        best_anchor = ""
        body_plain = unicodedata.normalize("NFC", soup.get_text(" ", strip=True))
        au_nfc = unicodedata.normalize("NFC", anchor_user)
        anchor_in_body = bool(au_nfc) and au_nfc.casefold() in body_plain.casefold()
        min_inline_anchor_len = 10

        if anchor_user:
            try_inline = anchor_in_body and len(au_nfc) >= min_inline_anchor_len
            if try_inline:
                for _overlap, tag in scored_sections:
                    if first_p is not None and tag is first_p:
                        continue
                    if tag.find("a"):
                        continue
                    h2u = tag.find_previous("h2")
                    section_key_u = str(id(h2u)) if h2u else "intro"
                    if per_section_count.get(section_key_u, 0) >= max_links_per_section:
                        continue
                    for node in list(tag.descendants):
                        if not isinstance(node, NavigableString):
                            continue
                        parent = getattr(node, "parent", None)
                        if parent and getattr(parent, "name", "") == "a":
                            continue
                        text = str(node)
                        twork = unicodedata.normalize("NFC", text)
                        idx = twork.casefold().find(au_nfc.casefold())
                        if idx < 0:
                            continue
                        match = twork[idx : idx + len(au_nfc)]
                        before = twork[:idx]
                        after = twork[idx + len(au_nfc) :]
                        frag = BeautifulSoup(
                            f"{py_html.escape(before)}<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(match)}</a>{py_html.escape(after)}",
                            "html.parser",
                        )
                        node.replace_with(*list(frag.contents))
                        updates.append({"target_url": url, "anchor_text": match, "target_title": title, "group": group})
                        used_urls.add(url)
                        group_used[group] += 1
                        per_section_count[section_key_u] = per_section_count.get(section_key_u, 0) + 1
                        done = True
                        break
                    if done:
                        break
            if not done and best_tag is not None:
                h2a = best_tag.find_previous("h2")
                sk = str(id(h2a)) if h2a else "intro"
                if per_section_count.get(sk, 0) < max_links_per_section:
                    lead = phrase_pool[phrase_idx % len(phrase_pool)]
                    phrase_idx += 1
                    txt = (
                        f"{lead} có thể xem thêm "
                        f"<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(anchor_user)}</a> "
                        "— nội dung liên quan trực tiếp tới chủ đề đang trình bày."
                    )
                    best_tag.append(BeautifulSoup(f" {txt}", "html.parser"))
                    updates.append({"target_url": url, "anchor_text": anchor_user, "target_title": title, "group": group})
                    used_urls.add(url)
                    group_used[group] += 1
                    per_section_count[sk] = per_section_count.get(sk, 0) + 1
                    done = True

        if not done:
            for overlap, tag in scored_sections:
                if overlap <= 0:
                    continue
                if tag.find("a"):
                    continue
                h2 = tag.find_previous("h2")
                section_key = str(id(h2)) if h2 else "intro"
                if per_section_count.get(section_key, 0) >= max_links_per_section:
                    continue
                anchor = _choose_anchor_from_tag(tag, title)
                if not anchor and title_terms:
                    # fallback: use 2-word phrase from section that matches post topic.
                    txt = re.sub(r"\s+", " ", str(tag.get_text(" ", strip=True) or "")).strip()
                    words = re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]+", txt)
                    for n in (3, 2):
                        if anchor:
                            break
                        for i in range(0, max(0, len(words) - n + 1)):
                            cand = " ".join(words[i : i + n]).strip()
                            low = cand.lower()
                            if len(cand) < 8:
                                continue
                            hit = sum(1 for t in title_terms if t in low)
                            if hit >= min(2, n):
                                anchor = cand
                                break
                if not anchor:
                    continue
                best_anchor = anchor
                for node in list(tag.descendants):
                    if not isinstance(node, NavigableString):
                        continue
                    parent = getattr(node, "parent", None)
                    if parent and getattr(parent, "name", "") == "a":
                        continue
                    text = str(node)
                    idx = text.lower().find(anchor.lower())
                    if idx < 0:
                        continue
                    before = text[:idx]
                    match = text[idx : idx + len(anchor)]
                    after = text[idx + len(anchor) :]
                    frag = BeautifulSoup(
                        f"{py_html.escape(before)}<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(match)}</a>{py_html.escape(after)}",
                        "html.parser",
                    )
                    node.replace_with(*list(frag.contents))
                    updates.append({"target_url": url, "anchor_text": match, "target_title": title, "group": group})
                    used_urls.add(url)
                    group_used[group] += 1
                    per_section_count[section_key] = per_section_count.get(section_key, 0) + 1
                    done = True
                    break
                if done:
                    break
        # Fallback: if no natural exact match found, append a contextual sentence with anchor.
        if not done and best_tag is not None:
            h2 = best_tag.find_previous("h2")
            section_key = str(id(h2)) if h2 else "intro"
            if per_section_count.get(section_key, 0) < max_links_per_section:
                anchor_fallback = best_anchor or anchor_user or title
                lead = phrase_pool[phrase_idx % len(phrase_pool)]
                phrase_idx += 1
                txt = (
                    f"{lead} "
                    f"<a href=\"{py_html.escape(url, quote=True)}\">{py_html.escape(anchor_fallback)}</a> "
                    "để áp dụng đúng ngữ cảnh."
                )
                best_tag.append(BeautifulSoup(f" {txt}", "html.parser"))
                updates.append({"target_url": url, "anchor_text": anchor_fallback, "target_title": title, "group": group})
                used_urls.add(url)
                group_used[group] += 1
                per_section_count[section_key] = per_section_count.get(section_key, 0) + 1
                done = True
    return str(soup), updates


@router.post("/content-ai/wp-internal-links")
def content_ai_internal_links(
    payload: InternalLinkRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    content_html = str(payload.content_html or "").strip()
    if not content_html:
        raise HTTPException(status_code=400, detail="Thiếu content_html.")
    base = _normalize_site_base(payload.target_website)
    if not base:
        raise HTTPException(status_code=400, detail="Target website không hợp lệ.")
    kw = str(payload.primary_keyword or "").strip()
    posts = _fetch_related_posts_wp(base, kw, limit=18)
    cur_url = _norm_url_for_compare(str(payload.current_url or ""))
    cur_slug = str(payload.current_slug or "").strip().strip("/").lower()
    if cur_url or cur_slug:
        filtered: list[dict] = []
        for p in posts:
            link = str((p or {}).get("link") or "")
            slug = str((p or {}).get("slug") or "").strip().strip("/").lower()
            if cur_url and _norm_url_for_compare(link) == cur_url:
                continue
            if cur_slug and slug == cur_slug:
                continue
            filtered.append(p)
        posts = filtered
    if not posts:
        return JSONResponse(content={"content_html": content_html, "inserted_links": 0, "related_posts": 0})
    topic = _topic_tokens(f"{kw} {payload.current_slug or ''} {BeautifulSoup(content_html, 'html.parser').get_text(' ', strip=True)[:220]}")
    posts.sort(key=lambda p: _score_related_post(p, topic), reverse=True)
    max_links = max(1, min(int(payload.max_links or 4), 8))
    out_html = _inject_internal_links_contextual(content_html, posts, max_links=max_links)
    inserted_links = len(BeautifulSoup(out_html, "html.parser").find_all("a")) - len(BeautifulSoup(content_html, "html.parser").find_all("a"))
    return JSONResponse(
        content={
            "content_html": out_html,
            "inserted_links": max(0, inserted_links),
            "related_posts": len(posts),
        }
    )


@router.post("/content-ai/wp-internal-links/candidates")
def content_ai_internal_link_candidates(
    payload: InternalLinkCandidateRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    base = _normalize_site_base(payload.target_website)
    if not base:
        raise HTTPException(status_code=400, detail="Target website không hợp lệ.")
    kw = str(payload.primary_keyword or "").strip()
    sec_kw = str(payload.secondary_keywords or "").strip()
    content_html = str(payload.content_html or "").strip()
    hard_limit = max(3, min(int(payload.limit or 15), 30))

    seeds = _internal_link_search_seeds(kw, sec_kw, content_html, max_seeds=6)
    posts = _merge_wp_related_posts(base, seeds, per_seed=18, cap=56)
    plain_snip = BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True)[:2400] if content_html else ""
    topic_query = kw or (sec_kw.split(",")[0].strip() if sec_kw else "") or plain_snip[:120]
    if len(posts) < hard_limit:
        fb = _serp_sitemap_wp_posts_fallback(base, topic_query, limit=hard_limit * 2)
        posts = _merge_posts_by_link(posts, fb)
    if len(posts) < 3:
        posts = _merge_posts_by_link(
            posts,
            _fetch_related_posts_wp(base, "", limit=20),
        )

    cur_url = _norm_url_for_compare(str(payload.current_url or ""))
    cur_slug = str(payload.current_slug or "").strip().strip("/").lower()
    if cur_url or cur_slug:
        posts = [
            p for p in posts
            if (not cur_url or _norm_url_for_compare(str(p.get("link") or "")) != cur_url)
            and (not cur_slug or str(p.get("slug") or "").strip().strip("/").lower() != cur_slug)
        ]
    topic_seed = f"{kw} {sec_kw} {payload.current_slug or ''} {plain_snip}"
    topic = _topic_tokens(topic_seed)
    scored: list[dict[str, Any]] = []
    for p in posts:
        item = _scored_item_from_wp_post(
            p,
            topic_seed=topic_seed,
            topic=topic,
            plain_snip=plain_snip,
            content_html=content_html,
            article_primary_keyword=kw,
            article_secondary_keywords=sec_kw,
            relaxed=False,
        )
        if item:
            scored.append(item)
    if not scored and posts:
        for p in posts[: hard_limit * 2]:
            item = _scored_item_from_wp_post(
                p,
                topic_seed=topic_seed,
                topic=topic,
                plain_snip=plain_snip,
                content_html=content_html,
                article_primary_keyword=kw,
                article_secondary_keywords=sec_kw,
                relaxed=True,
            )
            if item:
                scored.append(item)
    _page_type_rank = {"money_page": 0, "service": 1, "course": 2, "pillar": 3, "blog": 4, "category": 5, "other": 6}

    def _sort_key(x: dict) -> tuple:
        pt = str(x.get("page_type") or "blog")
        return (
            -int(x.get("relevance_score") or 0),
            _page_type_rank.get(pt, 9),
            -int(x.get("content_keyword_score") or 0),
            0 if str(x.get("suggested_anchor") or x.get("anchor_text") or "").strip() else 1,
            -int(x.get("score") or 0),
        )

    scored.sort(key=_sort_key)
    items = scored[:hard_limit]
    hint = ""
    if not items:
        hint = (
            "Không tìm thấy bài liên quan trên WordPress/SERP. "
            "Kiểm tra Target website (https://...), REST API /wp-json/wp/v2/posts, "
            "và thử nhập từ khóa chính hoặc thêm nội dung bài."
        )
    return JSONResponse(
        content={
            "items": items,
            "primary_keyword": kw,
            "search_seeds": seeds,
            "wp_posts_fetched": len(posts),
            "hint": hint,
        },
    )


@router.post("/content-ai/wp-internal-links/apply")
def content_ai_internal_link_apply(
    payload: InternalLinkApplyRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    content_html = str(payload.content_html or "").strip()
    if not content_html:
        raise HTTPException(status_code=400, detail="Thiếu content_html.")
    selected = payload.selected_posts or []
    custom_raw = payload.custom_links or []
    chosen: list[dict] = []
    for it in selected:
        if not isinstance(it, dict):
            continue
        link = str(it.get("link") or it.get("target_url") or "").strip()
        title = str(it.get("title") or "").strip()
        anchor = str(it.get("anchor_text") or "").strip()
        if link and (title or anchor):
            chosen.append({"link": link, "title": title or anchor, "anchor_text": anchor})
    custom_list: list[dict] = []
    for it in custom_raw:
        if not isinstance(it, dict):
            continue
        url = str(it.get("target_url") or it.get("link") or "").strip()
        anchor = str(it.get("anchor_text") or "").strip()
        if url or anchor:
            custom_list.append(dict(it))
    checked_custom = [c for c in custom_list if str(c.get("target_url") or "").strip() and str(c.get("anchor_text") or "").strip()]
    if not chosen and not checked_custom:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chưa có link để chèn: tick chọn custom link (URL + anchor) "
                "hoặc chọn bài WordPress ở bảng «Tìm bài liên quan»."
            ),
        )

    use_llm = True if payload.use_llm_rewrite is None else bool(payload.use_llm_rewrite)
    pk_a = str(payload.article_primary_keyword or "").strip()
    sec_a = str(payload.article_secondary_keywords or "").strip()
    llm_available = False
    try:
        llm_available = bool(load_llm_config())
    except Exception:
        llm_available = False

    merged = apply_merged_internal_links(
        content_html=content_html,
        custom_links=checked_custom,
        selected_posts=chosen,
        current_url=str(payload.current_url or ""),
        article_primary_keyword=pk_a,
        article_secondary_keywords=sec_a,
        use_llm_rewrite=use_llm,
        llm_available=llm_available,
        legacy_inject_fn=_inject_selected_internal_links,
        target_website=str(payload.target_website or ""),
        apply_mode=str(payload.apply_mode or "full"),
        append_lead=str(payload.append_lead or "Tham khảo thêm:"),
        confirmed_append_urls=payload.confirmed_append_urls,
    )
    updates = merged.get("updates") or []
    pending = merged.get("pending_append_offers") or []
    if not updates and not pending:
        detail = str(merged.get("error") or "Không chèn được internal link.")
        raise HTTPException(status_code=422, detail=detail)
    return JSONResponse(
        content={
            "content_html": merged.get("content_html") or content_html,
            "inserted_links": int(merged.get("inserted_links") or 0),
            "updates": updates,
            "link_results": merged.get("link_results") or [],
            "screaming_frog_tsv": merged.get("screaming_frog_tsv") or "",
            "used_llm_rewrite": bool(merged.get("used_llm_rewrite")),
            "insert_mode": str(merged.get("insert_mode") or "minimal"),
            "pending_append_offers": pending,
            "verification": merged.get("verification") or {"ok": True, "issues": []},
        }
    )


@router.post("/content-ai/wp-internal-links/row-hint")
def content_ai_internal_link_row_hint(
    payload: InternalLinkRowHintRequest,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    try:
        hints = suggest_internal_link_row_keywords(
            article_primary_keyword=str(payload.article_primary_keyword or ""),
            article_secondary_keywords=str(payload.article_secondary_keywords or ""),
            target_post_title=str(payload.target_title or ""),
            target_post_url=str(payload.target_link or ""),
            target_categories=str(payload.target_categories or ""),
            target_tags=str(payload.target_tags or ""),
            content_snippet=str(payload.content_snippet or ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)[:900]) from exc
    return JSONResponse(content=hints)


def _html_to_lines(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    # Make HTML more "line-like" for progressive rendering.
    normalized = re.sub(r">\s*<", ">\n<", raw)
    parts = [x.rstrip() for x in normalized.splitlines()]
    lines = [x for x in parts if x.strip()]
    return lines or [raw]


def _content_to_stream_chunks(value: str, *, chunk_size: int = 280) -> list[str]:
    """
    Split generated HTML into progressive chunks for smoother SSE progress.
    Works even when provider returns the whole HTML in a single line.
    """
    lines = _html_to_lines(value)
    if not lines:
        return []
    raw = "\n".join(lines).strip()
    if not raw:
        return []
    size = max(120, min(int(chunk_size or 280), 900))
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        j = min(n, i + size)
        if j < n:
            # Try to break at a friendly boundary near chunk end.
            slice_text = raw[i:j]
            k = max(
                slice_text.rfind("\n"),
                slice_text.rfind(">"),
                slice_text.rfind(" "),
            )
            if k >= int(size * 0.45):
                j = i + k + 1
        out.append(raw[i:j])
        i = j
    return [x for x in out if x.strip()]


def _fallback_content_html_from_payload(payload: "ContentSuggestRequest") -> str:
    """
    Deterministic fallback when LLM returns empty output.
    Always return non-empty clean HTML for field=content.
    """
    kw = (payload.primary_keyword or "").strip()
    title = (payload.title or "").strip() or kw or "Nội dung dịch vụ"
    outline = (payload.outline_content or "").strip()
    notes = (payload.content or "").strip()
    h2_items: list[str] = []
    if outline:
        for ln in outline.splitlines():
            s = re.sub(r"^\s*#+\s*", "", str(ln or "").strip())
            if len(s) >= 4:
                h2_items.append(s)
            if len(h2_items) >= 6:
                break
    if not h2_items:
        h2_items = [
            f"Nhu cầu phổ biến về {kw or 'dịch vụ'}",
            "Dịch vụ cung cấp và phạm vi hỗ trợ",
            "Bảng giá tham khảo và quy trình triển khai",
            "Liên hệ đặt lịch nhanh",
        ]
    intro = (
        f"Bạn đang cần {kw or 'dịch vụ'} nhanh, rõ chi phí và có người xử lý đúng lỗi ngay từ đầu. "
        "Thông tin dưới đây giúp bạn chọn phương án phù hợp và đặt lịch ngay."
    )
    html_parts = [f"<h1>{title}</h1>", f"<p><strong>{intro}</strong></p>"]
    for idx, h2 in enumerate(h2_items, start=1):
        html_parts.append(f"<h2>{h2}</h2>")
        html_parts.append(
            "<p>Chúng tôi tiếp nhận nhu cầu, kiểm tra hiện trạng và báo hướng xử lý trước khi thực hiện để bạn chủ động thời gian.</p>"
        )
        html_parts.append(
            "<p>Quy trình ưu tiên minh bạch: xác nhận hạng mục, báo giá theo phạm vi thực tế, cập nhật tiến độ và nghiệm thu theo checklist.</p>"
        )
        if idx == 3:
            html_parts.append(
                "<table><tr><th>Hạng mục</th><th>Chi phí tham khảo</th></tr>"
                "<tr><td>Kiểm tra - chẩn đoán</td><td>150.000 - 300.000đ</td></tr>"
                "<tr><td>Bảo trì tối ưu</td><td>300.000 - 800.000đ</td></tr>"
                "<tr><td>Sửa lỗi phần cứng/phần mềm</td><td>400.000 - 2.500.000đ</td></tr></table>"
            )
    html_parts.append("<h2>Checklist trước khi đặt lịch</h2>")
    html_parts.append(
        "<ul><li>Mô tả lỗi đang gặp và thời điểm bắt đầu.</li>"
        "<li>Gửi ảnh/video hiện trạng nếu có.</li>"
        "<li>Để lại số điện thoại/Zalo để kỹ thuật viên xác nhận.</li></ul>"
    )
    if notes:
        html_parts.append(f"<p>{re.sub(r'<[^>]+>', ' ', notes)[:900]}</p>")
    html_parts.append(
        "<h2>Liên hệ ngay</h2><p>Gọi hotline hoặc nhắn Zalo để được tư vấn nhanh và đặt lịch theo khung giờ phù hợp.</p>"
    )
    return "\n".join(html_parts).strip()


@router.post("/content-ai/suggest")
def content_ai_suggest(
    request: Request,
    payload: ContentSuggestRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> Response:
    from app.services.user_api_access import assert_user_may_use_api

    assert_user_may_use_api(current_user)
    feature_key = feature_for_suggest_field(payload.field)
    assert_content_ai_feature(db, current_user, feature_key, quantity=1)
    requested = (payload.field or "").strip().lower()
    detected_intent = detect_search_intent(payload.primary_keyword or payload.title or "")
    if requested != "target_website" and not (payload.primary_keyword or "").strip():
        raise HTTPException(status_code=400, detail="Vui long nhap tu khoa chinh truoc khi goi y AI.")
    # Prefer LLM when configured; rule-based chỉ còn cho title/meta/outline/tags/slug — không sinh HTML body content.
    suggestion = ""
    llm_cfg = None
    try:
        llm_cfg = load_llm_config()
    except Exception:
        llm_cfg = None
    llm_mode = (os.getenv("CONTENT_AI_LLM_MODE", "auto") or "auto").strip().lower()
    if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
        llm_mode = "auto"
    llm_fields = _content_ai_llm_enabled_fields(llm_mode)
    if llm_mode == "auto" and requested == "content" and not llm_cfg:
        raise HTTPException(
            status_code=503,
            detail="CONTENT_AI_LLM_MODE=auto: field content cần LLM (API key). Hệ thống không còn sinh HTML content bằng rule-based.",
        )
    use_llm = _should_use_llm_for_suggest(
        request, requested, llm_cfg=llm_cfg, llm_fields=llm_fields
    )
    if use_llm:
        try:
            suggestion = generate_content_ai_suggestion(
                field=payload.field,
                title=payload.title or "",
                content=payload.content or "",
                target_website=payload.target_website or "",
                slug=payload.slug or "",
                tags=payload.tags or "",
                meta_description=payload.meta_description or "",
                primary_keyword=payload.primary_keyword or "",
                secondary_keywords=payload.secondary_keywords or "",
                outline_content=payload.outline_content or "",
                target_word_count=payload.target_word_count,
            )
            if requested == "content" and not str(suggestion or "").strip():
                suggestion = _fallback_content_html_from_payload(payload)
        except Exception as exc:
            allow_fallback = (request.query_params.get("fallback") or "").strip().lower() in {"1", "true", "yes"}
            msg = str(exc)[:800]
            if not allow_fallback and not _is_llm_transient_error(exc):
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "LLM call failed. "
                        "Tip: kiểm tra quota/billing hoặc thử đổi sang ANTHROPIC_API_KEY. "
                        f"Error: {msg}"
                    ),
                ) from exc
            suggestion = _fallback_content_html_from_payload(payload) if requested == "content" else ""
    if not suggestion:
        if llm_mode == "auto" and requested == "content":
            suggestion = _fallback_content_html_from_payload(payload)
        else:
            suggestion = suggest_content_ai_field(
                field=payload.field,
                title=payload.title or "",
                content=payload.content or "",
                target_website=payload.target_website or "",
                slug=payload.slug or "",
                tags=payload.tags or "",
                meta_description=payload.meta_description or "",
                primary_keyword=payload.primary_keyword or "",
                secondary_keywords=payload.secondary_keywords or "",
                outline_content=payload.outline_content or "",
            )
    if requested == "content" and not str(suggestion or "").strip():
        suggestion = _fallback_content_html_from_payload(payload)
    # Defensive: some providers may return multiple lines; normalize for single-line fields.
    if requested in {"title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords", "target_website"}:
        parts = [x.strip() for x in str(suggestion or "").replace("\r", "").split("\n") if x.strip()]
        suggestion = parts[0] if parts else str(suggestion or "").strip()
    fmt = (request.query_params.get("format") or "").strip().lower()
    if fmt == "text":
        return Response(content=str(suggestion or ""), media_type="text/plain; charset=utf-8")
    knowledge_used = False
    pk_for_kb = (payload.primary_keyword or "").strip()
    if pk_for_kb:
        try:
            from app.services.content_ai_knowledge_context import get_relevant_knowledge_for_keyword

            kb_hit = get_relevant_knowledge_for_keyword(
                pk_for_kb,
                target_website=payload.target_website or "",
            )
            knowledge_used = bool(kb_hit.get("found"))
        except Exception:
            knowledge_used = False
    record_content_ai_usage(
        db,
        current_user,
        feature_key,
        quantity=1,
        metadata={"field": requested, "intent": detected_intent},
    )
    db.commit()
    return JSONResponse(
        content={
            "value": suggestion,
            "detected_intent": detected_intent,
            "knowledge_used": knowledge_used,
        }
    )


@router.post("/content-ai/suggest-stream")
def content_ai_suggest_stream(
    request: Request,
    payload: ContentSuggestRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Stream suggestion progressively as SSE.
    This is UI-focused: we may generate full text then emit it line-by-line.
    """
    from app.services.user_api_access import assert_user_may_use_api

    assert_user_may_use_api(current_user)
    feature_key = feature_for_suggest_field(payload.field)
    assert_content_ai_feature(db, current_user, feature_key, quantity=1)
    requested = (payload.field or "").strip().lower()
    if requested != "target_website" and not (payload.primary_keyword or "").strip():
        raise HTTPException(status_code=400, detail="Vui long nhap tu khoa chinh truoc khi goi y AI.")

    delay_ms_raw = (request.query_params.get("delay_ms") or "").strip()
    try:
        delay_ms = int(delay_ms_raw) if delay_ms_raw else 10
    except ValueError:
        delay_ms = 10
    delay_ms = max(0, min(delay_ms, 120))

    allow_fallback = (request.query_params.get("fallback") or "").strip().lower() in {"1", "true", "yes"}

    def _emit_sse_delta(delta: str) -> str:
        return f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"

    def _emit_sse_done() -> str:
        return "data: [DONE]\n\n"

    def _emit_sse_error(msg: str) -> str:
        return f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"

    def _stream_content_delta_chunks(value: str) -> Any:
        for chunk in _content_to_stream_chunks(value, chunk_size=72):
            if chunk:
                yield _emit_sse_delta(chunk)

    def _sse_content_live():
        """True LLM token streaming for field=content."""
        from app.services.llm_content_writer import iter_content_ai_content_stream_deltas

        any_delta = False
        try:
            for delta in iter_content_ai_content_stream_deltas(
                title=payload.title or "",
                content=payload.content or "",
                target_website=payload.target_website or "",
                slug=payload.slug or "",
                tags=payload.tags or "",
                meta_description=payload.meta_description or "",
                primary_keyword=payload.primary_keyword or "",
                secondary_keywords=payload.secondary_keywords or "",
                outline_content=payload.outline_content or "",
                target_word_count=payload.target_word_count,
            ):
                if not str(delta or ""):
                    continue
                any_delta = True
                yield _emit_sse_delta(str(delta))
            if not any_delta:
                raise RuntimeError("LLM stream returned no deltas")
            record_db = SessionLocal()
            try:
                record_content_ai_usage(
                    record_db,
                    current_user,
                    feature_key,
                    quantity=1,
                    metadata={"field": requested, "stream": True, "live": True},
                )
                record_db.commit()
            finally:
                record_db.close()
            yield _emit_sse_done()
        except Exception as exc:
            if not allow_fallback:
                yield _emit_sse_error(str(exc)[:1200])
                return
            value = _fallback_content_html_from_payload(payload)
            if not str(value or "").strip():
                yield _emit_sse_error(str(exc)[:1200])
                return
            yield from _stream_content_delta_chunks(value)
            record_db = SessionLocal()
            try:
                record_content_ai_usage(
                    record_db,
                    current_user,
                    feature_key,
                    quantity=1,
                    metadata={"field": requested, "stream": True, "fallback": True},
                )
                record_db.commit()
            finally:
                record_db.close()
            yield _emit_sse_done()

    def _generate() -> str:
        llm_cfg = None
        try:
            llm_cfg = load_llm_config()
        except Exception:
            llm_cfg = None
        llm_mode = (os.getenv("CONTENT_AI_LLM_MODE", "auto") or "auto").strip().lower()
        if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
            llm_mode = "auto"
        llm_fields = _content_ai_llm_enabled_fields(llm_mode)
        if llm_mode == "auto" and requested == "content" and not llm_cfg:
            raise RuntimeError(
                "CONTENT_AI_LLM_MODE=auto: field content cần LLM (API key). Không sinh HTML content bằng rule-based."
            )
        use_llm = _should_use_llm_for_suggest(
            request, requested, llm_cfg=llm_cfg, llm_fields=llm_fields
        )
        if use_llm:
            try:
                generated = generate_content_ai_suggestion(
                    field=payload.field,
                    title=payload.title or "",
                    content=payload.content or "",
                    target_website=payload.target_website or "",
                    slug=payload.slug or "",
                    tags=payload.tags or "",
                    meta_description=payload.meta_description or "",
                    primary_keyword=payload.primary_keyword or "",
                    secondary_keywords=payload.secondary_keywords or "",
                    outline_content=payload.outline_content or "",
                    target_word_count=payload.target_word_count,
                )
                if requested == "content" and not str(generated or "").strip():
                    generated = _fallback_content_html_from_payload(payload)
                return generated
            except Exception as exc:
                if not allow_fallback and not _is_llm_transient_error(exc):
                    raise
                if requested == "content":
                    return _fallback_content_html_from_payload(payload)
        if llm_mode == "auto" and requested == "content":
            return _fallback_content_html_from_payload(payload)
        out = suggest_content_ai_field(
            field=payload.field,
            title=payload.title or "",
            content=payload.content or "",
            target_website=payload.target_website or "",
            slug=payload.slug or "",
            tags=payload.tags or "",
            meta_description=payload.meta_description or "",
            primary_keyword=payload.primary_keyword or "",
            secondary_keywords=payload.secondary_keywords or "",
            outline_content=payload.outline_content or "",
        )
        if requested == "content" and not str(out or "").strip():
            return _fallback_content_html_from_payload(payload)
        return out

    def _sse():
        if requested == "content":
            llm_cfg = None
            try:
                llm_cfg = load_llm_config()
            except Exception:
                llm_cfg = None
            llm_mode = (os.getenv("CONTENT_AI_LLM_MODE", "auto") or "auto").strip().lower()
            if llm_mode not in {"off", "auto", "title_meta_only", "content_only"}:
                llm_mode = "auto"
            llm_fields = _content_ai_llm_enabled_fields(llm_mode)
            use_llm = _should_use_llm_for_suggest(
                request, requested, llm_cfg=llm_cfg, llm_fields=llm_fields
            )
            if use_llm and llm_cfg:
                yield from _sse_content_live()
                return
            try:
                value = _generate()
                if not str(value or "").strip():
                    value = _fallback_content_html_from_payload(payload)
                yield from _stream_content_delta_chunks(value)
                record_db = SessionLocal()
                try:
                    record_content_ai_usage(
                        record_db,
                        current_user,
                        feature_key,
                        quantity=1,
                        metadata={"field": requested, "stream": True, "rule": True},
                    )
                    record_db.commit()
                finally:
                    record_db.close()
                yield _emit_sse_done()
            except Exception as exc:
                if allow_fallback:
                    value = _fallback_content_html_from_payload(payload)
                    yield from _stream_content_delta_chunks(value)
                    record_db = SessionLocal()
                    try:
                        record_content_ai_usage(
                            record_db,
                            current_user,
                            feature_key,
                            quantity=1,
                            metadata={"field": requested, "stream": True, "fallback": True},
                        )
                        record_db.commit()
                    finally:
                        record_db.close()
                    yield _emit_sse_done()
                else:
                    yield _emit_sse_error(str(exc)[:1200])
            return

        # Non-content fields: legacy event-based SSE (short outputs).
        yield f"event:meta\ndata:{json.dumps({'total': 0, 'status': 'generating'})}\n\n"
        try:
            value = _generate()
            if requested == "content" and not str(value or "").strip():
                value = _fallback_content_html_from_payload(payload)
            lines = _content_to_stream_chunks(value) if requested == "content" else [str(value or "")]
            if requested == "content" and not lines:
                value = _fallback_content_html_from_payload(payload)
                lines = _content_to_stream_chunks(value)
            total = max(1, len(lines))
            yield f"event:meta\ndata:{json.dumps({'total': total})}\n\n"
            buf: list[str] = []
            for idx, line in enumerate(lines):
                buf.append(line)
                pct = int(round(((idx + 1) / total) * 100))
                payload_obj = {"pct": pct, "line": line, "sofar": "\n".join(buf)}
                yield f"event:chunk\ndata:{json.dumps(payload_obj, ensure_ascii=False)}\n\n"
                if delay_ms:
                    time.sleep(delay_ms / 1000.0)
            record_db = SessionLocal()
            try:
                record_content_ai_usage(
                    record_db,
                    current_user,
                    feature_key,
                    quantity=1,
                    metadata={"field": requested, "stream": True},
                )
                record_db.commit()
            finally:
                record_db.close()
            yield f"event:done\ndata:{json.dumps({'ok': True, 'value': value}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            if requested == "content":
                value = _fallback_content_html_from_payload(payload)
                lines = _content_to_stream_chunks(value)
                total = max(1, len(lines))
                yield f"event:meta\ndata:{json.dumps({'total': total})}\n\n"
                buf: list[str] = []
                for idx, line in enumerate(lines):
                    buf.append(line)
                    pct = int(round(((idx + 1) / total) * 100))
                    payload_obj = {"pct": pct, "line": line, "sofar": "\n".join(buf)}
                    yield f"event:chunk\ndata:{json.dumps(payload_obj, ensure_ascii=False)}\n\n"
                    if delay_ms:
                        time.sleep(delay_ms / 1000.0)
                record_db = SessionLocal()
                try:
                    record_content_ai_usage(
                        record_db,
                        current_user,
                        feature_key,
                        quantity=1,
                        metadata={"field": requested, "stream": True, "fallback": True},
                    )
                    record_db.commit()
                finally:
                    record_db.close()
                yield f"event:done\ndata:{json.dumps({'ok': True, 'value': value}, ensure_ascii=False)}\n\n"
                return
            msg = str(exc)[:1200]
            yield f"event:error\ndata:{json.dumps({'ok': False, 'error': msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class OutlineReferenceRequest(BaseModel):
    competitor_url: str


class OutlineRefreshRequest(BaseModel):
    outline: str


class WordpressDraftPublishRequest(BaseModel):
    wp_url: str
    username: str
    app_password: str
    draft_payload: dict
    seo_plugin: str | None = "auto"
    primary_keyword: str | None = None
    publish_mode: str | None = "draft"  # "draft" | "publish"


_OUTLINE_SYNONYM_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("khóa học", ("chương trình", "lộ trình", "khóa học")),
    ("đào tạo", ("huấn luyện", "đào tạo", "hướng dẫn")),
    ("học viên", ("người học", "học viên", "học viên tham gia")),
    ("cam kết", ("bảo chứng", "cam kết", "đảm bảo")),
    ("thực chiến", ("ứng dụng thực tế", "thực chiến", "triển khai thực tế")),
    ("chuyên sâu", ("toàn diện", "chuyên sâu", "nâng cao")),
    ("hỗ trợ", ("đồng hành", "hỗ trợ", "tư vấn")),
    ("tối ưu", ("cải thiện", "tối ưu", "nâng cấp")),
    ("quy trình", ("lộ trình", "quy trình", "cách triển khai")),
    ("bứt phá", ("tăng tốc", "bứt phá", "vượt trội")),
]


def _refresh_outline_with_synonyms(outline: str) -> str:
    text = str(outline or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    refreshed: list[str] = []
    for idx, line in enumerate(lines):
        current = line
        if not line.strip():
            refreshed.append(line)
            continue
        for key, choices in _OUTLINE_SYNONYM_GROUPS:
            pattern = re.compile(rf"\b{re.escape(key)}\b", flags=re.I)
            if pattern.search(current):
                choice = choices[(idx + len(key) + random.randint(0, 2)) % len(choices)]

                def _replace(_m: re.Match[str]) -> str:
                    src = _m.group(0)
                    if src.isupper():
                        return choice.upper()
                    if src[:1].isupper():
                        return choice[:1].upper() + choice[1:]
                    return choice

                current = pattern.sub(_replace, current)
        refreshed.append(current)
    return "\n".join(refreshed)


def _extract_outline_fallback(soup: BeautifulSoup) -> list[str]:
    lines: list[str] = []
    title = ""
    if soup.title:
        title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
    if title:
        lines.append(f"# {title}")

    toc_nodes = soup.select("nav a, .toc a, [class*='toc'] a")
    for n in toc_nodes:
        txt = re.sub(r"\s+", " ", n.get_text(" ", strip=True)).strip()
        if len(txt) >= 5:
            line = f"## {txt}"
            if line not in lines:
                lines.append(line)
            if len(lines) >= 25:
                break

    if len(lines) < 6:
        blocks = soup.select("article p strong, article h4, article h5, main p strong, main h4, main h5")
        for b in blocks:
            txt = re.sub(r"\s+", " ", b.get_text(" ", strip=True)).strip()
            if len(txt) < 8:
                continue
            line = f"## {txt}"
            if line not in lines:
                lines.append(line)
            if len(lines) >= 25:
                break
    return lines


@router.post("/content-ai/outline-reference")
def content_ai_outline_reference(
    payload: OutlineReferenceRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    raw_url = (payload.competitor_url or "").strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Vui lòng nhập link đối thủ.")
    parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Link đối thủ không hợp lệ.")
    url = parsed.geturl()
    try:
        resp = requests.get(
            url,
            timeout=18,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
                )
            },
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Không thể truy cập link đối thủ. Vui lòng kiểm tra lại URL (đúng domain, có https).",
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Trang đối thủ trả HTTP {resp.status_code}.")

    # Requests sometimes defaults to ISO-8859-1 when headers are missing/incorrect,
    # which breaks Vietnamese diacritics. Prefer detected encoding when needed.
    enc = (resp.encoding or "").strip().lower()
    if (not enc) or enc in {"iso-8859-1", "latin-1"}:
        try:
            resp.encoding = resp.apparent_encoding or "utf-8"
        except Exception:
            resp.encoding = "utf-8"

    soup = BeautifulSoup(resp.text or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    headings: list[str] = []
    for node in soup.select("h1, h2, h3"):
        level = (node.name or "").lower()
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if not text:
            continue
        prefix = {"h1": "#", "h2": "##", "h3": "###"}.get(level, "##")
        line = f"{prefix} {text}"
        if line not in headings:
            headings.append(line)
    if not headings:
        headings = _extract_outline_fallback(soup)
    if not headings:
        parsed_path = (parsed.path or "").strip("/")
        if parsed_path:
            topic = re.sub(r"[-_/]+", " ", parsed_path).strip()
            topic = re.sub(r"\s+", " ", topic)
            if topic:
                headings = [f"# {topic.title()}"]
    if not headings:
        raise HTTPException(
            status_code=422,
            detail="Không trích xuất được outline từ link này. Thử URL bài viết chi tiết khác.",
        )
    return JSONResponse(content={"url": url, "outline": "\n".join(headings), "count": len(headings)})


@router.post("/content-ai/outline-refresh")
def content_ai_outline_refresh(
    payload: OutlineRefreshRequest,
    current_user: User = Depends(require_active_trial),
) -> JSONResponse:
    outline = str(payload.outline or "").strip()
    if not outline:
        raise HTTPException(status_code=400, detail="Vui lòng nhập outline trước.")
    refreshed = _refresh_outline_with_synonyms(outline)
    if not refreshed:
        raise HTTPException(status_code=422, detail="Không thể làm mới outline.")
    return JSONResponse(content={"outline": refreshed})


def _normalize_wp_base_url(wp_url: str) -> str:
    raw = (wp_url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Vui lòng nhập WP URL.")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="WP URL không hợp lệ.")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _wp_request(
    *,
    session: requests.Session,
    method: str,
    url: str,
    logs: list[str],
    step: str,
    **kwargs,
) -> requests.Response:
    try:
        resp = session.request(method, url, timeout=25, **kwargs)
    except requests.RequestException as exc:
        logs.append(f"[{step}] Network error: {exc}")
        raise HTTPException(status_code=502, detail={"message": "Lỗi kết nối WordPress.", "logs": logs}) from exc
    logs.append(f"[{step}] HTTP {resp.status_code} {url}")
    return resp


def _build_wp_session(username: str, app_password: str, *, strip_spaces: bool) -> requests.Session:
    user = (username or "").strip()
    pwd = (app_password or "").strip()
    if strip_spaces:
        pwd = re.sub(r"\s+", "", pwd)
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    session = requests.Session()
    session.auth = (user, pwd)
    # Some hosts/proxies drop implicit auth; send explicit Authorization too.
    session.headers.update(
        {
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        }
    )
    return session


def _ensure_wp_tag_ids(
    *,
    session: requests.Session,
    wp_base: str,
    tags: list[str],
    logs: list[str],
) -> list[int]:
    out: list[int] = []
    for tag in tags:
        name = re.sub(r"\s+", " ", str(tag or "").strip())
        if not name:
            continue
        search_url = f"{wp_base}/wp-json/wp/v2/tags"
        resp = _wp_request(
            session=session,
            method="GET",
            url=search_url,
            logs=logs,
            step=f"tag-search:{name}",
            params={"search": name, "per_page": 100},
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:600]
            logs.append(f"[tag-search:{name}] response: {detail}")
            continue
        found_id = None
        try:
            items = resp.json()
        except ValueError:
            items = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name") or "").strip().lower() == name.lower():
                    try:
                        found_id = int(item.get("id"))
                    except (TypeError, ValueError):
                        found_id = None
                    break
        if found_id is None:
            c = _wp_request(
                session=session,
                method="POST",
                url=search_url,
                logs=logs,
                step=f"tag-create:{name}",
                json={"name": name},
            )
            if c.status_code >= 400:
                logs.append(f"[tag-create:{name}] failed: {(c.text or '')[:600]}")
                continue
            try:
                created = c.json()
                found_id = int(created.get("id"))
            except (ValueError, TypeError, AttributeError):
                found_id = None
        if found_id is not None and found_id not in out:
            out.append(found_id)
    return out


def _detect_wp_seo_plugin(*, session: requests.Session, wp_base: str, logs: list[str]) -> str:
    root = _wp_request(
        session=session,
        method="GET",
        url=f"{wp_base}/wp-json",
        logs=logs,
        step="wp-root",
    )
    if root.status_code >= 400:
        return "unknown"
    try:
        data = root.json()
    except ValueError:
        return "unknown"
    namespaces = data.get("namespaces") if isinstance(data, dict) else []
    ns = set(namespaces or [])
    if any("rankmath" in str(x).lower() for x in ns):
        logs.append("[seo-plugin] detected rankmath")
        return "rankmath"
    if any("yoast" in str(x).lower() for x in ns):
        logs.append("[seo-plugin] detected yoast")
        return "yoast"
    logs.append("[seo-plugin] not detected")
    return "unknown"


def _read_image_payload(featured_image: str, logs: list[str]) -> tuple[bytes, str, str] | None:
    src = str(featured_image or "").strip()
    if not src:
        return None
    if src.startswith("/static/"):
        local = Path(".") / src.lstrip("/")
        if not local.exists() or not local.is_file():
            logs.append(f"[featured-image] local file not found: {local}")
            return None
        blob = local.read_bytes()
        filename = local.name
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return blob, filename, ctype

    try:
        r = requests.get(src, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        logs.append(f"[featured-image] fetch failed: {exc}")
        return None
    if r.status_code >= 400:
        logs.append(f"[featured-image] fetch HTTP {r.status_code}: {src}")
        return None
    parsed = urlparse(src)
    filename = Path(parsed.path or "").name or f"featured-{uuid4().hex[:8]}.jpg"
    ctype = r.headers.get("Content-Type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return r.content, filename, ctype


def _upload_featured_media(
    *,
    session: requests.Session,
    wp_base: str,
    featured_image: str,
    logs: list[str],
) -> int | None:
    payload = _read_image_payload(featured_image, logs)
    if not payload:
        return None
    blob, filename, ctype = payload
    media_url = f"{wp_base}/wp-json/wp/v2/media"
    resp = _wp_request(
        session=session,
        method="POST",
        url=media_url,
        logs=logs,
        step="media-upload",
        data=blob,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": ctype,
        },
    )
    if resp.status_code >= 400:
        logs.append(f"[media-upload] failed: {(resp.text or '')[:700]}")
        return None
    try:
        data = resp.json()
        media_id = int(data.get("id"))
    except (ValueError, TypeError, AttributeError):
        logs.append("[media-upload] invalid response payload")
        return None
    logs.append(f"[media-upload] success media_id={media_id}")
    return media_id


def _upload_media_from_src(
    *,
    session: requests.Session,
    wp_base: str,
    src: str,
    logs: list[str],
) -> str | None:
    payload = _read_image_payload(src, logs)
    if not payload:
        return None
    blob, filename, ctype = payload
    media_url = f"{wp_base}/wp-json/wp/v2/media"
    resp = _wp_request(
        session=session,
        method="POST",
        url=media_url,
        logs=logs,
        step=f"inline-media-upload:{filename}",
        data=blob,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": ctype,
        },
    )
    if resp.status_code >= 400:
        logs.append(f"[inline-media-upload] failed src={src}: {(resp.text or '')[:700]}")
        return None
    try:
        data = resp.json()
    except ValueError:
        logs.append(f"[inline-media-upload] invalid JSON response for src={src}")
        return None
    out_url = str(data.get("source_url") or "").strip()
    if out_url:
        return out_url
    try:
        rendered = (((data.get("guid") or {}) if isinstance(data, dict) else {}).get("rendered") or "")
        out_url = str(rendered).strip()
    except Exception:
        out_url = ""
    if not out_url:
        logs.append(f"[inline-media-upload] missing source_url for src={src}")
        return None
    return out_url


def _rewrite_inline_images_for_wp(
    *,
    session: requests.Session,
    wp_base: str,
    content_html: str,
    logs: list[str],
) -> str:
    raw = str(content_html or "").strip()
    if not raw:
        return raw
    soup = BeautifulSoup(raw, "html.parser")
    imgs = soup.find_all("img")
    if not imgs:
        return raw
    cache: dict[str, str | None] = {}
    replaced = 0
    for img in imgs:
        src = str(img.get("src") or "").strip()
        if not src:
            continue
        if src not in cache:
            cache[src] = _upload_media_from_src(session=session, wp_base=wp_base, src=src, logs=logs)
        new_src = cache.get(src) or ""
        if new_src:
            img["src"] = new_src
            replaced += 1
    logs.append(f"[inline-media] replaced {replaced}/{len(imgs)} image src")
    return str(soup)


def _ensure_blockquote_inline_style(content_html: str) -> str:
    raw = str(content_html or "").strip()
    if not raw:
        return raw
    soup = BeautifulSoup(raw, "html.parser")
    for bq in soup.find_all("blockquote"):
        style = str(bq.get("style") or "").strip().rstrip(";")
        needed = [
            "border-left: 4px solid #38bdf8",
            "background: #f8fafc",
            "color: #0f172a",
            "padding: 12px 14px",
            "border-radius: 8px",
            "margin: 12px 0",
        ]
        merged = style
        style_lc = style.lower()
        for rule in needed:
            key = rule.split(":", 1)[0].strip().lower()
            if key not in style_lc:
                merged = f"{merged}; {rule}".strip("; ").strip()
        if merged:
            bq["style"] = merged
    return str(soup)


def _derive_focus_keyword(
    *,
    explicit_primary_keyword: str,
    draft: dict,
) -> str:
    kw = re.sub(r"\s+", " ", str(explicit_primary_keyword or "").strip())
    if kw:
        return kw
    draft_kw = re.sub(r"\s+", " ", str(draft.get("primary_keyword") or "").strip())
    if draft_kw:
        return draft_kw
    slug = str(draft.get("slug") or "").strip()
    if slug:
        parsed = urlparse(slug if "://" in slug else f"https://x.local/{slug.lstrip('/')}")
        parts = [p for p in (parsed.path or "").split("/") if p]
        if parts:
            from_slug = re.sub(r"[-_]+", " ", parts[-1]).strip()
            if from_slug:
                return from_slug
    title = re.sub(r"\s+", " ", str(draft.get("title") or "").strip())
    if title:
        tokens = title.split(" ")
        return " ".join(tokens[:5]).strip()
    return ""


def _slugify_wp(value: str) -> str:
    s = (value or "").replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-{2,}", "-", s)


def _normalize_wp_slug(slug: str, fallback_title: str) -> str:
    raw = str(slug or "").strip()
    if raw:
        parsed = urlparse(raw if "://" in raw else f"https://x.local/{raw.lstrip('/')}")
        parts = [p for p in (parsed.path or "").split("/") if p]
        if parts:
            candidate = _slugify_wp(parts[-1])
            if candidate:
                return candidate
    fallback = _slugify_wp(fallback_title or "")
    return fallback or "draft-post"


def _trim_seo_title(title: str, max_len: int = 60) -> str:
    t = re.sub(r"\s+", " ", str(title or "").strip())
    if len(t) <= max_len:
        return t
    if "|" in t:
        first = re.sub(r"\s+", " ", t.split("|", 1)[0].strip())
        if first and len(first) <= max_len:
            return first
    words = t.split(" ")
    out = ""
    for w in words:
        cand = (out + " " + w).strip()
        if len(cand) > max_len:
            break
        out = cand
    if out:
        return out
    return t[:max_len].strip()


def _normalize_meta_description(meta_description: str, fallback_text: str = "") -> str:
    src = re.sub(r"\s+", " ", str(meta_description or "").strip())
    if not src:
        src = re.sub(r"\s+", " ", str(fallback_text or "").strip())
    if len(src) <= 160:
        return src
    cut = src[:160]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


def _update_post_seo_meta(
    *,
    session: requests.Session,
    wp_base: str,
    post_id: int,
    meta_description: str,
    seo_title: str,
    focus_keyword: str,
    seo_plugin_mode: str,
    detected_plugin: str,
    logs: list[str],
) -> None:
    desc = str(meta_description or "").strip()
    seo_t = str(seo_title or "").strip()
    focus = str(focus_keyword or "").strip()
    if not desc and not focus and not seo_t:
        return
    plugin = (seo_plugin_mode or "auto").strip().lower()
    target = detected_plugin if plugin == "auto" else plugin
    key_sets: list[dict[str, str]] = []
    if target == "rankmath":
        key_sets = [
            {"title": "rank_math_title", "description": "rank_math_description", "focus": "rank_math_focus_keyword"},
            # Some sites/plugins expose private-style keys only.
            {"title": "_rank_math_title", "description": "_rank_math_description", "focus": "_rank_math_focus_keyword"},
        ]
    elif target == "yoast":
        key_sets = [{"title": "yoast_wpseo_title", "description": "yoast_wpseo_metadesc", "focus": "yoast_wpseo_focuskw"}]
    elif target == "none":
        logs.append("[seo-meta] skipped by plugin mode=none")
        return
    else:
        # unknown -> try both
        key_sets = [
            {"title": "rank_math_title", "description": "rank_math_description", "focus": "rank_math_focus_keyword"},
            {"title": "_rank_math_title", "description": "_rank_math_description", "focus": "_rank_math_focus_keyword"},
            {"title": "yoast_wpseo_title", "description": "yoast_wpseo_metadesc", "focus": "yoast_wpseo_focuskw"},
        ]

    ok_any = False
    for key_set in key_sets:
        meta_payload: dict[str, str] = {}
        if seo_t and key_set.get("title"):
            meta_payload[key_set["title"]] = seo_t
        if desc and key_set.get("description"):
            meta_payload[key_set["description"]] = desc
        if focus and key_set.get("focus"):
            meta_payload[key_set["focus"]] = focus
        if not meta_payload:
            continue
        key_label = f"{key_set.get('title','')},{key_set.get('description','')},{key_set.get('focus','')}".strip(",")
        body = {"meta": meta_payload}
        url = f"{wp_base}/wp-json/wp/v2/posts/{post_id}"
        resp = _wp_request(
            session=session,
            method="POST",
            url=url,
            logs=logs,
            step=f"seo-meta:{key_label}",
            json=body,
        )
        if resp.status_code < 400:
            logs.append(f"[seo-meta:{key_label}] success")
            ok_any = True
            if target in ("rankmath", "yoast"):
                break
        else:
            logs.append(f"[seo-meta:{key_label}] failed: {(resp.text or '')[:600]}")

        # Fallback: try direct top-level payload for plugins hooking into post update fields.
        direct_payload: dict[str, str] = {}
        if seo_t and key_set.get("title"):
            direct_payload[key_set["title"]] = seo_t
        if desc and key_set.get("description"):
            direct_payload[key_set["description"]] = desc
        if focus and key_set.get("focus"):
            direct_payload[key_set["focus"]] = focus
        if direct_payload:
            direct_resp = _wp_request(
                session=session,
                method="POST",
                url=url,
                logs=logs,
                step=f"seo-meta-direct:{key_label}",
                json=direct_payload,
            )
            if direct_resp.status_code < 400:
                logs.append(f"[seo-meta-direct:{key_label}] success")
                ok_any = True
                if target in ("rankmath", "yoast"):
                    break
            else:
                logs.append(f"[seo-meta-direct:{key_label}] failed: {(direct_resp.text or '')[:600]}")
    if not ok_any:
        logs.append("[seo-meta] no plugin meta key updated (plugin may hide meta from REST)")
        logs.append("[seo-meta] tip: bật Rank Math REST API / Headless support để cho phép ghi meta qua WP REST.")


def _update_rankmath_via_plugin_endpoint(
    *,
    session: requests.Session,
    wp_base: str,
    post_id: int,
    seo_title: str,
    meta_description: str,
    focus_keyword: str,
    logs: list[str],
) -> bool:
    title = str(seo_title or "").strip()
    desc = str(meta_description or "").strip()
    focus = str(focus_keyword or "").strip()
    payload_meta = {
        "rank_math_title": title,
        "rank_math_description": desc,
        "rank_math_focus_keyword": focus,
    }
    # Common endpoint variants seen across Rank Math versions/setups.
    candidates = [
        (
            f"{wp_base}/wp-json/rankmath/v1/updateMeta",
            {
                "objectID": post_id,
                "objectType": "post",
                "meta": payload_meta,
            },
        ),
        (
            f"{wp_base}/wp-json/rankmath/v1/updateMeta",
            {
                "object_id": post_id,
                "object_type": "post",
                "meta": payload_meta,
            },
        ),
        (
            f"{wp_base}/wp-json/rankmath/v1/saveMeta",
            {
                "postID": post_id,
                "meta": payload_meta,
            },
        ),
    ]
    ok = False
    for url, body in candidates:
        resp = _wp_request(
            session=session,
            method="POST",
            url=url,
            logs=logs,
            step="rankmath-plugin-meta",
            json=body,
        )
        if resp.status_code < 400:
            logs.append(f"[rankmath-plugin-meta] success via {url}")
            ok = True
            break
        logs.append(f"[rankmath-plugin-meta] failed via {url}: {(resp.text or '')[:500]}")
    return ok


@router.post("/content-ai/wordpress/test-connection")
def content_ai_wordpress_test_connection(
    payload: WordPressConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    result = _check_wp_site(
        {
            "url": payload.url,
            "username": payload.username,
            "app_password": payload.app_password,
        }
    )
    return JSONResponse(
        {
            "ok": result["verified"],
            "message": result["message"],
            "plugin_installed": result["plugin_installed"],
        }
    )


@router.post("/content-ai/wordpress/categories")
def content_ai_wordpress_categories(
    payload: WordPressConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Liệt kê category (wp/v2/categories) — dùng cho dropdown khi viết bulk / đăng bài."""
    from app.services.wp_categories import fetch_wordpress_categories

    result = fetch_wordpress_categories(
        url=payload.url,
        username=payload.username,
        app_password=payload.app_password,
    )
    return JSONResponse(content=result)


@router.post("/content-ai/wordpress/sync-posts")
def content_ai_wordpress_sync_posts(
    payload: WordPressConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    check = _check_wp_site(
        {
            "url": payload.url,
            "username": payload.username,
            "app_password": payload.app_password,
        }
    )
    if not check["verified"]:
        return JSONResponse({"ok": False, "count": None, "message": check["message"]})
    count, msg = _wp_posts_count(payload.url, payload.username, payload.app_password)
    if count is None:
        return JSONResponse({"ok": False, "count": None, "message": msg})
    plugin_note = (
        " Seoauto SEO Helper đã cài."
        if check["plugin_installed"]
        else " Seoauto SEO Helper chưa cài — nên cài plugin để tối ưu SEO khi đăng bài."
    )
    return JSONResponse({"ok": True, "count": count, "message": msg + plugin_note})


@router.post("/content-ai/haravan/test-connection")
def content_ai_haravan_test_connection(
    payload: HaravanConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    result = _check_haravan_site({"app_password": payload.private_token})
    return JSONResponse({"ok": result["verified"], "message": result["message"]})


@router.post("/content-ai/haravan/sync-blogs")
def content_ai_haravan_sync_blogs(
    payload: HaravanConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    count, msg = _haravan_sync_blogs_count(payload.private_token)
    return JSONResponse({"ok": count is not None, "count": count, "message": msg})


@router.post("/content-ai/publish-draft")
def content_ai_publish_draft(
    request: Request,
    payload: WordpressDraftPublishRequest,
    current_user: User = Depends(require_active_trial),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_content_ai_feature(db, current_user, "wp_publish", quantity=1)
    wp_base = _normalize_wp_base_url(payload.wp_url)
    username = (payload.username or "").strip()
    app_password = (payload.app_password or "").strip()
    if not username or not app_password:
        raise HTTPException(status_code=400, detail="Vui lòng nhập username và app password.")
    draft = payload.draft_payload if isinstance(payload.draft_payload, dict) else {}
    title_raw = str(draft.get("title") or "").strip()
    content = str(draft.get("content") or "").strip()
    slug_raw = str(draft.get("slug") or "").strip()
    meta_description_raw = str(draft.get("meta_description") or "").strip()
    title = _trim_seo_title(title_raw, max_len=60)
    slug = _normalize_wp_slug(slug_raw, title_raw)
    meta_description = _normalize_meta_description(meta_description_raw, fallback_text=title_raw)
    featured_image = str(draft.get("featured_image") or "").strip()
    if not featured_image:
        gallery = draft.get("gallery_images") or []
        if isinstance(gallery, list):
            for img in gallery:
                candidate = str(img or "").strip()
                if candidate:
                    featured_image = candidate
                    break
    if not title or not content:
        raise HTTPException(status_code=400, detail="Draft payload thiếu title hoặc content.")

    logs: list[str] = []
    session: requests.Session | None = None
    me: requests.Response | None = None
    auth_attempts = [
        ("raw", False),
        ("strip-spaces", True),
    ]
    for label, strip_spaces in auth_attempts:
        candidate = _build_wp_session(username, app_password, strip_spaces=strip_spaces)
        attempt_logs: list[str] = []
        resp = _wp_request(
            session=candidate,
            method="GET",
            url=f"{wp_base}/wp-json/wp/v2/users/me",
            logs=attempt_logs,
            step=f"auth-check:{label}",
        )
        if resp.status_code < 400:
            logs.extend(attempt_logs)
            logs.append(f"[auth-check] success via mode={label}")
            session = candidate
            me = resp
            break
        attempt_logs.append(f"[auth-check:{label}] response: {(resp.text or '')[:600]}")
        logs.extend(attempt_logs)
    if session is None or me is None:
        logs.append("[auth-check] tip: dùng Application Password (không dùng mật khẩu đăng nhập thường).")
        logs.append("[auth-check] tip: kiểm tra plugin bảo mật/CDN có chặn Authorization header không.")
        raise HTTPException(
            status_code=401,
            detail={"message": "Xác thực WordPress thất bại. Kiểm tra username/app password.", "logs": logs},
        )

    detected_plugin = _detect_wp_seo_plugin(session=session, wp_base=wp_base, logs=logs)
    seo_plugin_mode = str(payload.seo_plugin or "auto").strip().lower()
    if seo_plugin_mode not in {"auto", "yoast", "rankmath", "none"}:
        seo_plugin_mode = "auto"
    logs.append(f"[seo-plugin] mode={seo_plugin_mode}")

    tags_raw = draft.get("tags") or []
    tags_clean: list[str] = []
    if isinstance(tags_raw, list):
        seen: set[str] = set()
        for t in tags_raw:
            c = re.sub(r"\s+", " ", str(t or "").strip())
            if not c:
                continue
            k = c.lower()
            if k in seen:
                continue
            seen.add(k)
            tags_clean.append(c)
    tag_ids = _ensure_wp_tag_ids(session=session, wp_base=wp_base, tags=tags_clean, logs=logs)
    cat_ids: list[int] = []
    cats_raw = draft.get("categories")
    if isinstance(cats_raw, list):
        for x in cats_raw:
            try:
                cid = int(x)
            except (TypeError, ValueError):
                continue
            if cid > 0 and cid not in cat_ids:
                cat_ids.append(cid)
    elif cats_raw is not None:
        try:
            cid = int(cats_raw)
        except (TypeError, ValueError):
            cid = 0
        if cid > 0:
            cat_ids.append(cid)
    cat_ids = cat_ids[:20]
    mode = str(payload.publish_mode or "draft").strip().lower()
    if mode not in {"draft", "publish"}:
        mode = "draft"
    # Convert local/temporary image URLs in content to WordPress media URLs
    # so draft posts always show images on the target website.
    content = _rewrite_inline_images_for_wp(session=session, wp_base=wp_base, content_html=content, logs=logs)
    # Preserve blockquote color/visual style on WordPress theme by inlining style.
    content = _ensure_blockquote_inline_style(content)

    post_body: dict = {
        "title": title,
        "content": content,
        "slug": slug,
        # draft: always save as draft (never publish)
        # publish: publish now unless scheduled_at is future (then status=future)
        "status": "draft" if mode == "draft" else "publish",
    }
    if meta_description:
        post_body["excerpt"] = meta_description
    if tag_ids:
        post_body["tags"] = tag_ids
    if cat_ids:
        post_body["categories"] = cat_ids
        logs.append(f"[categories] assigned={cat_ids}")
    media_id = _upload_featured_media(
        session=session,
        wp_base=wp_base,
        featured_image=featured_image,
        logs=logs,
    )
    if media_id is not None:
        post_body["featured_media"] = media_id

    scheduled_at = str(draft.get("scheduled_at") or "").strip()
    if scheduled_at:
        try:
            # UI uses <input type="datetime-local"> -> usually naive local time "YYYY-MM-DDTHH:MM".
            dt = datetime.fromisoformat(scheduled_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            now = datetime.now(dt.tzinfo)
            if mode == "publish":
                # If schedule is in the future -> create a scheduled post (status=future)
                if dt > (now + timedelta(seconds=30)):
                    post_body["status"] = "future"
            # WordPress accepts both date + date_gmt; sending both prevents timezone surprises.
            post_body["date"] = dt.replace(microsecond=0).isoformat()
            dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
            post_body["date_gmt"] = dt_utc.isoformat()
            logs.append(f"[schedule] mode={mode} status={post_body.get('status')} date={post_body.get('date')}")
        except ValueError:
            logs.append(f"[schedule] Invalid datetime ignored: {scheduled_at}")
    else:
        logs.append(f"[schedule] mode={mode} scheduled_at empty")

    created = _wp_request(
        session=session,
        method="POST",
        url=f"{wp_base}/wp-json/wp/v2/posts",
        logs=logs,
        step="create-draft",
        json=post_body,
    )
    if created.status_code >= 400:
        logs.append(f"[create-draft] response: {(created.text or '')[:1200]}")
        raise HTTPException(
            status_code=502,
            detail={"message": "Tạo bản nháp WordPress thất bại.", "logs": logs},
        )
    try:
        data = created.json()
    except ValueError as exc:
        logs.append("[create-draft] Invalid JSON response from WordPress")
        raise HTTPException(
            status_code=502,
            detail={"message": "WordPress trả dữ liệu không hợp lệ.", "logs": logs},
        ) from exc

    try:
        created_post_id = int(data.get("id"))
    except (TypeError, ValueError):
        created_post_id = 0
    if created_post_id > 0:
        # Ensure snippet core fields are persisted even when SEO plugin meta is restricted.
        _wp_request(
            session=session,
            method="POST",
            url=f"{wp_base}/wp-json/wp/v2/posts/{created_post_id}",
            logs=logs,
            step="post-snippet-core-sync",
            json={"title": title, "excerpt": meta_description},
        )
        focus_keyword = _derive_focus_keyword(
            explicit_primary_keyword=str(payload.primary_keyword or ""),
            draft=draft,
        )
        _update_post_seo_meta(
            session=session,
            wp_base=wp_base,
            post_id=created_post_id,
            meta_description=meta_description,
            seo_title=title,
            focus_keyword=focus_keyword,
            seo_plugin_mode=seo_plugin_mode,
            detected_plugin=detected_plugin,
            logs=logs,
        )
        # Extra fallback for sites where Rank Math meta is blocked on wp/v2 posts route.
        if (seo_plugin_mode == "rankmath") or (seo_plugin_mode == "auto" and detected_plugin == "rankmath"):
            _update_rankmath_via_plugin_endpoint(
                session=session,
                wp_base=wp_base,
                post_id=created_post_id,
                seo_title=title,
                meta_description=meta_description,
                focus_keyword=focus_keyword,
                logs=logs,
            )

    log_audit_event(
        action="publish.wordpress",
        user_id=current_user.id,
        resource_type="wordpress",
        resource_id=str(data.get("id") or ""),
        detail={"url": wp_base, "status": data.get("status")},
        request=request,
    )
    record_content_ai_usage(
        db,
        current_user,
        "wp_publish",
        quantity=1,
        metadata={"post_id": data.get("id"), "wp_url": wp_base},
        idempotency_key=f"wp-publish:{data.get('id')}",
    )
    db.commit()
    return JSONResponse(
        content={
            "ok": True,
            "post_id": data.get("id"),
            "status": data.get("status"),
            "link": data.get("link"),
            "edit_link": (data.get("_links", {}).get("self", [{}])[0] or {}).get("href", ""),
            "normalized_slug": slug,
            "fixed_meta_description": meta_description,
            "seo_title": title,
            "featured_media": media_id,
            "seo_plugin_mode": seo_plugin_mode,
            "seo_plugin_detected": detected_plugin,
            "logs": logs,
        }
    )
