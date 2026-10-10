"""Validate và làm sạch ảnh trong HTML Content AI / Chatbot."""

from __future__ import annotations

import logging
import re
from html import escape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_LOG = logging.getLogger(__name__)

_PLACEHOLDER_SRC_RE = re.compile(
    r"^(?:#|about:blank|javascript:|data:image/svg\+xml|placeholder)(?:\b|$)",
    re.I,
)
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|avif|bmp)(\?|#|$)", re.I)
_HAS_VIET_DIACRITIC_RE = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
    re.I,
)
_ALLOWED_RELATIVE_PREFIXES = ("/static/", "/api/user-files/")


def _base_valid_image_src(src: str) -> bool:
    s = str(src or "").strip()
    if not s:
        return False
    if _PLACEHOLDER_SRC_RE.match(s):
        return False
    low = s.lower()
    if low.startswith(("http://", "https://", "//", "/")):
        return True
    return low.startswith("data:image/") and "svg" not in low


def log_image_error(
    *,
    image_url: str = "",
    source: str = "",
    status_code: int | None = None,
    error_message: str = "",
) -> None:
    _LOG.warning(
        "content_ai_image_guard url=%s source=%s status=%s error=%s",
        str(image_url or "")[:500],
        str(source or "")[:80],
        status_code if status_code is not None else "-",
        str(error_message or "")[:300],
    )


def looks_like_text_not_url(src: str) -> bool:
    """True khi src giống alt/caption (vd: 'Dịch vụ sửa máy tính tại Thủ Đức') chứ không phải URL."""
    s = str(src or "").strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith(("http://", "https://", "//")):
        return False
    if low.startswith(_ALLOWED_RELATIVE_PREFIXES):
        return False
    if low.startswith("data:image/") and "svg" not in low:
        return False
    if _IMAGE_EXT_RE.search(s) and "/" in s and " " not in s.split("/")[-1]:
        return False
    if " " in s and not _IMAGE_EXT_RE.search(s):
        return True
    if _HAS_VIET_DIACRITIC_RE.search(s) and not low.startswith("/"):
        return True
    if not re.search(r"[/.]", s) and len(s) > 24:
        return True
    return False


def is_stored_image_src(src: str) -> bool:
    """Ảnh đã lưu trên server (upload/API) — tin cậy cho hiển thị."""
    low = str(src or "").strip().lower()
    return low.startswith("/static/uploads/") or low.startswith("/api/user-files/")


def is_llm_hallucinated_external_src(src: str) -> bool:
    """URL http(s) ngoài do LLM bịa — không phải file đã lưu trên hệ thống."""
    s = str(src or "").strip()
    if not s or is_stored_image_src(s):
        return False
    low = s.lower()
    if low.startswith("data:image/") and "svg" not in low:
        return False
    return low.startswith(("http://", "https://", "//"))


def is_usable_image_src(src: str, *, allow_relative_static: bool = True) -> bool:
    """URL ảnh dùng được trong content — không placeholder, không text thay URL."""
    s = str(src or "").strip()
    if not _base_valid_image_src(s):
        return False
    if looks_like_text_not_url(s):
        return False
    low = s.lower()
    if low.startswith(("http://", "https://", "//")):
        try:
            p = urlparse(s if "://" in s else f"https:{s}")
            if not p.netloc:
                return False
        except Exception:
            return False
        return True
    if allow_relative_static and low.startswith(_ALLOWED_RELATIVE_PREFIXES):
        return True
    if low.startswith("data:image/") and "svg" not in low:
        return True
    return False


