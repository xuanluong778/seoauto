"""Google Map SEO — API kết nối Google Business Profile."""

from __future__ import annotations

import io
import logging
from typing import Any

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.credits import cost_google_map_ai_generate, credits_enforced
from app.services.plan_quota_registry import feature_key_for
from app.services.saas_gate import build_job_id, saas_action_gate
from app.services.tenant_org import personal_organization_id
from app.services.trial_access import require_active_trial
from app.services.google_map_gbp_service import (
    disconnect_user,
    get_status,
    handle_oauth_callback,
    list_user_locations,
    oauth_configured,
    oauth_start_url,
    sync_user_locations,
)
from app.services.plan_quota_service import assert_google_map_location_capacity, assert_plan_capability
from app.services.google_map_gbp_profile_service import (
    ai_generate,
    apply_to_gbp,
    list_drafts,
    save_draft,
)
from app.services.google_map_gbp_review_service import (
    ai_reply,
    get_reply_drafts,
    list_reviews,
    post_reply,
    save_reply_draft,
)
from app.services.google_map_gbp_post_service import (
    ai_generate as ai_generate_post,
    create_post,
    get_calendar,
    list_posts,
    publish_post,
    schedule_post,
    update_post,
)
from app.services.google_map_gbp_media_service import (
    ai_caption,
    audit_media,
    delete_media,
    get_reminder,
    list_media,
    publish_media,
    save_reminder,
    update_media,
    upload_media,
)
from app.services.google_map_gbp_verification_service import (
    delete_asset,
    get_verification,
    save_verification,
    upload_asset,
)
from app.services.google_map_gbp_competitor_service import analyze_competitors
from app.services.google_map_gbp_report_service import (
    build_report,
    export_report_csv,
    export_report_pdf,
    get_branding,
    save_branding,
)
from app.services.google_map_lead_scanner_service import (
    admin_usage_stats,
    export_scan,
    fetch_lead_detail,
    get_scan_detail,
    get_scanner_config,
    list_scan_history,
    quote_lead_detail_for_user,
    quote_scan,
    run_scan,
)

router = APIRouter(tags=["google-map-seo"])
_LOG = logging.getLogger(__name__)

_GBP_ERRORS = {
    "access_denied": "Bạn đã hủy cấp quyền Google Business Profile.",
    "no_refresh_token": "Google không trả refresh token. Hãy thử kết nối lại và chọn «Cho phép» đầy đủ.",
    "no_accounts": "Tài khoản Google không có quyền quản lý Business Profile nào.",
    "api_disabled": "api_disabled",
    "api_forbidden": "api_forbidden",
}


def _redirect_gbp_error(code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/google-map-seo?gbp_error={code}", status_code=302)


def _run_google_map_ai(db: Session, user: User, *, action: str, runner):
    """Central SaaS gate for Google Map AI — reserve → commit / release."""
    import uuid

    credit_cost = cost_google_map_ai_generate(db=db) if credits_enforced() else 0
    feature = feature_key_for("google_map_location")
    org_id = personal_organization_id(int(user.id))
    job_id = build_job_id("google_map_ai_generate", user.id, org_id, action, uuid.uuid4().hex[:10])
    with saas_action_gate(
        db,
        user,
        feature_code=feature,
        credit_cost=credit_cost,
        quota_units=1,
        job_id=job_id,
        idempotency_key=job_id,
        organization_id=org_id,
        charge_mode="reserve",
    ) as sgate:
        try:
            out = runner()
            sgate.commit()
            sgate.record_usage(metadata={"action": action, "organization_id": org_id})
            return out
        except Exception:
            sgate.release(reason=f"google_map_{action}_failed")
            raise


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


@router.get("/status")
def gbp_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_status(db, user))


