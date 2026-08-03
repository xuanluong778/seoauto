"""API quản lý khóa LLM/API — đăng ký trong main.py để luôn có route /api/settings/api-keys."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db import get_db
from app.models.user import User
from app.services.auth import get_current_user
from app.services.api_key_verify import verify_api_key
from app.services.rbac import normalize_role, require_write_user
from app.services.security_audit_log import log_audit_event
from app.services.user_api_access import (
    api_access_enabled_for,
    assert_user_may_manage_api_keys,
    describe_user_llm_source,
    may_manage_custom_api_keys,
    use_admin_api_pool_for,
)
from app.services.user_trial_service import trial_status_snapshot
from sqlalchemy.orm import Session

from app.services.api_keys_store import (
    PROVIDERS as _SETTINGS_API_PROVIDERS,
    create_key as _settings_create_key,
    delete_key as _settings_delete_key,
    get_stats as _settings_get_stats,
    list_keys as _settings_list_keys,
    update_key as _settings_update_key,
    get_key as _settings_get_key,
)
from app.services.ai_provider_prefs import read_prefs as _ai_read_prefs, write_prefs as _ai_write_prefs
from app.services.ai_provider_status import build_provider_snapshot as _ai_build_snapshot
from app.services.publishing_sites_store import (
    PLATFORMS as _PUB_PLATFORMS,
    list_sites as _pub_list,
    get_counts as _pub_counts,
    get_site as _pub_get,
    create_site as _pub_create,
    update_site as _pub_update,
    delete_site as _pub_delete,
)
from app.services.ai_knowledge_store import (
    TONES as _KB_TONES,
    clone_base as _kb_clone,
    create_base as _kb_create,
    delete_base as _kb_delete,
    get_base as _kb_get,
    list_bases as _kb_list,
    update_base as _kb_update,
)
from app.services.ai_knowledge_docs import (
    get_kb_stats as _kb_stats,
    import_bytes as _kb_import_bytes,
    import_text as _kb_import_text,
    get_document as _kb_get_document,
    list_documents as _kb_list_documents,
    reindex_kb as _kb_reindex,
    search_kb as _kb_search,
)

import base64
import requests
from urllib.parse import urlparse

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _verify_and_activate_trial(
    db: Session,
    *,
    user_id: int,
    provider: str,
    plain_key: str,
) -> dict:
    ok, verify_msg = verify_api_key(provider, plain_key)
    if not ok:
        return {
            "verified": False,
            "verify_message": verify_msg,
            "trial_activation": None,
            "trial": trial_status_snapshot(db, user_id),
        }
    return {
        "verified": True,
        "verify_message": verify_msg,
        "trial_activation": None,
        "trial": trial_status_snapshot(db, user_id),
    }


@router.get("/trial")
def settings_trial_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    return JSONResponse(
        {"trial": trial_status_snapshot(db, current_user.id, role=normalize_role(current_user.role))}
    )


class SettingsApiKeyVerifyBody(BaseModel):
    provider: str
    api_key: str


class SettingsApiKeyCreate(BaseModel):
    name: str
    provider: str
    api_key: str
    daily_limit: int | None = None
    priority: int | None = None
    enabled: bool | None = True


class SettingsApiKeyPatch(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    daily_limit: int | None = None
    priority: int | None = None
    enabled: bool | None = None
    status: str | None = None


class AiProviderPrefsPatch(BaseModel):
    pipeline_multi_model: bool | None = None


@router.get("/ai-provider")
def settings_ai_provider_get(current_user: User = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse(_ai_build_snapshot(user_id=current_user.id))


@router.patch("/ai-provider")
def settings_ai_provider_patch(
    payload: AiProviderPrefsPatch,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    cur = _ai_read_prefs(user_id=current_user.id)
    if payload.pipeline_multi_model is not None:
        cur["pipeline_multi_model"] = payload.pipeline_multi_model
    _ai_write_prefs(cur, user_id=current_user.id)
    return JSONResponse(_ai_build_snapshot(user_id=current_user.id))


class SystemSettingsPatch(BaseModel):
    theme: str | None = None
    language: str | None = None
    launch_on_startup: bool | None = None
    batch_size: int | None = None
    max_retries: int | None = None
    stuck_timeout_minutes: int | None = None


@router.get("/system")
def settings_system_get(current_user: User = Depends(get_current_user)) -> JSONResponse:
    from app.services.user_system_settings import read_settings

    return JSONResponse({"settings": read_settings(user_id=current_user.id)})


@router.patch("/system")
def settings_system_patch(
    payload: SystemSettingsPatch,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.user_system_settings import write_settings

    patch = payload.model_dump(exclude_unset=True)
    settings = write_settings(patch, user_id=current_user.id)
    return JSONResponse({"settings": settings})


@router.get("/api-keys")
def settings_api_keys_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    return JSONResponse(
        {
            "providers": _SETTINGS_API_PROVIDERS,
            "items": _settings_list_keys(user_id=current_user.id),
            "stats": _settings_get_stats(user_id=current_user.id),
            "trial": trial_status_snapshot(db, current_user.id, role=normalize_role(current_user.role)),
            "api_access": {
                "enabled": api_access_enabled_for(current_user),
                "use_admin_pool": use_admin_api_pool_for(current_user),
                "can_manage_api_keys": may_manage_custom_api_keys(db, current_user),
                "llm_source": describe_user_llm_source(db, current_user),
            },
        }
    )


@router.post("/api-keys/verify")
def settings_api_keys_verify(
    payload: SettingsApiKeyVerifyBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    check = _verify_and_activate_trial(
        db,
        user_id=current_user.id,
        provider=payload.provider,
        plain_key=payload.api_key,
    )
    return JSONResponse(
        {
            "ok": bool(check["verified"]),
            "message": check["verify_message"],
            "trial": check["trial"],
            "trial_activation": check.get("trial_activation"),
        },
        status_code=200 if check["verified"] else 400,
    )


@router.post("/api-keys")
def settings_api_keys_create(
    request: Request,
    payload: SettingsApiKeyCreate,
    current_user: User = Depends(require_write_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    check = _verify_and_activate_trial(
        db,
        user_id=current_user.id,
        provider=payload.provider,
        plain_key=payload.api_key,
    )
    if not check["verified"]:
        return JSONResponse({"detail": check["verify_message"], "trial": check["trial"]}, status_code=400)
    try:
        item = _settings_create_key(payload.model_dump(), user_id=current_user.id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    log_audit_event(
        action="api_key.create",
        user_id=current_user.id,
        resource_type="api_key",
        resource_id=str(item.get("id") or ""),
        detail={"provider": item.get("provider"), "name": item.get("name")},
        request=request,
    )
    return JSONResponse(
        {
            "item": item,
            "stats": _settings_get_stats(user_id=current_user.id),
            "trial": check["trial"],
            "trial_activation": check["trial_activation"],
            "verify_message": check["verify_message"],
        }
    )


@router.get("/api-keys/{key_id}")
def settings_api_keys_get(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    item = _settings_get_key(key_id, user_id=current_user.id, reveal_key=True)
    if not item:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse({"item": item})


@router.patch("/api-keys/{key_id}")
def settings_api_keys_update(
    request: Request,
    key_id: str,
    payload: SettingsApiKeyPatch,
    current_user: User = Depends(require_write_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    patch = payload.model_dump(exclude_unset=True)
    trial_extra: dict = {}
    if patch.get("api_key"):
        existing = _settings_get_key(key_id, user_id=current_user.id, reveal_key=False)
        provider = (patch.get("provider") or (existing or {}).get("provider") or "openai")
        check = _verify_and_activate_trial(
            db,
            user_id=current_user.id,
            provider=str(provider),
            plain_key=str(patch["api_key"]),
        )
        if not check["verified"]:
            return JSONResponse({"detail": check["verify_message"], "trial": check["trial"]}, status_code=400)
        trial_extra = {
            "trial": check["trial"],
            "trial_activation": check["trial_activation"],
            "verify_message": check["verify_message"],
        }
    item = _settings_update_key(key_id, patch, user_id=current_user.id)
    if not item:
        return JSONResponse({"detail": "not found"}, status_code=404)
    log_audit_event(
        action="api_key.update",
        user_id=current_user.id,
        resource_type="api_key",
        resource_id=key_id,
        detail={"fields": list(patch.keys())},
        request=request,
    )
    return JSONResponse({"item": item, "stats": _settings_get_stats(user_id=current_user.id), **trial_extra})


@router.delete("/api-keys/{key_id}")
def settings_api_keys_delete(
    request: Request,
    key_id: str,
    current_user: User = Depends(require_write_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    ok = _settings_delete_key(key_id, user_id=current_user.id)
    if not ok:
        return JSONResponse({"detail": "not found"}, status_code=404)
    log_audit_event(
        action="api_key.delete",
        user_id=current_user.id,
        resource_type="api_key",
        resource_id=key_id,
        request=request,
    )
    return JSONResponse({"ok": True, "stats": _settings_get_stats(user_id=current_user.id)})


@router.post("/api-keys/{key_id}/test")
def settings_api_keys_test(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    assert_user_may_manage_api_keys(db, current_user)
    item = _settings_get_key(key_id, user_id=current_user.id, reveal_key=True)
    if not item:
        return JSONResponse({"detail": "not found"}, status_code=404)
    plain = str(item.get("api_key") or "").strip()
    if not plain:
        return JSONResponse({"ok": False, "message": "Khóa rỗng — không thể test.", "item": item})
    check = _verify_and_activate_trial(
        db,
        user_id=current_user.id,
        provider=str(item.get("provider") or "openai"),
        plain_key=plain,
    )
    return JSONResponse(
        {
            "ok": bool(check["verified"]),
            "message": check["verify_message"],
            "item": item,
            "trial": check["trial"],
            "trial_activation": check.get("trial_activation"),
        }
    )


# ===================== Publishing sites =====================


class PublishingSiteCreate(BaseModel):
    platform: str | None = "wordpress"
    name: str
    url: str
    username: str | None = ""
    app_password: str | None = ""
    default_status: str | None = "draft"


class PublishingSitePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    username: str | None = None
    app_password: str | None = None
    default_status: str | None = None


def _pub_summary(*, user_id: int) -> dict:
    counts = _pub_counts(user_id=user_id)
    return {
        "platforms": sorted(list(_PUB_PLATFORMS)),
        "counts": counts,
        "items": {platform: _pub_list(user_id=user_id, platform=platform) for platform in _PUB_PLATFORMS},
    }


def _sync_pub_plugin_flags_from_helper(db: Session, user: User) -> None:
    """Align publishing-site badges with active SEO Helper plugin connections."""
    try:
        from app.models.wordpress_plugin import WordpressConnection
        from app.services.publishing_sites_store import mark_seo_helper_installed
        from app.services.wordpress_pairing_service import resolve_organization_id
        from app.services.wordpress_plugin_security import normalize_domain

        org_id = resolve_organization_id(user, None)
        rows = (
            db.query(WordpressConnection)
            .filter(
                WordpressConnection.organization_id == int(org_id),
                WordpressConnection.user_id == int(user.id),
                WordpressConnection.status.in_(("active", "pending")),
            )
            .all()
        )
        domains: set[str] = set()
        urls: list[str] = []
        for row in rows:
            dom = str(getattr(row, "domain_normalized", "") or "").strip().lower()
            if not dom:
                dom = normalize_domain(str(getattr(row, "site_url", "") or ""))
            if dom:
                domains.add(dom)
            if getattr(row, "site_url", None):
                urls.append(str(row.site_url))
        if domains or urls:
            mark_seo_helper_installed(user_id=int(user.id), domains=domains, site_urls=urls)
    except Exception:
        # Listing must not fail if helper tables are unavailable.
        return


@router.get("/publishing-sites")
def settings_publishing_sites_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    _sync_pub_plugin_flags_from_helper(db, current_user)
    return JSONResponse(_pub_summary(user_id=current_user.id))


@router.get("/publishing-sites/{site_id}")
def settings_publishing_sites_get(
    site_id: str,
    reveal_password: bool = False,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Chi tiết một site — reveal_password=true trả app_password thật (dùng form đăng bài Content AI)."""
    site = _pub_get(site_id, user_id=current_user.id, reveal_password=bool(reveal_password))
    if not site:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse({"item": site})


