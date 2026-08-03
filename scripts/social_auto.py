"""Social Auto API — campaigns, posts, AI variants (MVP)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.models.user import User
from app.services.auth import get_current_user
from app.services.social_auto_facebook_service import (
    build_preview,
    facebook_oauth_configured,
    handle_oauth_callback,
    mock_connect,
    oauth_start_url,
    publish_to_fanpage,
)
from app.services.social_auto_facebook_store import (
    disconnect_page,
    get_active_page,
    get_safety_settings,
    is_mock_mode,
    list_api_logs,
    list_pages,
    save_safety_settings,
    set_active_page,
)
from app.services.social_auto_generator import generate_facebook_variant
from app.services.social_auto_safety import run_safety_checks
from app.services.social_auto_store import (
    _find_campaign,
    _find_post,
    cancel_schedule,
    create_campaign,
    create_post,
    get_overview_stats,
    list_campaigns,
    list_posts,
    mark_published,
    schedule_post,
    update_campaign,
    update_post,
    upsert_variant_post,
)

router = APIRouter(tags=["social-auto"])


class CampaignCreateBody(BaseModel):
    name: str = Field(default="", max_length=200)
    source_title: str = Field(default="", max_length=500)
    source_content: str = Field(default="", max_length=50000)
    keyword: str = Field(default="", max_length=200)
    target_url: str = Field(default="", max_length=2000)
    status: str = Field(default="draft", max_length=32)


class CampaignPatchBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    source_title: str | None = Field(default=None, max_length=500)
    source_content: str | None = Field(default=None, max_length=50000)
    keyword: str | None = Field(default=None, max_length=200)
    target_url: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=32)


class PostCreateBody(BaseModel):
    campaign_id: str = Field(..., min_length=8, max_length=64)
    platform: str = Field(..., max_length=32)
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=20000)
    hashtags: str = Field(default="", max_length=500)
    cta: str = Field(default="", max_length=1000)
    status: str = Field(default="draft", max_length=32)


class PostPatchBody(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=20000)
    hashtags: str | None = Field(default=None, max_length=500)
    cta: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, max_length=32)
    scheduled_at: str | None = Field(default=None, max_length=64)
    published_url: str | None = Field(default=None, max_length=2000)
    error_message: str | None = Field(default=None, max_length=2000)


class ScheduleBody(BaseModel):
    scheduled_at: str = Field(..., min_length=8, max_length=64)
    page_id: str | None = Field(default=None, max_length=64)


class SafetySettingsBody(BaseModel):
    max_posts_per_day: int | None = Field(default=None, ge=1, le=10)
    min_hours_between_posts: int | None = Field(default=None, ge=1, le=12)
    auto_stop_on_rate_limit: bool | None = None
    auto_stop_on_permission_error: bool | None = None
    clear_pause: bool | None = None


class SafetyCheckBody(BaseModel):
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=20000)
    hashtags: str = Field(default="", max_length=500)
    keyword: str = Field(default="", max_length=200)
    source_content: str = Field(default="", max_length=50000)
    source_title: str = Field(default="", max_length=500)
    scheduled_at: str | None = Field(default=None, max_length=64)
    page_id: str | None = Field(default=None, max_length=64)
    post_id: str | None = Field(default=None, max_length=64)


class PreviewBody(BaseModel):
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=20000)
    hashtags: str = Field(default="", max_length=500)
    cta: str = Field(default="", max_length=1000)
    page_id: str | None = Field(default=None, max_length=64)


class PublishNowBody(BaseModel):
    page_id: str | None = Field(default=None, max_length=64)


class MarkPublishedBody(BaseModel):
    published_url: str = Field(..., min_length=4, max_length=2000)


class GenerateVariantsBody(BaseModel):
    campaign_id: str | None = Field(default=None, max_length=64)
    name: str = Field(default="", max_length=200)
    source_title: str = Field(..., min_length=1, max_length=500)
    source_content: str = Field(default="", max_length=50000)
    keyword: str = Field(default="", max_length=200)
    target_url: str = Field(default="", max_length=2000)
    tone: str = Field(default="chuyên gia", max_length=100)
    cta: str = Field(default="", max_length=1000)


@router.get("/campaigns")
def api_list_campaigns(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    active = get_active_page(current_user.id)
    return {
        "items": list_campaigns(current_user.id),
        "stats": get_overview_stats(current_user.id),
        "facebook": {
            "configured": facebook_oauth_configured(),
            "mock_mode": is_mock_mode(),
            "pages": list_pages(current_user.id),
            "active_page": active,
            "safety": get_safety_settings(current_user.id),
        },
    }


@router.post("/campaigns")
def api_create_campaign(
    body: CampaignCreateBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = create_campaign(
        user_id=current_user.id,
        name=body.name,
        source_title=body.source_title,
        source_content=body.source_content,
        keyword=body.keyword,
        target_url=body.target_url,
        status=body.status,
    )
    return {"item": item}


@router.patch("/campaigns/{campaign_id}")
def api_patch_campaign(
    campaign_id: str,
    body: CampaignPatchBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Không có field cập nhật.")
    item = update_campaign(campaign_id, current_user.id, patch)
    return {"item": item}


@router.get("/posts")
def api_list_posts(
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {
        "items": list_posts(
            current_user.id,
            campaign_id=campaign_id,
            status=status,
            platform=platform,
        ),
    }


@router.post("/posts")
def api_create_post(
    body: PostCreateBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = create_post(
        user_id=current_user.id,
        campaign_id=body.campaign_id,
        platform=body.platform,
        title=body.title,
        content=body.content,
        hashtags=body.hashtags,
        cta=body.cta,
        status=body.status,
    )
    return {"item": item}


@router.patch("/posts/{post_id}")
def api_patch_post(
    post_id: str,
    body: PostPatchBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="Không có field cập nhật.")
    item = update_post(post_id, current_user.id, patch)
    return {"item": item}


@router.post("/posts/{post_id}/schedule")
def api_schedule_post(
    post_id: str,
    body: ScheduleBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    post = _find_post(post_id, current_user.id)
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    page_id = body.page_id or post.get("page_id")
    active = get_active_page(current_user.id)
    if not page_id and active:
        page_id = active.get("page_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="Chọn Fanpage trước khi lên lịch.")

    camp = _find_campaign(str(post.get("campaign_id") or ""), current_user.id)
    safety = run_safety_checks(
        current_user.id,
        title=str(post.get("title") or ""),
        content=str(post.get("content") or ""),
        hashtags=str(post.get("hashtags") or ""),
        keyword=str((camp or {}).get("keyword") or ""),
        source_content=str((camp or {}).get("source_content") or ""),
        source_title=str((camp or {}).get("source_title") or ""),
        scheduled_at=body.scheduled_at,
        page_id=str(page_id),
        exclude_post_id=post_id,
    )
    if not safety.get("can_schedule"):
        raise HTTPException(status_code=400, detail={"message": "Không đạt kiểm tra an toàn.", "safety": safety})

    update_post(post_id, current_user.id, {"page_id": str(page_id)})
    item = schedule_post(post_id, current_user.id, body.scheduled_at)
    return {"item": item, "safety": safety}


@router.post("/posts/{post_id}/cancel-schedule")
def api_cancel_schedule(
    post_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = cancel_schedule(post_id, current_user.id)
    return {"item": item}


@router.post("/posts/{post_id}/mark-published")
def api_mark_published(
    post_id: str,
    body: MarkPublishedBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = mark_published(post_id, current_user.id, body.published_url)
    return {"item": item}


@router.post("/generate-variants")
def api_generate_variants(
    body: GenerateVariantsBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if body.campaign_id:
        camp = _find_campaign(body.campaign_id, current_user.id)
        if not camp:
            raise HTTPException(status_code=404, detail="Không tìm thấy chiến dịch.")
        campaign_id = body.campaign_id
        update_campaign(
            campaign_id,
            current_user.id,
            {
                "source_title": body.source_title,
                "source_content": body.source_content,
                "keyword": body.keyword,
                "target_url": body.target_url,
                "status": "active",
            },
        )
    else:
        camp = create_campaign(
            user_id=current_user.id,
            name=body.name or body.source_title,
            source_title=body.source_title,
            source_content=body.source_content,
            keyword=body.keyword,
            target_url=body.target_url,
            status="active",
        )
        campaign_id = str(camp["id"])

    active = get_active_page(current_user.id)
    page_id = str(active.get("page_id")) if active else None

    fb = generate_facebook_variant(
        user_id=current_user.id,
        source_title=body.source_title,
        source_content=body.source_content,
        keyword=body.keyword,
        target_url=body.target_url,
        tone=body.tone,
        cta=body.cta,
    )

    post = upsert_variant_post(
        user_id=current_user.id,
        campaign_id=campaign_id,
        platform="facebook",
        title=fb.get("title") or body.source_title,
        content=fb.get("content") or "",
        hashtags=fb.get("hashtags") or "",
        cta=fb.get("cta") or body.cta,
        page_id=page_id,
    )

    safety = run_safety_checks(
        current_user.id,
        title=post.get("title") or "",
        content=post.get("content") or "",
        hashtags=post.get("hashtags") or "",
        keyword=body.keyword,
        source_content=body.source_content,
        source_title=body.source_title,
        page_id=page_id,
    )

    return {
        "campaign_id": campaign_id,
        "variants": {"facebook": fb},
        "posts": [post],
        "safety": safety,
        "stats": get_overview_stats(current_user.id),
    }


# —— Facebook Fanpage OAuth / Graph ——


@router.get("/facebook/status")
def api_facebook_status(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "configured": facebook_oauth_configured(),
        "mock_mode": is_mock_mode(),
        "pages": list_pages(current_user.id),
        "active_page": get_active_page(current_user.id),
        "safety": get_safety_settings(current_user.id),
    }


@router.get("/facebook/oauth/start")
def api_facebook_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return oauth_start_url(request, current_user.id)


@router.get("/facebook/oauth/callback")
def api_facebook_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> RedirectResponse:
    if is_mock_mode() and not code:
        from app.core.security import decode_facebook_oauth_state

        try:
            uid = decode_facebook_oauth_state(state)
            mock_connect(uid)
        except ValueError:
            pass
        return RedirectResponse(url="/social-auto?fb=connected", status_code=302)
    result = handle_oauth_callback(request, code, state)
    _ = result
    return RedirectResponse(url="/social-auto?fb=connected", status_code=302)


@router.get("/facebook/oauth/mock-callback")
def api_facebook_mock_callback(
    state: str = Query(...),
) -> RedirectResponse:
    from app.core.security import decode_facebook_oauth_state

    uid = decode_facebook_oauth_state(state)
    mock_connect(uid)
    return RedirectResponse(url="/social-auto?fb=connected", status_code=302)


@router.post("/facebook/pages/{page_id}/activate")
def api_facebook_activate_page(
    page_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        item = set_active_page(current_user.id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/facebook/pages/{page_id}")
def api_facebook_disconnect(
    page_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ok = disconnect_page(current_user.id, page_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage.")
    return {"ok": True}


# —— An toàn nền tảng ——


@router.get("/safety/settings")
def api_safety_settings(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"item": get_safety_settings(current_user.id)}


@router.patch("/safety/settings")
def api_patch_safety_settings(
    body: SafetySettingsBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    return {"item": save_safety_settings(current_user.id, patch)}


@router.post("/safety/check")
def api_safety_check(
    body: SafetyCheckBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return run_safety_checks(
        current_user.id,
        title=body.title,
        content=body.content,
        hashtags=body.hashtags,
        keyword=body.keyword,
        source_content=body.source_content,
        source_title=body.source_title,
        scheduled_at=body.scheduled_at,
        page_id=body.page_id,
        exclude_post_id=body.post_id,
    )


@router.get("/safety/logs")
def api_safety_logs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": list_api_logs(current_user.id, limit=limit)}


@router.post("/posts/preview")
def api_post_preview(
    body: PreviewBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    page = get_active_page(current_user.id)
    if body.page_id:
        pages = list_pages(current_user.id)
        page = next((p for p in pages if str(p.get("page_id")) == str(body.page_id)), page)
    message = "\n\n".join(x for x in [body.content, body.hashtags, body.cta] if x).strip()
    preview = build_preview(message, page_name=str((page or {}).get("page_name") or "Fanpage"))
    preview["title"] = body.title
    return {"preview": preview}


@router.post("/posts/{post_id}/publish-now")
def api_publish_now(
    post_id: str,
    body: PublishNowBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    post = _find_post(post_id, current_user.id)
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài đăng.")
    page_id = body.page_id or post.get("page_id")
    active = get_active_page(current_user.id)
    if not page_id and active:
        page_id = active.get("page_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="Chọn Fanpage trước khi đăng.")

    camp = _find_campaign(str(post.get("campaign_id") or ""), current_user.id)
    safety = run_safety_checks(
        current_user.id,
        title=str(post.get("title") or ""),
        content=str(post.get("content") or ""),
        hashtags=str(post.get("hashtags") or ""),
        keyword=str((camp or {}).get("keyword") or ""),
        source_content=str((camp or {}).get("source_content") or ""),
        source_title=str((camp or {}).get("source_title") or ""),
        page_id=str(page_id),
        exclude_post_id=post_id,
    )
    if not safety.get("passed"):
        raise HTTPException(status_code=400, detail={"message": "Không đạt kiểm tra an toàn.", "safety": safety})

    message = "\n\n".join(
        x for x in [post.get("content"), post.get("hashtags"), post.get("cta")] if x
    ).strip()
    result = publish_to_fanpage(current_user.id, str(page_id), message)
    item = mark_published(post_id, current_user.id, str(result.get("permalink_url") or ""))
    return {"item": item, "facebook": result, "safety": safety}