@router.get("/oauth/status")
def gbp_oauth_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Alias for clients expecting /oauth/status."""
    return _ok(get_status(db, user))


@router.get("/locations")
def gbp_locations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(list_user_locations(db, user.id))


@router.post("/oauth/start")
def gbp_oauth_start(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình Google Business Profile OAuth trên server.",
        )
    assert_plan_capability(
        db,
        user,
        "google_map_seo",
        min_plan_slug="pro",
        message="Google Map SEO (GBP) chỉ có từ gói Pro. Gói Basic ưu tiên BYOK cho Content AI.",
    )
    return {"ok": True, **oauth_start_url(request, user.id)}


@router.get("/oauth/redirect")
def gbp_oauth_redirect(
    request: Request,
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    """Chuyển thẳng tới Google — dùng cookie seo_token khi user bấm Kết nối."""
    if not oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình Google Business Profile OAuth trên server.",
        )
    auth_url = oauth_start_url(request, user.id)["auth_url"]
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/oauth/callback")
def gbp_oauth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if error:
        return _redirect_gbp_error(error if error in _GBP_ERRORS else "access_denied")
    if not code or not state:
        return _redirect_gbp_error("missing_code")
    try:
        path = handle_oauth_callback(request, db, code=code, state=state)
    except Exception:
        _LOG.exception("GBP oauth callback failed")
        return _redirect_gbp_error("callback_failed")
    return RedirectResponse(url=path, status_code=302)


@router.post("/sync")
def gbp_sync(
    connection_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not oauth_configured():
        raise HTTPException(status_code=503, detail="Chưa cấu hình Google Business Profile OAuth.")
    current = len(list_user_locations(db, user.id))
    assert_google_map_location_capacity(db, user, current_count=current, adding=1)
    return _ok(sync_user_locations(db, user.id, connection_id=connection_id))


@router.post("/disconnect")
def gbp_disconnect(
    connection_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    n = disconnect_user(db, user.id, connection_id=connection_id)
    return _ok({"disconnected": n})


class GbpProfileInput(BaseModel):
    business_name: str = ""
    industry: str = ""
    locality: str = ""
    website: str = ""
    main_services: str = ""
    service_name: str = ""
    tone: str = "professional"


class GbpProfileGenerateBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    content_type: str = Field(..., min_length=1, max_length=48)
    input: GbpProfileInput = Field(default_factory=GbpProfileInput)


class GbpProfileDraftBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    content_type: str = Field(..., min_length=1, max_length=48)
    input: GbpProfileInput = Field(default_factory=GbpProfileInput)
    output_text: str = ""


class GbpProfileApplyBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    content_type: str = Field(..., min_length=1, max_length=48)
    content: str = Field(..., min_length=1, max_length=8000)


@router.get("/profile/drafts")
def gbp_profile_drafts(
    location_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(list_drafts(db, user.id, location_key=location_key))


@router.post("/profile/generate")
def gbp_profile_generate(
    body: GbpProfileGenerateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    return _ok(
        _run_google_map_ai(
            db,
            user,
            action="profile_generate",
            runner=lambda: ai_generate(
                db,
                user.id,
                location_key=body.location_key.strip(),
                content_type=body.content_type.strip(),
                input_data=body.input.model_dump(),
            ),
        )
    )


@router.post("/profile/drafts")
def gbp_profile_save_draft(
    body: GbpProfileDraftBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        save_draft(
            db,
            user.id,
            location_key=body.location_key.strip(),
            content_type=body.content_type.strip(),
            input_data=body.input.model_dump(),
            output_text=body.output_text,
        )
    )


@router.post("/profile/apply")
def gbp_profile_apply(
    body: GbpProfileApplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        apply_to_gbp(
            db,
            user.id,
            location_key=body.location_key.strip(),
            content_type=body.content_type.strip(),
            content=body.content,
        )
    )


class GbpReviewAiBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    review: dict[str, Any] = Field(default_factory=dict)
    tone: str = "professional"
    business: dict[str, Any] = Field(default_factory=dict)


class GbpReviewDraftBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    review_id: str = Field(..., min_length=1, max_length=128)
    tone: str = ""
    reply_text: str = ""


class GbpReviewPostBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    review_id: str = Field(..., min_length=1, max_length=128)
    review_resource_name: str = ""
    reply_text: str = Field(..., min_length=1, max_length=4096)


@router.get("/reviews")
def gbp_reviews_list(
    location_key: str = Query(..., min_length=1, max_length=64),
    filter: str = Query(default="all", alias="filter"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(list_reviews(db, user.id, location_key=location_key, review_filter=filter))


@router.get("/reviews/drafts")
def gbp_review_drafts(
    location_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_reply_drafts(db, user.id, location_key=location_key))


@router.post("/reviews/ai-reply")
def gbp_review_ai_reply(
    body: GbpReviewAiBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    return _ok(
        _run_google_map_ai(
            db,
            user,
            action="review_ai_reply",
            runner=lambda: ai_reply(
                db,
                user.id,
                location_key=body.location_key.strip(),
                review=body.review,
                tone=body.tone.strip(),
                business=body.business,
            ),
        )
    )


@router.post("/reviews/drafts")
def gbp_review_save_draft(
    body: GbpReviewDraftBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        save_reply_draft(
            db,
            user.id,
            location_key=body.location_key.strip(),
            review_id=body.review_id.strip(),
            tone=body.tone.strip(),
            reply_text=body.reply_text,
        )
    )


@router.post("/reviews/post")
def gbp_review_post(
    body: GbpReviewPostBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        post_reply(
            db,
            user.id,
            location_key=body.location_key.strip(),
            review_id=body.review_id.strip(),
            review_resource_name=body.review_resource_name.strip(),
            reply_text=body.reply_text,
        )
    )


class GbpPostInputBody(BaseModel):
    keywords: str = ""
    locality: str = ""
    goal: str = ""
    cta_type: str = "learn_more"
    business_name: str = ""


class GbpPostGenerateBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    post_type: str = Field(..., min_length=1, max_length=32)
    input: GbpPostInputBody = Field(default_factory=GbpPostInputBody)


class GbpPostCreateBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    post_type: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=8000)
    cta_type: str = "learn_more"
    cta_label: str = ""
    image_suggestions: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    scheduled_at: str = ""
    schedule_mode: str = ""


class GbpPostUpdateBody(BaseModel):
    title: str | None = None
    content: str | None = None
    cta_type: str | None = None
    cta_label: str | None = None
    image_suggestions: list[str] | None = None
    status: str | None = None
    scheduled_at: str | None = None
    schedule_mode: str | None = None


class GbpPostScheduleBody(BaseModel):
    scheduled_at: str = Field(..., min_length=8, max_length=40)
    schedule_mode: str = "once"


@router.get("/posts")
def gbp_posts_list(
    location_key: str = Query(..., min_length=1, max_length=64),
    status: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    sf = status.strip() or None
    return _ok(list_posts(db, user.id, location_key=location_key, status_filter=sf))


@router.get("/posts/calendar")
def gbp_posts_calendar(
    location_key: str = Query(..., min_length=1, max_length=64),
    date_from: str = Query(default="", alias="from"),
    date_to: str = Query(default="", alias="to"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        get_calendar(
            db,
            user.id,
            location_key=location_key,
            date_from=date_from.strip() or None,
            date_to=date_to.strip() or None,
        )
    )


@router.post("/posts/generate")
def gbp_posts_generate(
    body: GbpPostGenerateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    return _ok(
        _run_google_map_ai(
            db,
            user,
            action="posts_generate",
            runner=lambda: ai_generate_post(
                db,
                user.id,
                location_key=body.location_key.strip(),
                post_type=body.post_type.strip(),
                input_data=body.input.model_dump(),
            ),
        )
    )


@router.post("/posts")
def gbp_posts_create(
    body: GbpPostCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        create_post(
            db,
            user.id,
            location_key=body.location_key.strip(),
            post_type=body.post_type.strip(),
            title=body.title,
            content=body.content,
            cta_type=body.cta_type.strip(),
            cta_label=body.cta_label.strip(),
            image_suggestions=body.image_suggestions,
            input_data=body.input,
            status=body.status.strip(),
            scheduled_at=body.scheduled_at.strip() or None,
            schedule_mode=body.schedule_mode.strip() or None,
        )
    )


@router.patch("/posts/{post_id}")
def gbp_posts_update(
    post_id: int,
    body: GbpPostUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        update_post(
            db,
            user.id,
            post_id,
            title=body.title,
            content=body.content,
            cta_type=body.cta_type,
            cta_label=body.cta_label,
            image_suggestions=body.image_suggestions,
            status=body.status,
            scheduled_at=body.scheduled_at,
            schedule_mode=body.schedule_mode,
        )
    )


@router.post("/posts/{post_id}/schedule")
def gbp_posts_schedule(
    post_id: int,
    body: GbpPostScheduleBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        schedule_post(
            db,
            user.id,
            post_id,
            scheduled_at=body.scheduled_at.strip(),
            schedule_mode=body.schedule_mode.strip(),
        )
    )


@router.post("/posts/{post_id}/publish")
def gbp_posts_publish(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(publish_post(db, user.id, post_id))


class GbpMediaAiCaptionBody(BaseModel):
    keywords: str = ""
    locality: str = ""
    note: str = ""


class GbpMediaUpdateBody(BaseModel):
    caption: str | None = None
    suggested_filename: str | None = None


class GbpMediaReminderBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    remind_weekday: int = Field(default=1, ge=0, le=6)


@router.get("/media")
def gbp_media_list(
    location_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(list_media(db, user.id, location_key=location_key))


@router.get("/media/audit")
def gbp_media_audit(
    location_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(audit_media(db, user.id, location_key=location_key))


@router.post("/media/upload")
async def gbp_media_upload(
    location_key: str = Form(...),
    media_type: str = Form(...),
    keywords: str = Form(""),
    locality: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        await upload_media(
            db,
            user.id,
            location_key=location_key.strip(),
            media_type=media_type.strip(),
            file=file,
            keywords=keywords.strip(),
            locality=locality.strip(),
        )
    )


@router.patch("/media/{media_id}")
def gbp_media_update(
    media_id: int,
    body: GbpMediaUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        update_media(
            db,
            user.id,
            media_id,
            caption=body.caption,
            suggested_filename=body.suggested_filename,
        )
    )


@router.delete("/media/{media_id}")
def gbp_media_delete(
    media_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(delete_media(db, user.id, media_id))


@router.post("/media/{media_id}/ai-caption")
def gbp_media_ai_caption(
    media_id: int,
    body: GbpMediaAiCaptionBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_active_trial),
) -> dict[str, Any]:
    return _ok(
        _run_google_map_ai(
            db,
            user,
            action="media_ai_caption",
            runner=lambda: ai_caption(
                db,
                user.id,
                media_id,
                input_data=body.model_dump(),
            ),
        )
    )


@router.post("/media/{media_id}/publish")
def gbp_media_publish(
    media_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(publish_media(db, user.id, media_id))


@router.get("/media/reminder")
def gbp_media_reminder_get(
    location_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_reminder(db, user.id, location_key=location_key))


@router.post("/media/reminder")
def gbp_media_reminder_save(
    body: GbpMediaReminderBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        save_reminder(
            db,
            user.id,
            location_key=body.location_key.strip(),
            enabled=body.enabled,
            remind_weekday=body.remind_weekday,
        )
    )


class GbpVerificationSaveBody(BaseModel):
    location_key: str = Field(..., min_length=1, max_length=64)
    checklist: dict[str, bool] = Field(default_factory=dict)
    notes: str = ""
    manual_status: str = ""


@router.get("/verification")
def gbp_verification_get(
    location_key: str = Query(..., min_length=1, max_length=64),
    demo_status: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        get_verification(
            db,
            user.id,
            location_key=location_key,
            demo_status=demo_status.strip() or None,
        )
    )


@router.put("/verification")
def gbp_verification_save(
    body: GbpVerificationSaveBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        save_verification(
            db,
            user.id,
            location_key=body.location_key.strip(),
            checklist=body.checklist,
            notes=body.notes,
            manual_status=body.manual_status.strip() or None,
        )
    )


@router.post("/verification/assets/upload")
async def gbp_verification_upload(
    location_key: str = Form(...),
    asset_type: str = Form("photo"),
    label: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        await upload_asset(
            db,
            user.id,
            location_key=location_key.strip(),
            asset_type=asset_type.strip(),
            file=file,
            label=label.strip(),
        )
    )


@router.delete("/verification/assets/{asset_id}")
def gbp_verification_delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(delete_asset(db, user.id, asset_id))


@router.get("/competitors")
def gbp_competitors_analyze(
    location_key: str = Query(..., min_length=1, max_length=64),
    keyword: str = Query(default="", max_length=200),
    locality: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        analyze_competitors(
            db,
            user.id,
            location_key=location_key.strip(),
            keywords=keyword.strip(),
            locality=locality.strip(),
        )
    )


class GbpReportBrandingBody(BaseModel):
    agency_name: str | None = None
    logo_url: str | None = None
    accent_color: str | None = None
    footer_text: str | None = None
    contact_email: str | None = None


@router.get("/reports")
def gbp_reports(
    location_key: str = Query(..., min_length=1, max_length=64),
    period: str = Query(default="30d", max_length=8),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(
        build_report(
            db,
            user.id,
            location_key=location_key.strip(),
            period=period.strip(),
        )
    )


@router.get("/reports/export")
def gbp_reports_export(
    location_key: str = Query(..., min_length=1, max_length=64),
    period: str = Query(default="30d", max_length=8),
    format: str = Query(default="csv", alias="format", max_length=8),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = build_report(
        db,
        user.id,
        location_key=location_key.strip(),
        period=period.strip(),
    )
    loc_name = (report.get("location") or {}).get("name") or "google-map"
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in loc_name)[:40]
    fmt = (format or "csv").strip().lower()
    if fmt == "pdf":
        try:
            body = export_report_pdf(report)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return StreamingResponse(
            io.BytesIO(body),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="gms-report-{safe_name}.pdf"',
            },
        )
    csv_body = export_report_csv(report)
    return StreamingResponse(
        io.BytesIO(csv_body.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gms-report-{safe_name}.csv"',
        },
    )


@router.get("/reports/branding")
def gbp_reports_branding_get(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_branding(db, user.id))


@router.patch("/reports/branding")
def gbp_reports_branding_patch(
    body: GbpReportBrandingBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(save_branding(db, user.id, body.model_dump(exclude_unset=True)))


class LeadScanBody(BaseModel):
    mode: str = Field(default="keyword", max_length=16)
    keyword: str = Field(default="", max_length=300)
    category: str = Field(default="", max_length=200)
    province: str = Field(default="", max_length=120)
    district: str = Field(default="", max_length=120)
    radius_km: float = Field(default=5.0, ge=0.5, le=50.0)
    limit: int = Field(default=20, ge=20, le=100)


@router.get("/lead-scanner/config")
def gbp_lead_scanner_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_scanner_config(db, user))


@router.post("/lead-scanner/quote")
def gbp_lead_scanner_quote(
    body: LeadScanBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(quote_scan(db, user, body.model_dump()))


@router.post("/lead-scanner/quote-detail")
def gbp_lead_scanner_quote_detail(
    count: int = Query(default=1, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(quote_lead_detail_for_user(db, user.id, count))


@router.post("/lead-scanner/scan")
def gbp_lead_scanner_scan(
    body: LeadScanBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    client_ip = request.client.host if request.client else None
    return _ok(run_scan(db, user, body.model_dump(), client_ip=client_ip))


@router.post("/lead-scanner/scans/{scan_id}/leads/{lead_id}/detail")
def gbp_lead_scanner_lead_detail(
    scan_id: int,
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    client_ip = request.client.host if request.client else None
    return _ok(fetch_lead_detail(db, user, scan_id, lead_id, client_ip=client_ip))


@router.get("/lead-scanner/history")
def gbp_lead_scanner_history(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok({"scans": list_scan_history(db, user.id, limit=limit)})


@router.get("/lead-scanner/scans/{scan_id}")
def gbp_lead_scanner_detail(
    scan_id: int,
    filter: str = Query(default="", alias="filter", max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _ok(get_scan_detail(db, user.id, scan_id, filt=filter.strip() or None))


@router.get("/lead-scanner/scans/{scan_id}/export")
def gbp_lead_scanner_export(
    scan_id: int,
    format: str = Query(default="csv", alias="format", max_length=8),
    filter: str = Query(default="", alias="filter", max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    body, media_type, filename = export_scan(
        db,
        user,
        scan_id,
        fmt=(format or "csv").strip().lower(),
        filt=filter.strip() or None,
    )
    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