@router.post("/publishing-sites")
def settings_publishing_sites_create(
    payload: PublishingSiteCreate,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    try:
        item = _pub_create(payload.model_dump(), user_id=current_user.id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"item": item, "summary": _pub_summary(user_id=current_user.id)})


@router.patch("/publishing-sites/{site_id}")
def settings_publishing_sites_update(
    site_id: str,
    payload: PublishingSitePatch,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    item = _pub_update(site_id, payload.model_dump(exclude_unset=True), user_id=current_user.id)
    if not item:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse({"item": item, "summary": _pub_summary(user_id=current_user.id)})


@router.delete("/publishing-sites/{site_id}")
def settings_publishing_sites_delete(
    site_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    ok = _pub_delete(site_id, user_id=current_user.id)
    if not ok:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "summary": _pub_summary(user_id=current_user.id)})


def _normalize_wp_base(url: str) -> str:
    from app.services.wp_connect import normalize_wp_base_url

    return normalize_wp_base_url(url)


def _normalize_app_password(value: str) -> str:
    return str(value or "").strip().replace(" ", "")


def _wp_auth_headers(username: str, app_password: str, *, normalize_password: bool = True) -> dict[str, str]:
    pwd = _normalize_app_password(app_password) if normalize_password else str(app_password or "")
    cred = f"{username.strip()}:{pwd}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(cred).decode("ascii"),
        "Accept": "application/json",
    }


