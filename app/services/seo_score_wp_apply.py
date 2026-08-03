"""Áp dụng bản tối ưu SEO Score lên WordPress — đúng một trường."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.seo import Project, SeoScoreApplyLog
from app.services.seo_score_ai_fix import normalize_page_field
from app.services.site_ownership import user_owns_wp_site
from app.services.wp_connect import normalize_wp_base_url
from app.services.wp_site_connector import (
    _wp_headers,
    fetch_post_by_url,
    get_site_credentials,
    list_sites,
)

_LOG = logging.getLogger(__name__)

MANUAL_APPLY_MESSAGE = (
    "Chưa thể áp dụng tự động. Vui lòng copy nội dung tối ưu để cập nhật thủ công."
)

_APPLY_FIELDS = frozenset({
    "title",
    "meta_description",
    "heading",
    "image_alt",
    "intro",
    "content_section",
})


class SeoScoreApplyError(Exception):
    def __init__(self, message: str, *, manual_only: bool = False) -> None:
        super().__init__(message)
        self.manual_only = manual_only


def _host_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        host = (urlparse(raw).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return raw.lower().strip("/")


def url_belongs_to_project(url: str, project_domain: str) -> bool:
    url_host = _host_key(url)
    proj_host = _host_key(project_domain)
    if not url_host or not proj_host:
        return False
    return url_host == proj_host or url_host.endswith("." + proj_host)


def _json_preview(value: Any, *, limit: int = 8000) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except Exception:
        return str(value)[:limit]


def record_seo_score_apply_log(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    url: str,
    page_field: str,
    before: Any,
    after: Any,
    status: str,
    error: str = "",
) -> None:
    """Ghi log apply (DB + structured log)."""
    _LOG.info(
        "seo_score_apply user_id=%s project_id=%s url=%s page_field=%s status=%s error=%s",
        user_id,
        project_id,
        url,
        page_field,
        status,
        error or "-",
    )
    try:
        row = SeoScoreApplyLog(
            user_id=user_id,
            project_id=project_id,
            url=str(url or "")[:2000],
            page_field=str(page_field or "")[:64],
            before_json=_json_preview(before),
            after_json=_json_preview(after),
            status=str(status or "unknown")[:32],
            error=str(error or "")[:2000],
        )
        db.add(row)
        db.flush()
    except Exception:
        _LOG.exception("seo_score_apply DB log failed user=%s url=%s", user_id, url)


def _load_project(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    url: str,
) -> Project | None:
    if project_id is not None:
        project = (
            db.query(Project)
            .filter(Project.id == int(project_id), Project.user_id == user_id)
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Không tìm thấy project.")
        if not url_belongs_to_project(url, project.domain):
            raise HTTPException(status_code=400, detail="URL không thuộc domain của project.")
        return project

    host = _host_key(url)
    if not host:
        return None
    for project in db.query(Project).filter(Project.user_id == user_id).all():
        if url_belongs_to_project(url, project.domain):
            return project
    return None


def _find_wp_site_for_domain(user_id: int, project_domain: str) -> dict[str, Any] | None:
    target = _host_key(project_domain)
    if not target:
        return None
    for site in list_sites(user_id):
        site_url = str(site.get("url") or "")
        if not user_owns_wp_site(user_id, site_url):
            continue
        if _host_key(site_url) == target:
            return site
    return None


def _manual_result(*, pf: str, project_id: int | None = None, site_id: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "applied": False,
        "manual_only": True,
        "message": MANUAL_APPLY_MESSAGE,
        "page_field": pf,
        "project_id": project_id,
        "site_id": site_id,
    }


def _wp_patch(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    resource: str,
    wp_id: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/wp-json/wp/v2/{resource}/{int(wp_id)}"
    try:
        r = requests.post(url, headers=headers, auth=auth, json=body, timeout=60)
    except requests.RequestException as exc:
        raise SeoScoreApplyError(f"Không gọi được WordPress: {exc}") from exc
    if r.status_code >= 400:
        raise SeoScoreApplyError(
            f"WordPress từ chối cập nhật (HTTP {r.status_code}): {(r.text or '')[:300]}"
        )
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _patch_seo_meta(
    *,
    base: str,
    headers: dict[str, str],
    auth: tuple[str, str],
    resource: str,
    wp_id: int,
    meta_description: str,
    seo_title: str = "",
) -> None:
    desc = str(meta_description or "").strip()
    title = str(seo_title or "").strip()
    if not desc and not title:
        return
    key_sets = [
        {"title": "rank_math_title", "description": "rank_math_description"},
        {"title": "_rank_math_title", "description": "_rank_math_description"},
        {"title": "yoast_wpseo_title", "description": "yoast_wpseo_metadesc"},
        {"description": "meta_description"},
        {"description": "_meta_description"},
    ]
    for key_set in key_sets:
        meta_payload: dict[str, str] = {}
        if title and key_set.get("title"):
            meta_payload[key_set["title"]] = title
        if desc and key_set.get("description"):
            meta_payload[key_set["description"]] = desc
        if not meta_payload:
            continue
        try:
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"meta": meta_payload},
            )
            return
        except SeoScoreApplyError:
            continue


def _norm_img_src(src: str, base: str = "") -> str:
    raw = str(src or "").strip()
    if not raw:
        return ""
    try:
        full = urljoin(base + "/", raw) if base else raw
        p = urlparse(full)
        return (p.path or "").rstrip("/").lower()
    except Exception:
        return raw.lower().rstrip("/")


def _plain_text(html: str) -> str:
    return BeautifulSoup(str(html or ""), "html.parser").get_text(" ", strip=True)


def _verify_text_before(current: str, before: Any, *, label: str) -> None:
    cur = str(current or "").strip()
    exp = str(before or "").strip()
    if not exp or not cur:
        return
    if cur == exp or cur.lower() == exp.lower():
        return
    if exp in cur or cur in exp:
        return
    raise SeoScoreApplyError(
        f"{label} trên WordPress đã thay đổi so với bản trước khi chấm điểm. {MANUAL_APPLY_MESSAGE}",
        manual_only=True,
    )


def _apply_heading_html(content: str, heading_after: dict[str, Any], heading_before: dict[str, Any] | None = None) -> str:
    soup = BeautifulSoup(str(content or ""), "html.parser")
    before = heading_before if isinstance(heading_before, dict) else {}
    after = heading_after if isinstance(heading_after, dict) else {}

    def replace_level(tag: str, before_list: list[Any], after_list: list[Any]) -> None:
        before_texts = [str(x).strip() for x in before_list if str(x).strip()]
        after_texts = [str(x).strip() for x in after_list if str(x).strip()]
        if not after_texts:
            return
        tags = soup.find_all(tag)
        if before_texts:
            for idx, btext in enumerate(before_texts):
                matched = False
                for node in tags:
                    if node.get_text(" ", strip=True) == btext:
                        node.clear()
                        node.append(after_texts[min(idx, len(after_texts) - 1)])
                        matched = True
                        break
                if not matched:
                    raise SeoScoreApplyError(
                        f"Không tìm thấy {tag.upper()} «{btext[:120]}» trong nội dung WordPress. {MANUAL_APPLY_MESSAGE}",
                        manual_only=True,
                    )
            return
        for idx, text in enumerate(after_texts):
            if idx < len(tags):
                tags[idx].clear()
                tags[idx].append(text)

    replace_level("h1", list(before.get("h1") or []), list(after.get("h1") or []))
    replace_level("h2", list(before.get("h2") or []), list(after.get("h2") or []))
    replace_level("h3", list(before.get("h3") or []), list(after.get("h3") or []))
    return str(soup)


def _apply_image_alt_html(
    content: str,
    alt_rows: list[dict[str, Any]],
    *,
    base: str,
    before_rows: list[dict[str, Any]] | None = None,
) -> str:
    if not isinstance(alt_rows, list) or not alt_rows:
        raise SeoScoreApplyError("Thiếu dữ liệu alt để áp dụng.")
    by_src: dict[str, str] = {}
    for row in alt_rows:
        if not isinstance(row, dict):
            continue
        src = str(row.get("src") or row.get("url") or "").strip()
        alt = str(row.get("alt") or "").strip()
        if src and alt:
            by_src[_norm_img_src(src, base)] = alt

    if not by_src:
        raise SeoScoreApplyError("Không có alt hợp lệ để áp dụng.")

    before_alt: dict[str, str] = {}
    if isinstance(before_rows, list):
        for row in before_rows:
            if not isinstance(row, dict):
                continue
            src = _norm_img_src(str(row.get("src") or row.get("url") or ""), base)
            if src:
                before_alt[src] = str(row.get("alt") or "")

    soup = BeautifulSoup(str(content or ""), "html.parser")
    changed = 0
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip()
        key = _norm_img_src(src, base)
        alt_val = by_src.get(key)
        if not alt_val:
            for k, alt in by_src.items():
                if k and (key.endswith(k) or k.endswith(key)):
                    alt_val = alt
                    key = k
                    break
        if not alt_val:
            continue
        if key in before_alt:
            current_alt = str(img.get("alt") or "")
            expected = before_alt[key]
            if expected != current_alt and expected not in ("", current_alt):
                raise SeoScoreApplyError(
                    f"Alt ảnh {src[:120]} đã thay đổi trên WordPress. {MANUAL_APPLY_MESSAGE}",
                    manual_only=True,
                )
        img["alt"] = alt_val
        changed += 1

    if changed == 0:
        raise SeoScoreApplyError(
            f"Không tìm thấy ảnh khớp trong nội dung WordPress. {MANUAL_APPLY_MESSAGE}",
            manual_only=True,
        )
    return str(soup)


def _apply_text_snippet(content: str, before: str, after: str, *, label: str) -> str:
    before_text = str(before or "").strip()
    after_text = str(after or "").strip()
    if not after_text:
        raise SeoScoreApplyError(f"{label} mới không hợp lệ.")
    if not before_text:
        raise SeoScoreApplyError(
            f"Không xác định được {label} gốc để thay thế. {MANUAL_APPLY_MESSAGE}",
            manual_only=True,
        )
    if before_text in content:
        return content.replace(before_text, after_text, 1)
    plain = _plain_text(content)
    if before_text in plain:
        raise SeoScoreApplyError(
            f"Tìm thấy {label} dạng text nhưng không khớp HTML — cần cập nhật thủ công. {MANUAL_APPLY_MESSAGE}",
            manual_only=True,
        )
    raise SeoScoreApplyError(
        f"Không tìm thấy {label} gốc trong nội dung WordPress. {MANUAL_APPLY_MESSAGE}",
        manual_only=True,
    )


def _apply_content_section_html(content: str, before: Any, after: Any) -> str:
    before_secs = before if isinstance(before, list) else []
    after_secs = after if isinstance(after, list) else []
    if not after_secs:
        raise SeoScoreApplyError("Section mới không hợp lệ.")
    updated = content
    replaced = 0
    for idx, bsec in enumerate(before_secs):
        if not isinstance(bsec, dict):
            continue
        asec = after_secs[min(idx, len(after_secs) - 1)] if after_secs else {}
        if not isinstance(asec, dict):
            continue
        btext = str(bsec.get("text") or "").strip()
        atext = str(asec.get("text") or "").strip()
        heading = str(bsec.get("heading") or "").strip()
        if not btext or not atext:
            continue
        if btext not in updated:
            raise SeoScoreApplyError(
                f"Không tìm thấy section «{heading or btext[:60]}» trong nội dung WordPress. {MANUAL_APPLY_MESSAGE}",
                manual_only=True,
            )
        updated = updated.replace(btext, atext, 1)
        replaced += 1
    if replaced == 0:
        raise SeoScoreApplyError(
            f"Không thay đổi được section nào. {MANUAL_APPLY_MESSAGE}",
            manual_only=True,
        )
    return updated


def apply_seo_score_fix_to_wordpress(
    db: Session,
    *,
    user_id: int,
    project_id: int | None,
    url: str,
    page_field: str,
    before: Any,
    after: Any,
    issue_id: str = "",
) -> dict[str, Any]:
    pf = normalize_page_field(page_field)
    project: Project | None = None
    site_id: str | None = None

    def _log(status: str, error: str = "", proj_id: int | None = None) -> None:
        record_seo_score_apply_log(
            db,
            user_id=user_id,
            project_id=proj_id if proj_id is not None else (project.id if project else project_id),
            url=url,
            page_field=pf,
            before=before,
            after=after,
            status=status,
            error=error,
        )

    if pf not in _APPLY_FIELDS:
        msg = "Trường này chưa hỗ trợ áp dụng tự động lên WordPress."
        _log("unsupported", msg)
        raise SeoScoreApplyError(msg, manual_only=True)

    try:
        project = _load_project(db, user_id=user_id, project_id=project_id, url=url)
    except HTTPException:
        _log("forbidden", "Project không thuộc user hoặc URL không khớp domain.")
        raise

    if not project:
        _log("manual", "Không tìm thấy project cho URL.")
        return _manual_result(pf=pf)

    site = _find_wp_site_for_domain(user_id, project.domain)
    if not site:
        _log("manual", "Không có WordPress connection.", project.id)
        return _manual_result(pf=pf, project_id=project.id)

    site_id = str(site.get("id") or "")
    try:
        post = fetch_post_by_url(site_id=site_id, user_id=user_id, post_url=url)
    except HTTPException as exc:
        detail = str(exc.detail) if exc.detail else "Không tìm thấy bài/trang WordPress."
        _LOG.info("seo_score_apply post lookup failed user=%s url=%s: %s", user_id, url, detail)
        _log("manual", detail, project.id)
        return _manual_result(pf=pf, project_id=project.id, site_id=site_id)

    cred = get_site_credentials(site_id, user_id)
    base = normalize_wp_base_url(cred["url"])
    headers = _wp_headers(cred["username"], cred["app_password"])
    auth = (cred["username"], cred["app_password"])
    wp_id = int(post.get("wp_id") or 0)
    post_type = str(post.get("post_type") or "post")
    resource = "pages" if post_type == "page" else "posts"
    content = str(post.get("content") or "")

    applied_value: Any = after

    try:
        if pf == "title":
            new_title = str(after or "").strip()
            if not new_title:
                raise SeoScoreApplyError("Title mới không hợp lệ.")
            _verify_text_before(str(post.get("title") or ""), before, label="Title")
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"title": new_title},
            )
            applied_value = new_title

        elif pf == "meta_description":
            new_meta = str(after or "").strip()
            if not new_meta:
                raise SeoScoreApplyError("Meta description mới không hợp lệ.")
            current_meta = str(post.get("excerpt") or "").strip() or _plain_text(str(post.get("excerpt") or ""))
            _verify_text_before(current_meta, before, label="Meta description")
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"excerpt": new_meta},
            )
            _patch_seo_meta(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                meta_description=new_meta,
                seo_title=str(post.get("title") or ""),
            )
            applied_value = new_meta

        elif pf == "heading":
            if not isinstance(after, dict):
                raise SeoScoreApplyError("Dữ liệu heading không hợp lệ.")
            heading_before = before if isinstance(before, dict) else {}
            new_content = _apply_heading_html(content, after, heading_before)
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"content": new_content},
            )
            applied_value = after

        elif pf == "image_alt":
            if not isinstance(after, list):
                raise SeoScoreApplyError("Dữ liệu image alt không hợp lệ.")
            before_rows = before if isinstance(before, list) else []
            new_content = _apply_image_alt_html(content, after, base=base, before_rows=before_rows)
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"content": new_content},
            )
            applied_value = after

        elif pf == "intro":
            if isinstance(after, str):
                after_text = after
            else:
                after_text = str(after or "")
            before_text = str(before or "") if isinstance(before, str) else str(before or "")
            new_content = _apply_text_snippet(content, before_text, after_text, label="Đoạn mở bài")
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"content": new_content},
            )
            applied_value = after_text.strip()

        elif pf == "content_section":
            new_content = _apply_content_section_html(content, before, after)
            _wp_patch(
                base=base,
                headers=headers,
                auth=auth,
                resource=resource,
                wp_id=wp_id,
                body={"content": new_content},
            )
            applied_value = after

        else:
            raise SeoScoreApplyError(
                "Trường này chưa hỗ trợ áp dụng tự động.",
                manual_only=True,
            )
    except SeoScoreApplyError as exc:
        _log("manual" if exc.manual_only else "error", str(exc), project.id)
        raise

    _log("success", "", project.id)
    return {
        "ok": True,
        "applied": True,
        "manual_only": False,
        "message": "Đã áp dụng lên WordPress.",
        "page_field": pf,
        "applied_value": applied_value,
        "wp_id": wp_id,
        "post_url": str(post.get("link") or url),
        "site_id": site_id,
        "project_id": project.id,
        "issue_id": str(issue_id or ""),
    }