def normalize_content_image_src(src: str, *, site_base: str = "") -> str:
    """Chuẩn hóa src thành absolute https khi có thể.

    Critical: never rewrite app-hosted paths (/api/user-files/, /static/...)
    onto ``target_website``. Those files live on seoauto.vn, not the customer's
    WordPress domain — rewriting breaks insert validation and empty <img> in editor.
    """
    s = str(src or "").strip()
    if not s:
        return ""
    # Strip auth tokens from path for stable storage
    if "token=" in s and ("/api/user-files/" in s.lower() or s.startswith("/static/")):
        s = re.sub(r"([?&])token=[^&]*", "", s).rstrip("?&")
    if s.startswith("//"):
        return f"https:{s}"
    low = s.lower()
    # App-private & static assets stay on this product host — relative only.
    if low.startswith(("/api/user-files/", "/static/")):
        return s
    # Absolute URL that was wrongly built as {target_website}/api/user-files/...
    try:
        p = urlparse(s if "://" in s else "")
        path = str(p.path or "")
        if path.startswith(("/api/user-files/", "/static/uploads/", "/static/")) and path.startswith("/api/"):
            return path + (("?" + p.query) if p.query and "token=" not in p.query else "")
        if path.startswith("/api/user-files/") or path.startswith("/static/uploads/"):
            return path
        if path.startswith("/static/") and p.netloc and "user-files" not in path:
            # /static/ on external site may be intentional for WP uploads — only rewrite
            # when netloc looks like it incorrectly hosts our private path (handled above).
            pass
    except Exception:
        pass
    # Mis-prefixed absolute that still contains our private path
    m = re.search(r"(https?://[^/]+)?(/api/user-files/[^?\s\"']+)", s, flags=re.I)
    if m and m.group(2):
        return m.group(2)
    m2 = re.search(r"(https?://[^/]+)?(/static/uploads/[^?\s\"']+)", s, flags=re.I)
    if m2 and m2.group(2):
        return m2.group(2)

    if s.startswith("/"):
        base = str(site_base or "").strip().rstrip("/")
        if base:
            return urljoin(base + "/", s.lstrip("/"))
        return s
    if s.lower().startswith("http://"):
        return "https://" + s[7:]
    return s


def rehydrate_app_media_src(src: str) -> str:
    """Force app-hosted media back to site-relative path (never customer domain)."""
    s = str(src or "").strip()
    if not s:
        return ""
    s = re.sub(r"([?&])token=[^&]*", "", s).rstrip("?&")
    m = re.search(r"(/api/user-files/[^?\s\"'#]+)", s, flags=re.I)
    if m:
        return m.group(1)
    m2 = re.search(r"(/static/uploads/[^?\s\"'#]+)", s, flags=re.I)
    if m2:
        return m2.group(1)
    if s.lower().startswith(("/api/user-files/", "/static/")):
        return s.split("?", 1)[0]
    return s


def validate_image_url_for_insert(
    url: str,
    *,
    source: str = "insert",
    site_base: str = "",
    probe_remote: bool = True,
) -> str:
    """Raise ValueError nếu URL không dùng được; trả URL đã chuẩn hóa."""
    raw = str(url or "").strip()
    # Prefer pure app paths before any site_base join
    app_path = rehydrate_app_media_src(raw)
    if app_path.startswith(("/api/user-files/", "/static/")):
        if not is_usable_image_src(app_path):
            log_image_error(image_url=app_path, source=source, error_message="reject_insert_app")
            raise ValueError("URL ảnh không hợp lệ — cần absolute https hoặc /static/.")
        # Local app files are already on disk after import — never HTTP-probe via target site.
        return app_path

    norm = normalize_content_image_src(raw, site_base=site_base)
    if not is_usable_image_src(norm):
        log_image_error(image_url=norm, source=source, error_message="reject_insert")
        raise ValueError("URL ảnh không hợp lệ — cần absolute https hoặc /static/.")
    if probe_remote and norm.lower().startswith(("http://", "https://")):
        # Don't probe rewritten customer-domain copies of app media
        if re.search(r"/api/user-files/", norm, flags=re.I):
            return rehydrate_app_media_src(norm) or norm
        probe = probe_image_url(norm)
        if not probe.get("ok"):
            log_image_error(
                image_url=norm,
                source=source,
                status_code=probe.get("status_code"),
                error_message=str(probe.get("error") or "unreachable"),
            )
            raise ValueError(
                f"Ảnh không tải được (HTTP {probe.get('status_code') or 'lỗi'})."
            )
    return norm


def probe_image_url(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """HEAD/GET nhẹ — trả ok, status_code, error."""
    u = normalize_content_image_src(str(url or "").strip())
    if not u.lower().startswith(("http://", "https://")):
        if u.startswith("/static/") or u.startswith("/api/user-files/"):
            return {"ok": True, "status_code": None, "error": ""}
        return {"ok": False, "status_code": None, "error": "not_absolute_url"}
    try:
        from app.services.url_safety import safe_requests_get, validate_public_http_url

        blocked = validate_public_http_url(u)
        if blocked:
            return {"ok": False, "status_code": None, "error": blocked}
        r = safe_requests_get(
            u,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SEOAuto/1.0)"},
        )
        # HEAD not supported in safe_requests_get; GET body is short-circuited by status check
        if r.status_code >= 400:
            return {"ok": False, "status_code": int(r.status_code), "error": f"HTTP {r.status_code}"}
        return {"ok": True, "status_code": int(r.status_code), "error": ""}
    except Exception as exc:
        return {"ok": False, "status_code": None, "error": str(exc)[:200]}