def _check_wp_site(site: dict) -> dict:
    url = _normalize_wp_base(site.get("url") or "")
    username = str(site.get("username") or "").strip()
    app_password_raw = str(site.get("app_password") or "").strip()
    if not url:
        return {"verified": False, "plugin_installed": False, "message": "Thiếu URL website."}
    if not username or not app_password_raw:
        return {"verified": False, "plugin_installed": False, "message": "Thiếu username hoặc app password."}
    from app.services.wp_connect import wp_get_json
    from urllib.parse import urlparse

    last_fail: dict | None = None
    headers: dict[str, str] | None = None
    working_url = url
    for label, normalize_pwd in (("strip-spaces", True), ("raw", False)):
        attempt_headers = _wp_auth_headers(username, app_password_raw, normalize_password=normalize_pwd)
        user = username.strip()
        pwd = _normalize_app_password(app_password_raw) if normalize_pwd else str(app_password_raw or "")
        try:
            me, working_url = wp_get_json(
                "/wp-json/wp/v2/users/me",
                url=url,
                headers=attempt_headers,
                auth=(user, pwd),
                timeout=20,
            )
        except requests.RequestException as exc:
            host = urlparse(url).netloc or url
            return {
                "verified": False,
                "plugin_installed": False,
                "message": str(exc) if str(exc) else f"Không kết nối được tới WordPress ({host}).",
            }
        if me.status_code < 400:
            headers = attempt_headers
            url = working_url
            break
        snippet = (me.text or "")[:160]
        hint = ""
        if me.status_code == 404:
            hint = " Không tìm thấy REST API — kiểm tra permalink (không dùng Plain) và URL đúng (có https)."
        elif me.status_code in (401, 403):
            hint = " Dùng Application Password (không phải mật khẩu đăng nhập thường)."
        last_fail = {
            "verified": False,
            "plugin_installed": False,
            "message": f"WP /users/me HTTP {me.status_code}.{hint} {snippet}".strip(),
        }
    if headers is None:
        return last_fail or {
            "verified": False,
            "plugin_installed": False,
            "message": "Xác thực WordPress thất bại.",
        }
    plugin_installed = False
    plugin_probe_ok = False

    def _name_looks_like_helper(value: str) -> bool:
        low = (value or "").lower()
        return (
            "seoauto" in low
            or "digiseo" in low
            or "gen-seo" in low
            or "gen_seo" in low
            or "seo helper" in low
        )

    # 1) Preferred: WP plugins list (requires manage_plugins capability).
    try:
        pl, _ = wp_get_json(
            "/wp-json/wp/v2/plugins",
            url=url,
            headers=headers,
            auth=(user, pwd),
            timeout=15,
            params={"per_page": 100},
        )
        if pl.status_code < 400:
            plugin_probe_ok = True
            data = pl.json() if "json" in (pl.headers.get("content-type") or "").lower() else []
            if isinstance(data, list):
                for item in data:
                    blob = " ".join(
                        [
                            str((item or {}).get("plugin") or ""),
                            str((item or {}).get("name") or ""),
                            str((item or {}).get("textdomain") or ""),
                        ]
                    )
                    if _name_looks_like_helper(blob):
                        plugin_installed = True
                        break
    except Exception:
        plugin_probe_ok = False

    # 2) Fallback: REST namespace registered by SEOAuto SEO Helper (works even when
    # /wp/v2/plugins is forbidden for Application Password users).
    if not plugin_installed:
        try:
            idx, _ = wp_get_json(
                "/wp-json/",
                url=url,
                headers=headers,
                auth=(user, pwd),
                timeout=12,
            )
            if idx.status_code < 400:
                payload = idx.json() if "json" in (idx.headers.get("content-type") or "").lower() else {}
                namespaces = payload.get("namespaces") or []
                if isinstance(namespaces, list):
                    for ns in namespaces:
                        nslow = str(ns or "").lower()
                        if nslow.startswith("seoauto/") or nslow.startswith("digiseo/"):
                            plugin_installed = True
                            break
                if not plugin_installed:
                    routes = payload.get("routes") or {}
                    if isinstance(routes, dict):
                        for route in routes:
                            rlow = str(route or "").lower()
                            if "/seoauto/v1" in rlow or "/digiseo/v1" in rlow:
                                plugin_installed = True
                                break
        except Exception:
            pass

    if plugin_installed:
        message = "Kết nối WordPress thành công. Đã phát hiện SEOAuto SEO Helper."
    elif plugin_probe_ok:
        message = (
            "Kết nối WordPress thành công, nhưng chưa thấy plugin SEOAuto SEO Helper "
            "trên website. Hãy Upload plugin seoauto-seo-helper.zip → Activate, rồi bấm Kiểm tra lại."
        )
    else:
        message = (
            "Kết nối WordPress thành công, nhưng không đọc được danh sách plugin "
            "(thiếu quyền manage_plugins). Hãy dùng tài khoản Admin hoặc kiểm tra REST /seoauto/v1."
        )
    return {
        "verified": True,
        "plugin_installed": plugin_installed,
        "message": message,
    }


