"""Social Auto — Web 2.0 Publisher API (/api/social/web20)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db

from app.models.user import User
from app.services.auth import get_current_user
from app.services.rbac import normalize_role
from app.services.social_auto_generator import generate_web20_article
from app.services.social_auto_web20_safety import run_web20_safety_checks
from app.services.social_auto_web20_publish import publish_web20_post
from app.services.social_auto_scheduler import run_social_auto_scheduler
from app.services.social_auto_web20_store import (
    _find_account,
    _find_post,
    append_log,
    create_account,
    create_manual_account,
    create_medium_account,
    create_oauth_account,
    create_post,
    delete_account,
    get_account_credentials,
    get_account_secrets,
    get_settings,
    list_accounts,
    list_logs,
    list_posts,
    save_settings,
    update_account,
    update_post,
)
from app.services.web20_internal_auth import require_web20_internal_or_admin
from app.services.social_auto_web20_wp import test_wp_connection
from app.services.web20_providers import get_provider, list_platforms
from app.services.web20_platform_status import (
    CARD_STATUS_LABELS,
    PLATFORM_META,
    platform_card_status,
    supports_auto_publish,
)
from app.services.web20_platform_status import assert_account_publish_ready
from app.services.web20_providers import blogger as blogger_oauth
from app.services.web20_providers import tumblr as tumblr_oauth
from app.services.web20_providers.medium import fetch_user as medium_fetch_user

router = APIRouter(prefix="/web20", tags=["social-auto-web20"])
# Public Google Console redirect: /api/integrations/blogger/callback
blogger_integrations_router = APIRouter(tags=["social-auto-web20"])


class Web20AccountCreate(BaseModel):
    site_url: str = Field(..., min_length=4, max_length=2000)
    username: str = Field(..., min_length=1, max_length=120)
    app_password: str = Field(..., min_length=4, max_length=256)
    label: str = Field(default="", max_length=120)
    default_status: str = Field(default="draft", max_length=32)


class Web20AccountPatch(BaseModel):
    site_url: str | None = Field(default=None, max_length=2000)
    username: str | None = Field(default=None, max_length=120)
    app_password: str | None = Field(default=None, max_length=256)
    label: str | None = Field(default=None, max_length=120)
    default_status: str | None = Field(default=None, max_length=32)
    external_id: str | None = Field(default=None, max_length=256)
    main_site_url: str | None = Field(default=None, max_length=2000)


class Web20MediumConnect(BaseModel):
    integration_token: str = Field(..., min_length=8, max_length=512)
    label: str = Field(default="", max_length=120)
    default_status: str = Field(default="draft", max_length=32)


class Web20ManualConnect(BaseModel):
    label: str = Field(default="Google Sites Manual", max_length=120)
    site_url: str = Field(default="", max_length=2000)
    main_site_url: str = Field(default="", max_length=2000)


class Web20PostCreate(BaseModel):
    account_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(default="", max_length=500)
    slug: str = Field(default="", max_length=200)
    excerpt: str = Field(default="", max_length=2000)
    html_content: str = Field(default="", max_length=100000)
    tags: list[str] = Field(default_factory=list)
    category: str = Field(default="", max_length=120)
    wp_status: str = Field(default="draft", max_length=32)
    main_site_url: str = Field(default="", max_length=2000)
    source_title: str = Field(default="", max_length=500)
    source_content: str = Field(default="", max_length=50000)


class Web20PostPatch(BaseModel):
    account_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    slug: str | None = Field(default=None, max_length=200)
    excerpt: str | None = Field(default=None, max_length=2000)
    html_content: str | None = Field(default=None, max_length=100000)
    tags: list[str] | None = None
    category: str | None = Field(default=None, max_length=120)
    wp_status: str | None = Field(default=None, max_length=32)
    main_site_url: str | None = Field(default=None, max_length=2000)
    scheduled_at: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)


class Web20ScheduleBody(BaseModel):
    scheduled_at: str = Field(..., min_length=8, max_length=64)


class Web20SettingsPatch(BaseModel):
    max_posts_per_account_per_day: int | None = Field(default=None, ge=1, le=10)
    default_wp_status: str | None = Field(default=None, max_length=32)


class Web20GenerateBody(BaseModel):
    account_id: str = Field(..., min_length=8, max_length=64)
    source_title: str = Field(..., min_length=1, max_length=500)
    source_content: str = Field(default="", max_length=50000)
    keyword: str = Field(default="", max_length=200)
    target_url: str = Field(default="", max_length=2000)
    main_site_url: str = Field(default="", max_length=2000)
    tone: str = Field(default="chuyên gia", max_length=100)


class Web20SafetyBody(BaseModel):
    title: str = Field(default="", max_length=500)
    html_content: str = Field(default="", max_length=100000)
    account_id: str = Field(default="", max_length=64)
    main_site_url: str = Field(default="", max_length=2000)
    source_content: str = Field(default="", max_length=50000)
    post_id: str | None = Field(default=None, max_length=64)


def _role(user: User) -> str:
    return normalize_role(getattr(user, "role", None))


def _require_account(account_id: str, user_id: int, role: str | None = None) -> dict[str, Any]:
    row = _find_account(account_id, user_id, role)
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản Web 2.0.")
    return row


@router.get("/settings")
def api_web20_settings(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"settings": get_settings(current_user.id)}


@router.patch("/settings")
def api_web20_patch_settings(
    body: Web20SettingsPatch,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = save_settings(current_user.id, body.model_dump(exclude_unset=True))
    return {"settings": item}


@router.get("/platforms")
def api_web20_platforms(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    from app.services.web20_providers.blogger import is_mock_mode as blogger_mock
    from app.services.web20_providers.tumblr import is_mock_mode as tumblr_mock

    user_accounts = list_accounts(current_user.id, role=_role(current_user))
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for acc in user_accounts:
        pf = str(acc.get("platform") or "")
        by_platform.setdefault(pf, []).append(acc)

    items = list_platforms()
    for p in items:
        pid = p.get("id")
        meta = PLATFORM_META.get(str(pid), {})
        p["publish_mode"] = meta.get("publish_mode") or "auto"
        p["supports_auto_publish"] = bool(meta.get("supports_auto_publish"))
        p["card_status"] = platform_card_status(str(pid), by_platform.get(str(pid), []))
        p["card_status_label"] = CARD_STATUS_LABELS.get(p["card_status"], p["card_status"])
        if pid == "blogger":
            p["oauth_mode"] = "mock" if blogger_mock() else "live"
        elif pid == "tumblr":
            p["oauth_mode"] = "mock" if tumblr_mock() else "live"
        elif pid == "medium":
            p["oauth_mode"] = "beta"
        elif pid == "google_sites_manual":
            p["oauth_mode"] = "manual"
        else:
            p["oauth_mode"] = "live"

    zalo_meta = PLATFORM_META["zalo_oa"]
    items.append(
        {
            "id": "zalo_oa",
            "label": zalo_meta["label"],
            "publish_mode": zalo_meta["publish_mode"],
            "supports_auto_publish": False,
            "card_status": platform_card_status("zalo_oa", []),
            "card_status_label": CARD_STATUS_LABELS["coming_soon"],
            "oauth_mode": "coming_soon",
        }
    )
    return {"items": items}


@router.get("/accounts")
def api_web20_accounts(
    platform: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": list_accounts(current_user.id, platform=platform, role=_role(current_user))}


@router.post("/accounts")
def api_web20_create_account(
    body: Web20AccountCreate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    test = test_wp_connection(
        site_url=body.site_url,
        username=body.username,
        app_password=body.app_password,
    )
    if not test.get("ok"):
        raise HTTPException(status_code=400, detail=test.get("message") or "Không kết nối được WordPress 2.0.")
    item = create_account(
        user_id=current_user.id,
        site_url=str(test.get("working_url") or body.site_url),
        username=body.username,
        app_password=body.app_password,
        label=body.label,
        default_status=body.default_status or "draft",
    )
    update_account(
        item["id"],
        current_user.id,
        {"last_test_at": item.get("connected_at"), "last_test_message": test.get("message")},
    )
    append_log(current_user.id, code="account_connected", message=f"Kết nối WP {item.get('site_url')}", account_id=item["id"])
    return {"item": item, "items": list_accounts(current_user.id)}


@router.post("/accounts/medium")
def api_web20_connect_medium(
    body: Web20MediumConnect,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user = medium_fetch_user(body.integration_token.strip())
    item = create_medium_account(
        user_id=current_user.id,
        integration_token=body.integration_token.strip(),
        medium_user_id=str(user.get("id") or ""),
        label=body.label or f"Medium @{user.get('username') or user.get('id')}",
        default_status=body.default_status or "draft",
    )
    append_log(current_user.id, code="account_connected", message=f"Kết nối Medium @{user.get('username')}", account_id=item["id"])
    return {"item": item, "items": list_accounts(current_user.id)}


@router.post("/accounts/google-sites-manual")
def api_web20_connect_manual(
    body: Web20ManualConnect,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    item = create_manual_account(
        user_id=current_user.id,
        label=body.label,
        site_url=body.site_url,
        main_site_url=body.main_site_url,
    )
    append_log(current_user.id, code="account_connected", message="Thêm Google Sites Manual", account_id=item["id"])
    return {"item": item, "items": list_accounts(current_user.id)}


@router.get("/blogger/oauth/start")
def api_blogger_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return blogger_oauth.oauth_start_url(request, current_user.id)


def _finish_blogger_oauth(request: Request, code: str, state: str) -> RedirectResponse:
    if not code or not state:
        return RedirectResponse(url="/social-auto?web20=error&platform=blogger", status_code=302)
    try:
        data = blogger_oauth.handle_oauth_callback(request, code, state)
    except Exception:
        return RedirectResponse(url="/social-auto?web20=error&platform=blogger", status_code=302)
    user_id = int(data["user_id"])
    item = create_oauth_account(
        user_id=user_id,
        platform="blogger",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        blogs=data.get("blogs") or [],
        external_id=str(data.get("active_blog_id") or ""),
        label=(data.get("blogs") or [{}])[0].get("name") if data.get("blogs") else "Blogger",
    )
    append_log(user_id, code="account_connected", message="Kết nối Blogger OAuth", account_id=item["id"])
    return RedirectResponse(url="/social-auto?web20=connected&platform=blogger", status_code=302)


@router.get("/blogger/oauth/callback")
def api_blogger_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> RedirectResponse:
    return _finish_blogger_oauth(request, code, state)


@blogger_integrations_router.get("/blogger/callback")
def api_blogger_integrations_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> RedirectResponse:
    """Alias matching Google Cloud Authorized redirect URI."""
    return _finish_blogger_oauth(request, code, state)


@router.get("/blogger/oauth/mock-callback")
def api_blogger_mock_callback(
    request: Request,
    state: str = Query(default=""),
) -> RedirectResponse:
    data = blogger_oauth.handle_oauth_callback(request, "mock", state)
    user_id = int(data["user_id"])
    create_oauth_account(
        user_id=user_id,
        platform="blogger",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        blogs=data.get("blogs") or [],
        external_id=str(data.get("active_blog_id") or ""),
        label="Blogger Mock",
    )
    return RedirectResponse(url="/social-auto?web20=connected&platform=blogger", status_code=302)


@router.get("/tumblr/oauth/start")
def api_tumblr_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return tumblr_oauth.oauth_start_url(request, current_user.id)


@router.get("/tumblr/oauth/callback")
def api_tumblr_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> RedirectResponse:
    if not code or not state:
        return RedirectResponse(url="/social-auto?web20=error&platform=tumblr", status_code=302)
    data = tumblr_oauth.handle_oauth_callback(request, code, state)
    user_id = int(data["user_id"])
    item = create_oauth_account(
        user_id=user_id,
        platform="tumblr",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        blogs=data.get("blogs") or [],
        external_id=str(data.get("active_blog_id") or ""),
        label=(data.get("blogs") or [{}])[0].get("name") if data.get("blogs") else "Tumblr",
    )
    append_log(user_id, code="account_connected", message="Kết nối Tumblr OAuth", account_id=item["id"])
    return RedirectResponse(url="/social-auto?web20=connected&platform=tumblr", status_code=302)


@router.get("/tumblr/oauth/mock-callback")
def api_tumblr_mock_callback(
    request: Request,
    state: str = Query(default=""),
) -> RedirectResponse:
    data = tumblr_oauth.handle_oauth_callback(request, "mock", state)
    user_id = int(data["user_id"])
    create_oauth_account(
        user_id=user_id,
        platform="tumblr",
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        blogs=data.get("blogs") or [],
        external_id=str(data.get("active_blog_id") or ""),
        label="Tumblr Mock",
    )
    return RedirectResponse(url="/social-auto?web20=connected&platform=tumblr", status_code=302)


@router.patch("/accounts/{account_id}")
def api_web20_patch_account(
    account_id: str,
    body: Web20AccountPatch,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    item = update_account(account_id, current_user.id, patch)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    return {"item": item, "items": list_accounts(current_user.id)}


@router.delete("/accounts/{account_id}")
def api_web20_delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not delete_account(account_id, current_user.id):
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    append_log(current_user.id, code="account_deleted", message="Đã xóa tài khoản Web 2.0", account_id=account_id)
    return {"ok": True, "items": list_accounts(current_user.id)}


@router.post("/accounts/{account_id}/test")
def api_web20_test_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    account = _require_account(account_id, current_user.id)
    platform = str(account.get("platform") or "wordpress_2_0")
    secrets = get_account_secrets(account_id, current_user.id)
    provider = get_provider(platform)
    test = provider.test_connection(account, secrets)
    patch: dict[str, Any] = {
        "last_test_at": datetime.now(timezone.utc).isoformat(),
        "last_test_message": test.get("message") or "",
        "status": "connected" if test.get("ok") else "error",
    }
    if test.get("blogs"):
        patch["blogs"] = test["blogs"]
    if test.get("working_url"):
        patch["site_url"] = test["working_url"]
    update_account(account_id, current_user.id, patch)
    return test


@router.get("/posts")
def api_web20_posts(
    account_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": list_posts(current_user.id, account_id=account_id, role=_role(current_user))}


@router.post("/posts")
def api_web20_create_post(
    body: Web20PostCreate,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    account = _require_account(body.account_id, current_user.id)
    secrets = get_account_secrets(body.account_id, current_user.id)
    wp_status = body.wp_status or secrets.get("default_status") or "draft"
    if not str(body.title or "").strip() or not str(body.html_content or "").strip():
        raise HTTPException(status_code=400, detail="Cần title và nội dung HTML.")
    item = create_post(
        user_id=current_user.id,
        account_id=body.account_id,
        title=body.title,
        slug=body.slug,
        excerpt=body.excerpt,
        html_content=body.html_content,
        tags=body.tags,
        category=body.category,
        wp_status=wp_status,
        main_site_url=body.main_site_url,
        source_title=body.source_title,
        source_content=body.source_content,
    )
    safety = run_web20_safety_checks(
        current_user.id,
        title=item.get("title") or "",
        html_content=item.get("html_content") or "",
        account_id=body.account_id,
        main_site_url=body.main_site_url,
        source_content=body.source_content,
        exclude_post_id=item.get("id"),
    )
    update_post(item["id"], current_user.id, {"safety_score": safety["score"], "safety_passed": safety["passed"]})
    item["safety"] = safety
    return {"item": item, "items": list_posts(current_user.id)}


@router.patch("/posts/{post_id}")
def api_web20_patch_post(
    post_id: str,
    body: Web20PostPatch,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    patch = body.model_dump(exclude_unset=True)
    item = update_post(post_id, current_user.id, patch)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    return {"item": item, "items": list_posts(current_user.id)}


@router.post("/generate")
def api_web20_generate(
    body: Web20GenerateBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_account(body.account_id, current_user.id)
    gen = generate_web20_article(
        user_id=current_user.id,
        source_title=body.source_title,
        source_content=body.source_content,
        keyword=body.keyword,
        target_url=body.target_url,
        main_site_url=body.main_site_url or body.target_url,
        tone=body.tone,
    )
    item = create_post(
        user_id=current_user.id,
        account_id=body.account_id,
        title=gen.get("title") or body.source_title,
        slug=gen.get("slug") or "",
        excerpt=gen.get("excerpt") or "",
        html_content=gen.get("html_content") or "",
        tags=gen.get("tags") or [],
        category=gen.get("category") or "",
        wp_status=gen.get("wp_status") or "draft",
        main_site_url=gen.get("main_site_url") or body.main_site_url or body.target_url,
        source_title=body.source_title,
        source_content=body.source_content,
    )
    safety = run_web20_safety_checks(
        current_user.id,
        title=item.get("title") or "",
        html_content=item.get("html_content") or "",
        account_id=body.account_id,
        main_site_url=item.get("main_site_url") or "",
        source_content=body.source_content,
        exclude_post_id=item.get("id"),
    )
    update_post(item["id"], current_user.id, {"safety_score": safety["score"], "safety_passed": safety["passed"]})
    item = {**item, "safety": safety}
    return {"generated": gen, "item": item, "safety": safety}


@router.post("/safety/check")
def api_web20_safety_inline(
    body: Web20SafetyBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if body.account_id and (not str(body.title or "").strip() or not str(body.html_content or "").strip()):
        raise HTTPException(status_code=400, detail="Cần account, title và nội dung để kiểm tra Safety.")
    safety = run_web20_safety_checks(
        current_user.id,
        title=body.title,
        html_content=body.html_content,
        account_id=body.account_id,
        main_site_url=body.main_site_url,
        source_content=body.source_content,
        exclude_post_id=body.post_id,
    )
    return {"safety": safety}


@router.post("/posts/{post_id}/safety-check")
def api_web20_safety(
    post_id: str,
    body: Web20SafetyBody | None = None,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = _find_post(post_id, current_user.id, _role(current_user))
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    b = body or Web20SafetyBody()
    title = b.title or str(row.get("title") or "")
    html = b.html_content or str(row.get("html_content") or "")
    account_id = b.account_id or str(row.get("account_id") or "")
    safety = run_web20_safety_checks(
        current_user.id,
        title=title,
        html_content=html,
        account_id=account_id,
        main_site_url=b.main_site_url or str(row.get("main_site_url") or ""),
        source_content=b.source_content or str(row.get("source_content") or ""),
        exclude_post_id=post_id,
    )
    update_post(post_id, current_user.id, {"safety_score": safety["score"], "safety_passed": safety["passed"]})
    return {"safety": safety, "post_id": post_id}


@router.post("/posts/{post_id}/publish")
def api_web20_publish(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return publish_web20_post(post_id, current_user.id, db=db, user=current_user, source="manual", skip_schedule_check=True)


@router.post("/posts/{post_id}/schedule")
def api_web20_schedule(
    post_id: str,
    body: Web20ScheduleBody,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = _find_post(post_id, current_user.id, _role(current_user))
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    account_id = str(row.get("account_id") or "")
    account = _require_account(account_id, current_user.id, _role(current_user))
    assert_account_publish_ready(account, source="schedule", for_schedule=True)
    if str(account.get("platform") or "") == "google_sites_manual":
        raise HTTPException(status_code=400, detail="Google Sites chỉ hỗ trợ Manual Package — không lên lịch tự động.")
    if not str(row.get("title") or "").strip() or not str(row.get("html_content") or "").strip():
        raise HTTPException(status_code=400, detail="Cần title và nội dung trước khi lên lịch.")
    safety = run_web20_safety_checks(
        current_user.id,
        title=str(row.get("title") or ""),
        html_content=str(row.get("html_content") or ""),
        account_id=account_id,
        main_site_url=str(row.get("main_site_url") or ""),
        source_content=str(row.get("source_content") or ""),
        exclude_post_id=post_id,
    )
    if not safety.get("can_publish"):
        raise HTTPException(status_code=400, detail={"message": "Safety chưa đạt.", "safety": safety})
    item = update_post(
        post_id,
        current_user.id,
        {
            "status": "scheduled",
            "scheduled_at": body.scheduled_at,
            "safety_score": safety["score"],
            "safety_passed": safety["passed"],
            "error_message": None,
        },
    )
    append_log(
        current_user.id,
        code="scheduled",
        message=f"Lên lịch đăng: {body.scheduled_at}",
        account_id=account_id,
        post_id=post_id,
    )
    return {"item": item, "safety": safety}


@router.post("/posts/{post_id}/retry")
def api_web20_retry(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = _find_post(post_id, current_user.id, _role(current_user))
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    if str(row.get("status") or "") not in {"failed", "retrying"}:
        raise HTTPException(status_code=400, detail="Chỉ retry bài failed/retrying.")
    update_post(post_id, current_user.id, {"status": "draft", "error_message": None})
    return publish_web20_post(post_id, current_user.id, db=db, user=current_user, source="retry", skip_schedule_check=True)


@router.post("/posts/{post_id}/cancel-schedule")
def api_web20_cancel_schedule(
    post_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = _find_post(post_id, current_user.id, _role(current_user))
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    item = update_post(post_id, current_user.id, {"status": "cancelled", "scheduled_at": None, "next_retry_at": None})
    return {"item": item}


@router.post("/scheduler/run")
def api_web20_scheduler_run(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _gate: User | None = Depends(require_web20_internal_or_admin),
) -> dict[str, Any]:
    return run_social_auto_scheduler(db=db, limit=limit)


@router.get("/logs")
def api_web20_logs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": list_logs(current_user.id, limit=limit, role=_role(current_user))}
