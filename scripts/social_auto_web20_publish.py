"""Central Web 2.0 publish flow — manual, schedule, retry."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.services.social_auto_web20_safety import run_web20_safety_checks
from app.services.social_auto_web20_store import (
    _find_account,
    _find_post,
    append_log,
    get_account_secrets,
    update_post,
)
from app.services.web20_oauth_tokens import ensure_fresh_oauth_secrets
from app.services.web20_providers import get_provider

MAX_RETRIES = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_post_status(platform: str, wp_status: str, result: dict[str, Any]) -> str:
    if platform == "google_sites_manual" or result.get("mode") == "manual":
        return "manual"
    if wp_status == "publish" or result.get("status") in {"live", "published", "public"}:
        return "published"
    return "published" if result.get("published_url") else "ready"


def publish_web20_post(
    post_id: str,
    user_id: int,
    *,
    source: str = "manual",
    skip_schedule_check: bool = False,
) -> dict[str, Any]:
    row = _find_post(post_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    status = str(row.get("status") or "draft")
    if status == "publishing":
        raise HTTPException(status_code=409, detail="Bài đang được đăng.")
    if status == "published" and source not in {"retry", "scheduler"}:
        raise HTTPException(status_code=400, detail="Bài đã published.")

    account_id = str(row.get("account_id") or "")
    account = _find_account(account_id, user_id)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản.")
    platform = str(account.get("platform") or "wordpress_2_0")

    if platform == "medium":
        secrets_probe = get_account_secrets(account_id, user_id)
        if not str(secrets_probe.get("integration_token") or "").strip():
            raise HTTPException(status_code=400, detail="Medium cần integration token để publish.")

    if not str(row.get("title") or "").strip() or not str(row.get("html_content") or "").strip():
        raise HTTPException(status_code=400, detail="Thiếu title hoặc nội dung.")

    safety = run_web20_safety_checks(
        user_id,
        title=str(row.get("title") or ""),
        html_content=str(row.get("html_content") or ""),
        account_id=account_id,
        main_site_url=str(row.get("main_site_url") or ""),
        source_content=str(row.get("source_content") or ""),
        exclude_post_id=post_id,
    )
    if not safety.get("can_publish"):
        raise HTTPException(
            status_code=400,
            detail={"message": "Safety Score chưa đạt.", "safety": safety},
        )

    wp_status = str(row.get("wp_status") or "draft")
    if wp_status not in {"publish"} and source in {"manual", "schedule", "scheduler"}:
        wp_status = str(row.get("wp_status") or account.get("default_status") or "draft")
        if wp_status == "publish" and source == "manual":
            pass
        elif wp_status not in {"publish", "queue"}:
            wp_status = "draft"

    update_post(post_id, user_id, {"status": "publishing", "error_message": None})

    secrets = get_account_secrets(account_id, user_id)
    if platform in {"blogger", "tumblr"}:
        secrets = ensure_fresh_oauth_secrets(account, secrets, user_id=user_id)

    provider = get_provider(platform)
    publish_row = {**row, "wp_status": wp_status}

    def _do_publish(secrets_in: dict[str, Any]) -> dict[str, Any]:
        return provider.publish_post(account, secrets_in, publish_row)

    result: dict[str, Any] | None = None
    last_exc: HTTPException | None = None
    try:
        result = _do_publish(secrets)
    except HTTPException as exc:
        last_exc = exc
        if platform in {"blogger", "tumblr"}:
            try:
                secrets = ensure_fresh_oauth_secrets(account, secrets, user_id=user_id, force_refresh=True)
                result = _do_publish(secrets)
                last_exc = None
            except HTTPException as exc2:
                last_exc = exc2

    if last_exc is not None or result is None:
        exc = last_exc or HTTPException(status_code=502, detail="Publish thất bại.")
        retry_count = int(row.get("retry_count") or 0) + 1
        err = str(exc.detail)[:500]
        patch: dict[str, Any] = {
            "error_message": err,
            "retry_count": retry_count,
            "last_error_at": _now_iso(),
        }
        if retry_count >= MAX_RETRIES:
            patch["status"] = "failed"
        else:
            patch["status"] = "retrying"
        update_post(post_id, user_id, patch)
        append_log(
            user_id,
            level="error",
            code="publish_failed",
            message=f"[{source}] {err}",
            account_id=account_id,
            post_id=post_id,
            meta={"retry_count": retry_count, "platform": platform},
        )
        raise exc

    post_status = _resolve_post_status(platform, wp_status, result)
    patch = {
        "status": post_status,
        "external_id": result.get("external_id"),
        "published_url": result.get("published_url"),
        "error_message": None,
        "published_at": _now_iso(),
        "safety_score": safety["score"],
        "safety_passed": True,
        "retry_count": int(row.get("retry_count") or 0),
    }
    if result.get("external_id") and platform == "wordpress_2_0":
        patch["wp_post_id"] = result.get("external_id")
    if result.get("manual_package"):
        patch["manual_package"] = result["manual_package"]
    item = update_post(post_id, user_id, patch)
    log_msg = f"[{source}] Web 2.0 {platform} ({result.get('status') or wp_status})"
    if result.get("published_url"):
        log_msg += f": {result.get('published_url')}"
    append_log(
        user_id,
        code="published" if post_status not in {"manual"} else "manual_ready",
        message=log_msg,
        account_id=account_id,
        post_id=post_id,
        meta={"platform": platform, "mode": result.get("mode")},
    )
    return {"item": item, "result": result, "safety": safety}