class WordPressConnectionBody(BaseModel):
    url: str
    username: str
    app_password: str


class WordPressCategoriesBody(BaseModel):
    """Categories can be loaded by saved site id or explicit WP credentials."""

    wp_site_id: str | None = None
    url: str | None = None
    username: str | None = None
    app_password: str | None = None


def _resolve_wp_category_credentials(
    *,
    user_id: int,
    wp_site_id: str | None = None,
    url: str | None = None,
    username: str | None = None,
    app_password: str | None = None,
) -> tuple[str, str, str]:
    sid = str(wp_site_id or "").strip()
    if sid:
        site = _pub_get(sid, user_id=user_id, reveal_password=True)
        if not site:
            raise HTTPException(status_code=404, detail="Không tìm thấy website đã lưu.")
        if str(site.get("platform") or "").lower() != "wordpress":
            raise HTTPException(status_code=400, detail="Website không phải WordPress.")
        site_url = str(site.get("url") or "").strip()
        site_user = str(site.get("username") or "").strip()
        site_pwd = str(site.get("app_password") or "").strip()
        if not site_url or not site_user or not site_pwd:
            raise HTTPException(
                status_code=400,
                detail="Website thiếu URL / username / Application password.",
            )
        return site_url, site_user, site_pwd
    site_url = str(url or "").strip()
    site_user = str(username or "").strip()
    site_pwd = str(app_password or "").strip()
    if not site_url or not site_user or not site_pwd:
        raise HTTPException(
            status_code=400,
            detail="Cần wp_site_id hoặc đủ url + username + app_password.",
        )
    return site_url, site_user, site_pwd


