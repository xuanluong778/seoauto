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
    """Chuẩn hóa src thành absolute https khi có thể."""
    s = str(src or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith("/"):
        base = str(site_base or "").strip().rstrip("/")
        if base:
            return urljoin(base + "/", s.lstrip("/"))
        return s
    if s.lower().startswith("http://"):
        return "https://" + s[7:]
    return s


def probe_image_url(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """HEAD/GET nhẹ — trả ok, status_code, error."""
    u = normalize_content_image_src(str(url or "").strip())
    if not u.lower().startswith(("http://", "https://")):
        if u.startswith("/static/") or u.startswith("/api/user-files/"):
            return {"ok": True, "status_code": None, "error": ""}
        return {"ok": False, "status_code": None, "error": "not_absolute_url"}
    try:
        r = requests.head(
            u,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SEOAuto/1.0)"},
        )
        if r.status_code in (405, 501):
            r = requests.get(
                u,
                timeout=timeout,
                stream=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SEOAuto/1.0)"},
            )
            r.close()
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

        if probe_remote and src.lower().startswith(("http://", "https://")):
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


def validate_image_url_for_insert(
    url: str,
    *,
    source: str = "insert",
    site_base: str = "",
    probe_remote: bool = True,
) -> str:
    """Raise ValueError nếu URL không dùng được; trả URL đã chuẩn hóa."""
    norm = normalize_content_image_src(str(url or "").strip(), site_base=site_base)
    if not is_usable_image_src(norm):
        log_image_error(image_url=norm, source=source, error_message="reject_insert")
        raise ValueError("URL ảnh không hợp lệ — cần absolute https hoặc /static/.")
    if probe_remote and norm.lower().startswith(("http://", "https://")):
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