def _ensure_img_attrs(img) -> None:
    if not img or not getattr(img, "name", None):
        return
    alt = str(img.get("alt") or "").strip()
    if not alt:
        fig = img.find_parent("figure")
        if fig:
            cap = fig.find("figcaption")
            if cap:
                alt = re.sub(r"\s+", " ", cap.get_text(" ", strip=True))[:200]
        if not alt:
            alt = "Ảnh minh họa"
        img["alt"] = alt
    if not str(img.get("loading") or "").strip():
        img["loading"] = "lazy"
    style = str(img.get("style") or "").strip()
    if "max-width" not in style.lower():
        img["style"] = (style + "; max-width:100%;height:auto;").strip("; ")


def sanitize_content_html_images(
    html: str,
    *,
    site_base: str = "",
    source: str = "sanitize",
    probe_remote: bool = False,
) -> str:
    """
    Loại bỏ/sửa thẻ img hỏng trong HTML.
    - Không chèn giữ img nếu src rỗng, text thay URL, placeholder.
    - Chuẩn hóa https cho URL tuyệt đối.
    """
    raw = str(html or "").strip()
    if not raw or "<img" not in raw.lower():
        return raw

    soup = BeautifulSoup(raw, "html.parser")
    changed = False
    for img in list(soup.find_all("img")):
        src = str(img.get("src") or "").strip()
        if not src:
            log_image_error(image_url="", source=source, error_message="empty_src")
            fig = img.find_parent("figure")
            if fig:
                fig.decompose()
            else:
                img.decompose()
            changed = True
            continue

        # Always rehydrate app-hosted paths before joining site_base
        app = rehydrate_app_media_src(src)
        if app.startswith(("/api/user-files/", "/static/uploads/")):
            if app != src:
                img["src"] = app
                src = app
                changed = True
        else:
            norm = normalize_content_image_src(src, site_base=site_base)
            if norm and norm != src:
                img["src"] = norm
                src = norm
                changed = True

        if not is_usable_image_src(src):
            log_image_error(
                image_url=src,
                source=source,
                error_message="invalid_src_shape",
            )
            fig = img.find_parent("figure")
            if fig:
                fig.decompose()
            else:
                img.decompose()
            changed = True
            continue

        # Never HTTP-probe (and never rewrite) private app media via customer domain
        if src.lower().startswith(("/api/user-files/", "/static/")):
            _ensure_img_attrs(img)
            changed = True
            continue

        if probe_remote and src.lower().startswith(("http://", "https://")):
            # Broken rewrite: host points to target website but path is our API
            if "/api/user-files/" in src.lower():
                fixed = rehydrate_app_media_src(src)
                img["src"] = fixed
                src = fixed
                changed = True
                _ensure_img_attrs(img)
                continue
            probe = probe_image_url(src)
            if not probe.get("ok"):
                log_image_error(
                    image_url=src,
                    source=source,
                    status_code=probe.get("status_code"),
                    error_message=str(probe.get("error") or "probe_failed"),
                )
                fig = img.find_parent("figure")
                if fig:
                    fig.decompose()
                else:
                    img.decompose()
                changed = True
                continue

        _ensure_img_attrs(img)
        changed = True

    body = soup.body
    out_html = "".join(str(x) for x in body.contents).strip() if body else str(soup).strip()
    return out_html if changed else raw


def repair_content_html_images(
    html: str,
    *,
    site_base: str = "",
    source: str = "repair",
    probe_remote: bool = True,
    strip_llm_external: bool = True,
) -> str:
    """
    Làm sạch ảnh hỏng: bỏ URL LLM bịa, probe URL ngoài 404, giữ /static/uploads/.
    """
    raw = str(html or "").strip()
    if not raw or "<img" not in raw.lower():
        return raw

    cleaned = raw
    if strip_llm_external:
        soup = BeautifulSoup(cleaned, "html.parser")
        changed = False
        for img in list(soup.find_all("img")):
            src = str(img.get("src") or "").strip()
            if is_llm_hallucinated_external_src(src):
                log_image_error(
                    image_url=src,
                    source=source,
                    error_message="llm_hallucinated_external",
                )
                fig = img.find_parent("figure")
                if fig:
                    fig.decompose()
                else:
                    img.decompose()
                changed = True
        if changed:
            body = soup.body
            cleaned = "".join(str(x) for x in body.contents).strip() if body else str(soup).strip()

    return sanitize_content_html_images(
        cleaned,
        site_base=site_base,
        source=source,
        probe_remote=probe_remote,
    )