class HaravanConnectionBody(BaseModel):
    store_url: str | None = ""
    private_token: str


class ShopifyConnectionBody(BaseModel):
    store_url: str
    client_id: str
    client_secret: str = ""
    api_version: str = "2025-01"


class WebcakeConnectionBody(BaseModel):
    site_url: str = ""
    access_token: str = ""
    refresh_token: str = ""


def _haravan_bearer_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + str(token or "").strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _check_haravan_site(site: dict) -> dict:
    token = str(site.get("app_password") or "").strip()
    if not token:
        return {"verified": False, "plugin_installed": False, "message": "Thiếu Private Token."}
    try:
        r = requests.get(
            "https://apis.haravan.com/web/blogs.json",
            headers=_haravan_bearer_headers(token),
            params={"limit": 1},
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"verified": False, "plugin_installed": False, "message": f"Không gọi được Haravan API: {exc}"}
    if r.status_code >= 400:
        snippet = (r.text or "")[:220]
        return {
            "verified": False,
            "plugin_installed": False,
            "message": f"Haravan blogs API HTTP {r.status_code}. {snippet}",
        }
    return {
        "verified": True,
        "plugin_installed": False,
        "message": "Kết nối Haravan thành công (đã gọi blogs API).",
    }


def _haravan_sync_blogs_count(token: str) -> tuple[int | None, str]:
    tok = str(token or "").strip()
    if not tok:
        return None, "Thiếu Private Token."
    try:
        r = requests.get(
            "https://apis.haravan.com/web/blogs/count.json",
            headers=_haravan_bearer_headers(tok),
            timeout=20,
        )
    except requests.RequestException as exc:
        return None, f"Không gọi được Haravan API: {exc}"
    if r.status_code >= 400:
        return None, f"Haravan count API HTTP {r.status_code}. {(r.text or '')[:180]}"
    try:
        data = r.json()
    except ValueError:
        return None, "Phản hồi không phải JSON."
    if isinstance(data, dict) and "count" in data:
        return int(data["count"]), f"Đã đồng bộ: {int(data['count'])} blog."
    return None, "Không đọc được số blog từ API."


def _wp_posts_count(url: str, username: str, app_password: str) -> tuple[int | None, str]:
    base = _normalize_wp_base(url)
    if not base:
        return None, "Thiếu URL website."
    app_password_raw = str(app_password or "").strip()
    r: requests.Response | None = None
    for normalize_pwd in (True, False):
        headers = _wp_auth_headers(username, app_password_raw, normalize_password=normalize_pwd)
        try:
            r = requests.get(
                f"{base}/wp-json/wp/v2/posts",
                headers=headers,
                params={"per_page": 1, "status": "any"},
                timeout=20,
            )
        except requests.RequestException as exc:
            return None, f"Không gọi được WordPress REST API: {exc}"
        if r.status_code < 400:
            break
    if r is None or r.status_code >= 400:
        return None, f"WP posts API HTTP {r.status_code if r else '?'}. {(r.text or '')[:180] if r else ''}"
    try:
        total = int(r.headers.get("X-WP-Total") or 0)
    except (TypeError, ValueError):
        total = None
    if total is None:
        return None, "Không đọc được số bài từ WordPress (thiếu header X-WP-Total)."
    return total, f"Đã đồng bộ: {total} bài viết trên WordPress."


