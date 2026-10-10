"""Execute WordPress publish for Content AI drafts (shared by API + scheduler)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.user import User
from app.routers.pages import (
    _build_wp_session,
    _derive_focus_keyword,
    _detect_wp_seo_plugin,
    _ensure_blockquote_inline_style,
    _ensure_wp_tag_ids,
    _normalize_meta_description,
    _normalize_wp_base_url,
    _normalize_wp_slug,
    _rewrite_inline_images_for_wp,
    _trim_seo_title,
    _update_post_seo_meta,
    _update_rankmath_via_plugin_endpoint,
    _upload_featured_media,
    _wp_request,
    _wp_viewable_post_link,
)
from app.services.security_audit_log import log_audit_event


def publish_draft_to_wordpress(
    *,
    db: Session | None,
    user: User | None,
    wp_url: str,
    username: str,
    app_password: str,
    draft_payload: dict[str, Any],
    seo_plugin: str = "auto",
    primary_keyword: str | None = None,
    publish_mode: str = "publish",
    request: Any | None = None,
    record_usage: bool = True,
    usage_idempotency_key: str | None = None,
    wp_site_id: str | None = None,
    source_article_id: str | None = None,
) -> dict[str, Any]:
    """Publish or schedule a draft on WordPress. Returns result dict with post_id, link, status.

    Prefer SEO Helper plugin (HMAC) when a paired connection exists for the site so the
    plugin dashboard can count published posts. Fall back to WP Application Password REST.
    """
    import uuid as uuid_mod

    # --- Prefer SEO Helper plugin when paired ---
    if db is not None and user is not None:
        try:
            from app.services.wordpress_plugin_publish_service import (
                build_plugin_payload_from_draft,
                create_publish_job,
                execute_publish_job,
                get_connection_for_site,
            )

            conn = get_connection_for_site(
                db,
                user_id=int(user.id),
                wp_site_id=wp_site_id,
                site_url=wp_url,
            )
            if conn is not None and str(conn.status or "").lower() == "active":
                draft = draft_payload if isinstance(draft_payload, dict) else {}
                plugin_payload = build_plugin_payload_from_draft(
                    draft,
                    project_id=str(source_article_id or draft.get("project_id") or "").strip() or None,
                    publish_mode=publish_mode,
                    primary_keyword=primary_keyword,
                )
                # Ensure SEO fields travel with plugin payload when present.
                seo_title = str(draft.get("title") or "").strip()
                meta_description = str(draft.get("meta_description") or "").strip()
                focus = str(primary_keyword or draft.get("focus_keyword") or "").strip()
                seo_obj: dict[str, Any] = {}
                if seo_title:
                    seo_obj["title"] = seo_title
                if meta_description:
                    seo_obj["description"] = meta_description
                if focus:
                    seo_obj["focus_keyword"] = focus
                if seo_obj:
                    plugin_payload["seo"] = seo_obj

                req_id = str(usage_idempotency_key or f"wp-plugin-publish:{uuid_mod.uuid4()}")
                src = str(
                    source_article_id
                    or plugin_payload.get("source_article_id")
                    or f"content-ai-{uuid_mod.uuid4().hex[:12]}"
                )
                job = create_publish_job(
                    db,
                    user=user,
                    payload=plugin_payload,
                    connection_id=int(conn.id),
                    wp_site_id=wp_site_id or str(conn.publishing_site_id or "") or None,
                    site_url=wp_url,
                    request_id=req_id,
                    source_article_id=src,
                    enqueue=False,
                )
                if job.status == "blocked":
                    raise HTTPException(
                        status_code=403,
                        detail=job.error_message or job.error_code or "Plugin publish bị chặn.",
                    )
                outcome = execute_publish_job(db, int(job.id))
                if not outcome.get("ok"):
                    detail = (
                        (outcome.get("job") or {}).get("error_message")
                        if isinstance(outcome.get("job"), dict)
                        else None
                    ) or outcome.get("error") or "Đăng bài qua SEO Helper thất bại."
                    raise HTTPException(status_code=502, detail=str(detail)[:400])

                job_dict = outcome.get("job") if isinstance(outcome.get("job"), dict) else {}
                post_id = job_dict.get("wp_post_id") or (job_dict.get("result") or {}).get("post_id")
                link = job_dict.get("wp_post_url") or (job_dict.get("result") or {}).get("permalink") or (
                    (job_dict.get("result") or {}).get("link")
                )
                result_obj = job_dict.get("result") if isinstance(job_dict.get("result"), dict) else {}
                status = str(result_obj.get("status") or publish_mode or "publish").strip().lower() or "publish"
                wp_base_out = _normalize_wp_base_url(wp_url)
                view_link = _wp_viewable_post_link(
                    wp_base=wp_base_out,
                    post_id=post_id,
                    status=status,
                    public_link=link,
                )

                if record_usage:
                    from app.services.content_ai_entitlement import record_content_ai_usage

                    log_audit_event(
                        action="publish.wordpress",
                        user_id=user.id,
                        resource_type="wordpress_plugin",
                        resource_id=str(post_id or ""),
                        detail={"url": wp_url, "status": status, "source": "seo_helper_plugin", "job_id": job.id},
                        request=request,
                    )
                    record_content_ai_usage(
                        db,
                        user,
                        "wp_publish",
                        quantity=1,
                        metadata={"post_id": post_id, "wp_url": wp_url, "source": "seo_helper_plugin"},
                        idempotency_key=(usage_idempotency_key or f"wp-publish-plugin:{post_id}"),
                    )
                    db.commit()

                return {
                    "ok": True,
                    "post_id": post_id,
                    "status": status,
                    "link": view_link,
                    "edit_link": _wp_viewable_post_link(
                        wp_base=wp_base_out,
                        post_id=post_id,
                        status="draft",
                        public_link="",
                    ),
                    "wp_url": wp_base_out,
                    "via": "seo_helper_plugin",
                    "job_id": job.id,
                    "logs": [f"published via seoauto-seo-helper connection_id={conn.id}"],
                }
        except HTTPException:
            raise
        except Exception:
            # Fall through to Application Password path.
            pass

    wp_base = _normalize_wp_base_url(wp_url)
    username = (username or "").strip()
    app_password = (app_password or "").strip()
    if not username or not app_password:
        raise HTTPException(status_code=400, detail="Vui lòng nhập username và app password.")
    draft = draft_payload if isinstance(draft_payload, dict) else {}
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
    last_http = 0
    from app.services.wp_connect import wp_get_json, wp_http_status_note

    for label, strip_spaces in (("strip-spaces", True), ("raw", False)):
        candidate = _build_wp_session(username, app_password, strip_spaces=strip_spaces)
        try:
            resp, working = wp_get_json(
                "/wp-json/wp/v2/users/me",
                url=wp_base,
                headers=dict(candidate.headers),
                auth=candidate.auth,
                timeout=20,
            )
        except requests.RequestException as exc:
            logs.append(f"[auth-check:{label}] {exc.__class__.__name__}")
            continue
        last_http = int(resp.status_code or 0)
        logs.append(f"[auth-check:{label}@{working}] {wp_http_status_note(resp)}")
        if resp.status_code < 400:
            wp_base = working
            session = candidate
            me = resp
            break
    if session is None or me is None:
        code = last_http if last_http in (401, 403, 404) else 401
        hint = {
            401: "HTTP 401 — Application Password sai hoặc tài khoản không được phép REST.",
            403: "HTTP 403 — plugin bảo mật/CDN chặn, hoặc user không đủ quyền.",
            404: "HTTP 404 — REST API không tìm thấy (permalink Plain hoặc URL sai).",
        }.get(code, "Không kết nối được WordPress REST (/users/me).")
        raise HTTPException(
            status_code=401 if code in (401, 403) else (404 if code == 404 else 502),
            detail=f"Xác thực WordPress thất bại. {hint}",
        )

    detected_plugin = _detect_wp_seo_plugin(session=session, wp_base=wp_base, logs=logs)
    seo_plugin_mode = str(seo_plugin or "auto").strip().lower()
    if seo_plugin_mode not in {"auto", "yoast", "rankmath", "none"}:
        seo_plugin_mode = "auto"

    tags_clean: list[str] = []
    tags_raw = draft.get("tags") or []
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
    mode = str(publish_mode or "draft").strip().lower()
    if mode not in {"draft", "publish"}:
        mode = "draft"

    content = _rewrite_inline_images_for_wp(session=session, wp_base=wp_base, content_html=content, logs=logs)
    content = _ensure_blockquote_inline_style(content)

    post_body: dict[str, Any] = {
        "title": title,
        "content": content,
        "slug": slug,
        "status": "draft" if mode == "draft" else "publish",
    }
    if meta_description:
        post_body["excerpt"] = meta_description
    if tag_ids:
        post_body["tags"] = tag_ids
    if cat_ids:
        post_body["categories"] = cat_ids

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
            dt = datetime.fromisoformat(scheduled_at)
            if dt.tzinfo is None:
                from app.services.content_ai_publish_schedule_service import DEFAULT_TZ

                dt = dt.replace(tzinfo=DEFAULT_TZ)
            now = datetime.now(dt.tzinfo)
            if mode == "publish" and dt > (now + timedelta(seconds=30)):
                post_body["status"] = "future"
            post_body["date"] = dt.replace(microsecond=0).isoformat()
            dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
            post_body["date_gmt"] = dt_utc.isoformat()
        except ValueError:
            pass

    created = _wp_request(
        session=session,
        method="POST",
        url=f"{wp_base}/wp-json/wp/v2/posts",
        logs=logs,
        step="create-draft",
        json=post_body,
    )
    if created.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Tạo bài WordPress thất bại: {(created.text or '')[:400]}",
        )
    try:
        data = created.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="WordPress trả dữ liệu không hợp lệ.") from exc

    try:
        created_post_id = int(data.get("id"))
    except (TypeError, ValueError):
        created_post_id = 0
    if created_post_id > 0:
        _wp_request(
            session=session,
            method="POST",
            url=f"{wp_base}/wp-json/wp/v2/posts/{created_post_id}",
            logs=logs,
            step="post-snippet-core-sync",
            json={"title": title, "excerpt": meta_description},
        )
        focus_keyword = _derive_focus_keyword(
            explicit_primary_keyword=str(primary_keyword or ""),
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

    if user and record_usage and db is not None:
        from app.services.content_ai_entitlement import record_content_ai_usage

        log_audit_event(
            action="publish.wordpress",
            user_id=user.id,
            resource_type="wordpress",
            resource_id=str(data.get("id") or ""),
            detail={"url": wp_base, "status": data.get("status"), "source": "bulk_schedule"},
            request=request,
        )
        record_content_ai_usage(
            db,
            user,
            "wp_publish",
            quantity=1,
            metadata={"post_id": data.get("id"), "wp_url": wp_base, "source": "bulk_schedule"},
            idempotency_key=(usage_idempotency_key or f"wp-publish:{data.get('id')}"),
        )
        db.commit()

    return {
        "ok": True,
        "post_id": data.get("id"),
        "status": data.get("status"),
        "link": _wp_viewable_post_link(
            wp_base=wp_base,
            post_id=data.get("id"),
            status=data.get("status"),
            public_link=data.get("link"),
        ),
        "edit_link": _wp_viewable_post_link(
            wp_base=wp_base,
            post_id=data.get("id"),
            status="draft",
            public_link="",
        ),
        "wp_url": wp_base,
        "logs": logs,
    }


def guard_wp_publish_project_duplicate(
    db: Session,
    *,
    user_id: int,
    project_id: str | None,
) -> dict[str, Any] | None:
    """
    Block duplicate WordPress publish for the same Content AI project (double-click / retry).
    Returns idempotent JSON payload when a recent publish exists; otherwise marks publishing.
    """
    pid = str(project_id or "").strip()
    if not pid or int(user_id or 0) <= 0:
        return None

    from app.services.content_ai_publish_schedule_service import _resolve_publish_now_duplicate
    from app.services.content_ai_project_store import (
        get_content_ai_project,
        update_content_ai_project_fields,
    )
    from app.services.idempotency_guard import build_idempotency_key, find_usage_by_key

    dup = _resolve_publish_now_duplicate(db, int(user_id), pid)
    if dup is not None and dup.wp_post_id and int(dup.wp_post_id) > 0:
        return {
            "ok": True,
            "idempotent": True,
            "post_id": int(dup.wp_post_id),
            "status": "published",
            "link": dup.wp_post_url or "",
            "message": "Bài đã được đăng gần đây (idempotent).",
        }

    idem_key = build_idempotency_key("wp-publish-project", user_id, pid)
    prior = find_usage_by_key(db, idem_key)
    if prior is not None:
        import json

        meta: dict[str, Any] = {}
        raw_meta = getattr(prior, "metadata_json", None)
        if raw_meta:
            try:
                meta = json.loads(str(raw_meta))
            except (TypeError, ValueError):
                meta = {}
        post_id = meta.get("post_id")
        if post_id:
            return {
                "ok": True,
                "idempotent": True,
                "post_id": post_id,
                "status": meta.get("status") or "published",
                "link": meta.get("link") or "",
                "message": "Bài đã được đăng (idempotent usage key).",
            }

    proj = get_content_ai_project(pid, user_id=int(user_id))
    if proj is not None:
        wp_status = str(proj.get("wp_publish_status") or "").strip().lower()
        if wp_status == "publishing":
            raise HTTPException(status_code=409, detail="Bài đang được đăng.")

    update_content_ai_project_fields(
        pid,
        {"wp_publish_status": "publishing"},
        user_id=int(user_id),
    )
    return None
