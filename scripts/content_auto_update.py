"""Content Auto Update — WordPress REST + AI SEO refresh."""

from __future__ import annotations

from typing import Any

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.content_auto_update_entitlement import (
    build_cau_quota_snapshot,
    assert_cau_feature,
    record_cau_usage,
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
from app.services.content_update_agent import (
    _fallback_update,
    generate_seo_update,
    validate_preserved_markup,
)
from app.services.seo_core_30_score import (
    build_seo_update_summary,
    compare_seo_scores,
    evaluate_publish_gate,
    factors_failed_items,
    factors_not_passed,
    factors_warning_items,
    score_seo_core_30,
    seo_factor_counts,
)
from app.services.wp_site_connector import (
    connect_site,
    fetch_post_by_url,
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
    post = fetch_post_by_url(site_id=body.site_id, user_id=current_user.id, post_url=safe_url)
    seo_before = score_seo_core_30(
        title=str(post.get("title") or ""),
        meta_description=str(post.get("excerpt") or ""),
        content_html=str(post.get("content") or ""),
        primary_keyword="",
        slug=str(post.get("slug") or ""),
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
            },
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

    return JSONResponse({
        "session": _public_session(session),
        "post": post,
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
    orig = session.get("original") or {}
    slug = str(session.get("slug") or "")
    keyword = body.keyword.strip()
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
        user_id=current_user.id,
        title=old_title,
        content=old_content,
        excerpt=old_excerpt,
        keyword=keyword,
        focus=body.focus,
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
    session = save_session(current_user.id, session)
    record_cau_usage(
        db,
        current_user,
        "content_auto_update_generate",
        metadata={"session_id": body.session_id},
        idempotency_key=f"cau-gen:{body.session_id}:{session.get('updated_at')}",
    )
    return JSONResponse({
        "session": _public_session(session),
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
    })


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


@router.get("/content-ai/auto-update/history")
def api_history(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    return JSONResponse({"items": list_history(current_user.id, limit=limit)})