@router.post("/publishing-sites/wordpress/test-connection")
def settings_publishing_wordpress_test(
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


@router.post("/publishing-sites/wordpress/categories")
def settings_publishing_wordpress_categories(
    payload: WordPressCategoriesBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Danh mục WP — route dự phòng cho Content AI (khi /content-ai/... chưa có trên server cũ)."""
    from app.services.wp_categories import fetch_wordpress_categories

    url, username, app_password = _resolve_wp_category_credentials(
        user_id=int(current_user.id),
        wp_site_id=payload.wp_site_id,
        url=payload.url,
        username=payload.username,
        app_password=payload.app_password,
    )
    result = fetch_wordpress_categories(
        url=url,
        username=username,
        app_password=app_password,
    )
    return JSONResponse(content=result)


@router.post("/publishing-sites/wordpress/sync-posts")
def settings_publishing_wordpress_sync_preview(
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


@router.post("/publishing-sites/haravan/test-connection")
def settings_publishing_haravan_test(
    payload: HaravanConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    result = _check_haravan_site({"app_password": payload.private_token})
    return JSONResponse({"ok": result["verified"], "message": result["message"]})


@router.post("/publishing-sites/haravan/sync-blogs")
def settings_publishing_haravan_sync_preview(
    payload: HaravanConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    count, msg = _haravan_sync_blogs_count(payload.private_token)
    return JSONResponse({"ok": count is not None, "count": count, "message": msg})


@router.post("/publishing-sites/shopify/test-connection")
def settings_publishing_shopify_test(
    payload: ShopifyConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.shopify_connect import normalize_shop_url, test_shopify_connection

    result = test_shopify_connection(
        shop_url=normalize_shop_url(payload.store_url),
        client_id=str(payload.client_id or "").strip(),
        client_secret=str(payload.client_secret or "").strip(),
        api_version=str(payload.api_version or "2025-01"),
    )
    return JSONResponse(
        {
            "ok": result.get("verified"),
            "message": result.get("message"),
            "api_version": result.get("api_version"),
        }
    )


@router.post("/publishing-sites/shopify/sync-blogs")
def settings_publishing_shopify_sync(
    payload: ShopifyConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.shopify_connect import (
        normalize_shop_url,
        pack_shopify_secrets,
        sync_shopify_blogs,
    )

    cid = str(payload.client_id or "").strip()
    secret = str(payload.client_secret or "").strip()
    if not secret:
        return JSONResponse({"ok": False, "count": None, "message": "Thiếu Client Secret."}, status_code=400)
    blob = pack_shopify_secrets(
        client_secret=secret,
        api_version=str(payload.api_version or "2025-01"),
    )
    count, msg = sync_shopify_blogs(
        shop_url=normalize_shop_url(payload.store_url),
        client_id=cid,
        secrets_blob=blob,
    )
    return JSONResponse({"ok": count is not None, "count": count, "message": msg})


@router.post("/publishing-sites/webcake/test-connection")
def settings_publishing_webcake_test(
    payload: WebcakeConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.webcake_connect import normalize_site_url, test_webcake_connection

    result = test_webcake_connection(
        site_url=normalize_site_url(payload.site_url),
        access_token=str(payload.access_token or "").strip(),
        refresh_token=str(payload.refresh_token or "").strip(),
    )
    return JSONResponse({"ok": result.get("verified"), "message": result.get("message")})


@router.post("/publishing-sites/webcake/sync-categories")
def settings_publishing_webcake_sync(
    payload: WebcakeConnectionBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    from app.services.webcake_connect import (
        normalize_site_url,
        pack_webcake_secrets,
        sync_webcake_categories,
    )

    access = str(payload.access_token or "").strip()
    refresh = str(payload.refresh_token or "").strip()
    if not access or not refresh:
        return JSONResponse(
            {"ok": False, "count": None, "message": "Thiếu Access Token hoặc Refresh Token."},
            status_code=400,
        )
    blob = pack_webcake_secrets(access_token=access, refresh_token=refresh)
    count, msg = sync_webcake_categories(secrets_blob=blob)
    return JSONResponse({"ok": count is not None, "count": count, "message": msg})


@router.post("/publishing-sites/{site_id}/verify")
def settings_publishing_sites_verify(
    site_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    uid = current_user.id
    site = _pub_get(site_id, user_id=uid, reveal_password=True)
    if not site:
        return JSONResponse({"detail": "not found"}, status_code=404)
    if site["platform"] == "haravan":
        result = _check_haravan_site(site)
        from datetime import datetime, timezone

        item = _pub_update(
            site_id,
            {
                "verified": result["verified"],
                "plugin_installed": False,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                "last_message": result["message"],
            },
            user_id=uid,
        )
        return JSONResponse({"item": item, "summary": _pub_summary(user_id=uid), "result": result})
    if site["platform"] == "shopify":
        from datetime import datetime, timezone

        from app.services.shopify_connect import test_shopify_connection

        result = test_shopify_connection(
            shop_url=site.get("url") or "",
            client_id=str(site.get("username") or ""),
            client_secret="",
            api_version="2025-01",
            secrets_blob=str(site.get("app_password") or ""),
        )
        patch: dict[str, Any] = {
            "verified": result.get("verified"),
            "plugin_installed": False,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_message": result.get("message"),
        }
        if result.get("secrets_blob"):
            patch["app_password"] = result["secrets_blob"]
        item = _pub_update(site_id, patch, user_id=uid)
        return JSONResponse({"item": item, "summary": _pub_summary(user_id=uid), "result": result})
    if site["platform"] == "webcake":
        from datetime import datetime, timezone

        from app.services.webcake_connect import test_webcake_connection

        result = test_webcake_connection(
            site_url=str(site.get("url") or ""),
            secrets_blob=str(site.get("app_password") or ""),
        )
        patch = {
            "verified": result.get("verified"),
            "plugin_installed": False,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_message": result.get("message"),
        }
        if result.get("secrets_blob"):
            patch["app_password"] = result["secrets_blob"]
        item = _pub_update(site_id, patch, user_id=uid)
        return JSONResponse({"item": item, "summary": _pub_summary(user_id=uid), "result": result})
    if site["platform"] != "wordpress":
        item = _pub_update(
            site_id,
            {
                "verified": True,
                "plugin_installed": False,
                "last_checked_at": _pub_get(site_id, user_id=uid)["updated_at"],
                "last_message": "Nền tảng này chưa hỗ trợ kiểm tra tự động.",
            },
            user_id=uid,
        )
        return JSONResponse({"item": item, "summary": _pub_summary(user_id=uid)})
    result = _check_wp_site(site)
    from datetime import datetime, timezone

    item = _pub_update(
        site_id,
        {
            "verified": result["verified"],
            "plugin_installed": result["plugin_installed"],
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
            "last_message": result["message"],
        },
        user_id=uid,
    )
    return JSONResponse({"item": item, "summary": _pub_summary(user_id=uid), "result": result})


# ===================== AI Knowledge Base =====================


class AiKnowledgeBaseCreate(BaseModel):
    name: str
    brand_name: str | None = ""
    website_url: str | None = ""
    tone: str | None = "professional"
    language: str | None = "vi"
    products_services: str | None = ""
    target_audience: str | None = ""
    key_facts: str | None = ""
    avoid_topics: str | None = ""
    custom_instructions: str | None = ""
    enabled: bool | None = True
    is_default: bool | None = False
    scope: str | None = "user"
    inherit_mode: str | None = "all"
    inherit_websites: list[str] | str | None = None
    industry: str | None = ""
    tags: list[str] | str | None = None
    project_id: str | None = ""


class AiKnowledgeBasePatch(BaseModel):
    name: str | None = None
    brand_name: str | None = None
    website_url: str | None = None
    tone: str | None = None
    language: str | None = None
    products_services: str | None = None
    target_audience: str | None = None
    key_facts: str | None = None
    avoid_topics: str | None = None
    custom_instructions: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    inherit_mode: str | None = None
    inherit_websites: list[str] | str | None = None
    industry: str | None = None
    tags: list[str] | str | None = None
    project_id: str | None = None


class AiKnowledgeCloneBody(BaseModel):
    name: str | None = None


class AiKnowledgeSearchBody(BaseModel):
    query: str
    limit: int | None = 8


class AiKnowledgeImportTextBody(BaseModel):
    title: str | None = ""
    text: str


def _kb_items_with_stats(*, user_id: int, role: str = "user") -> list[dict]:
    items = _kb_list(user_id=user_id, role=role)
    for it in items:
        it["stats"] = _kb_stats(str(it.get("id") or ""))
    return items


@router.get("/ai-knowledge-bases")
def settings_ai_knowledge_bases_list(current_user: User = Depends(get_current_user)) -> JSONResponse:
    role = normalize_role(current_user.role)
    return JSONResponse({"tones": _KB_TONES, "items": _kb_items_with_stats(user_id=current_user.id, role=role)})


@router.post("/ai-knowledge-bases")
def settings_ai_knowledge_bases_create(
    request: Request,
    payload: AiKnowledgeBaseCreate,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    try:
        item = _kb_create(
            payload.model_dump(),
            user_id=current_user.id,
            role=normalize_role(current_user.role),
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    item["stats"] = _kb_stats(str(item.get("id") or ""))
    log_audit_event(
        action="knowledge_base.create",
        user_id=current_user.id,
        resource_type="knowledge_base",
        resource_id=str(item.get("id") or ""),
        detail={"name": item.get("name"), "scope": item.get("scope")},
        request=request,
    )
    return JSONResponse(
        {"item": item, "items": _kb_items_with_stats(user_id=current_user.id, role=normalize_role(current_user.role))}
    )


@router.get("/ai-knowledge-bases/{kb_id}")
def settings_ai_knowledge_bases_get(
    kb_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    item = _kb_get(kb_id, user_id=current_user.id, role=role)
    if not item:
        return JSONResponse({"detail": "not found"}, status_code=404)
    item["stats"] = _kb_stats(kb_id)
    item["documents"] = _kb_list_documents(kb_id)
    return JSONResponse({"item": item})


def _kb_require_writable(kb_id: str, *, user_id: int, role: str) -> dict[str, Any] | None:
    from app.services.ai_knowledge_store import _read_all, _writable_or_raise

    kid = str(kb_id or "").strip()
    for raw in _read_all():
        if str(raw.get("id")) == kid:
            try:
                _writable_or_raise(raw, user_id, role)
            except PermissionError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            return _kb_get(kb_id, user_id=user_id, role=role)
    return None


@router.patch("/ai-knowledge-bases/{kb_id}")
def settings_ai_knowledge_bases_update(
    kb_id: str,
    payload: AiKnowledgeBasePatch,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    try:
        item = _kb_update(
            kb_id,
            payload.model_dump(exclude_unset=True),
            user_id=current_user.id,
            role=role,
        )
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    if not item:
        return JSONResponse({"detail": "Không tìm thấy Knowledge Base."}, status_code=404)
    return JSONResponse({"item": item, "items": _kb_items_with_stats(user_id=current_user.id, role=role)})


@router.delete("/ai-knowledge-bases/{kb_id}")
def settings_ai_knowledge_bases_delete(
    request: Request,
    kb_id: str,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    try:
        ok = _kb_delete(kb_id, user_id=current_user.id, role=role)
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    if not ok:
        return JSONResponse({"detail": "Không tìm thấy Knowledge Base."}, status_code=404)
    log_audit_event(
        action="knowledge_base.delete",
        user_id=current_user.id,
        resource_type="knowledge_base",
        resource_id=kb_id,
        request=request,
    )
    return JSONResponse({"ok": True, "items": _kb_items_with_stats(user_id=current_user.id, role=role)})


@router.post("/ai-knowledge-bases/{kb_id}/clone")
def settings_ai_knowledge_bases_clone(
    request: Request,
    kb_id: str,
    payload: AiKnowledgeCloneBody | None = None,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    try:
        item = _kb_clone(
            kb_id,
            user_id=current_user.id,
            role=role,
            name=(payload.name if payload else None),
        )
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    item["stats"] = _kb_stats(str(item.get("id") or ""))
    log_audit_event(
        action="knowledge_base.clone",
        user_id=current_user.id,
        resource_type="knowledge_base",
        resource_id=str(item.get("id") or ""),
        detail={"source_kb_id": kb_id, "name": item.get("name")},
        request=request,
    )
    return JSONResponse(
        {"item": item, "items": _kb_items_with_stats(user_id=current_user.id, role=role)}
    )


@router.get("/ai-knowledge-bases/{kb_id}/documents")
def settings_ai_knowledge_bases_documents(
    kb_id: str,
    doc_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_get(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "not found"}, status_code=404)
    if doc_id and str(doc_id).strip():
        doc = _kb_get_document(kb_id, str(doc_id).strip())
        if not doc:
            return JSONResponse({"detail": "document not found"}, status_code=404)
        return JSONResponse({"document": doc})
    return JSONResponse({"documents": _kb_list_documents(kb_id), "stats": _kb_stats(kb_id)})


@router.get("/ai-knowledge-bases/{kb_id}/documents/{doc_id}")
def settings_ai_knowledge_bases_document_get(
    kb_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_get(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "not found"}, status_code=404)
    doc = _kb_get_document(kb_id, doc_id)
    if not doc:
        return JSONResponse({"detail": "document not found"}, status_code=404)
    return JSONResponse({"document": doc})


@router.post("/ai-knowledge-bases/{kb_id}/import")
async def settings_ai_knowledge_bases_import(
    request: Request,
    kb_id: str,
    file: UploadFile | None = File(None),
    title: str | None = Form(None),
    text: str | None = Form(None),
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_require_writable(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "Không tìm thấy Knowledge Base."}, status_code=404)
    try:
        if file and file.filename:
            data = await file.read()
            result = _kb_import_bytes(kb_id, file.filename, data, embed=False)
        elif text and str(text).strip():
            result = _kb_import_text(kb_id, str(title or "").strip(), str(text), embed=False)
        else:
            return JSONResponse({"detail": "Cần upload file hoặc dán văn bản."}, status_code=400)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    item = _kb_get(kb_id, user_id=current_user.id, role=role)
    if item:
        item["stats"] = result.get("stats") or _kb_stats(kb_id)
    log_audit_event(
        action="knowledge_base.import",
        user_id=current_user.id,
        resource_type="knowledge_base",
        resource_id=kb_id,
        detail={"filename": (file.filename if file else None), "title": title},
        request=request,
    )
    return JSONResponse(
        {
            "ok": True,
            "result": result,
            "item": item,
            "items": _kb_items_with_stats(user_id=current_user.id, role=role),
        }
    )


@router.post("/ai-knowledge-bases/{kb_id}/import-text")
def settings_ai_knowledge_bases_import_text(
    kb_id: str,
    payload: AiKnowledgeImportTextBody,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_require_writable(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "Không tìm thấy Knowledge Base."}, status_code=404)
    try:
        result = _kb_import_text(kb_id, str(payload.title or "").strip(), payload.text, embed=False)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "result": result, "items": _kb_items_with_stats(user_id=current_user.id, role=role)})


@router.post("/ai-knowledge-bases/{kb_id}/reindex")
def settings_ai_knowledge_bases_reindex(
    kb_id: str,
    current_user: User = Depends(require_write_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_require_writable(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "Không tìm thấy Knowledge Base."}, status_code=404)
    try:
        result = _kb_reindex(kb_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "result": result, "items": _kb_items_with_stats(user_id=current_user.id, role=role)})


@router.post("/ai-knowledge-bases/{kb_id}/search")
def settings_ai_knowledge_bases_search(
    kb_id: str,
    payload: AiKnowledgeSearchBody,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    role = normalize_role(current_user.role)
    if not _kb_get(kb_id, user_id=current_user.id, role=role):
        return JSONResponse({"detail": "not found"}, status_code=404)
    hits = _kb_search(kb_id, payload.query, limit=int(payload.limit or 8))
    return JSONResponse({"query": payload.query, "hits": hits})
