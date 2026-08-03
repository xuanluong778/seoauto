"""CAU Sửa SEO — update validation, change summary, WP conflict guard.

Auto Update modal only. Does not modify Content AI Single/Bulk paths.
"""

from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any

from fastapi import HTTPException

from app.services.content_diff import build_content_diff
from app.services.content_update_agent import validate_preserved_markup


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(html or ""))).strip()


def _word_count(html: str) -> int:
    t = _plain(html)
    return len(t.split()) if t else 0


def _headings(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in re.finditer(r"<h([1-6])\b[^>]*>([\s\S]*?)</h\1>", html or "", flags=re.I):
        out.append({"level": int(m.group(1)), "text": _plain(m.group(2))[:200]})
    return out


def _count(pat: str, html: str) -> int:
    return len(re.findall(pat, html or "", flags=re.I | re.S))


def normalize_modified(value: str | None) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    # Compare without timezone suffix noise
    return s.replace("Z", "").replace("+00:00", "").rstrip("Z")[:19]


def pick_wp_modified(payload: dict[str, Any] | None) -> str:
    """Canonical modified timestamp — prefer modified_gmt (UTC) from WordPress."""
    if not payload:
        return ""
    gmt = str(payload.get("modified_gmt") or "").strip()
    if gmt:
        return gmt
    return str(payload.get("modified") or "").strip()


def normalize_html_baseline(html: str) -> str:
    s = str(html or "")
    s = re.sub(r">\s+<", "><", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def content_baseline_key(html: str) -> str:
    normalized = normalize_html_baseline(html)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


def wp_remote_matches_session_baseline(*, baseline_content: str, remote_content: str) -> bool:
    """True when WordPress body is still the version loaded into this edit session."""
    base_key = content_baseline_key(baseline_content)
    remote_key = content_baseline_key(remote_content)
    return bool(base_key and remote_key and base_key == remote_key)


def resolve_expected_modified(
    *,
    session: dict[str, Any] | None,
    client_expected: str = "",
) -> str:
    """Session/server snapshot wins over client draft to avoid false conflicts."""
    sess = session or {}
    orig = sess.get("original") or {}
    for candidate in (
        str(sess.get("wp_modified") or "").strip(),
        str(orig.get("modified") or "").strip(),
        str(client_expected or "").strip(),
    ):
        if candidate:
            return candidate
    return ""


def validate_modal_content(*, title: str, content_html: str, old_content: str = "") -> dict[str, Any]:
    """Validate before WP update. Returns {ok, errors, warnings}."""
    errors: list[str] = []
    warnings: list[str] = []
    content = str(content_html or "")
    title_s = str(title or "").strip()

    if not title_s:
        errors.append("Title không được để trống.")
    plain = _plain(content)
    if not plain:
        errors.append("Nội dung HTML rỗng — không thể cập nhật.")

    h1 = _count(r"<h1\b", content)
    if h1 == 0:
        warnings.append("Không có thẻ H1 trong nội dung.")
    elif h1 > 1:
        warnings.append(f"Có {h1} thẻ H1 — nên chỉ còn 1.")

    if old_content:
        warnings.extend(validate_preserved_markup(old_content, content))

    # Structural presence checks (informational if new content adds none and old had none)
    for label, pat in (
        ("ảnh (img)", r"<img\b"),
        ("link (a)", r"<a\b"),
        ("bảng (table)", r"<table\b"),
        ("shortcode", r"\[[a-zA-Z][\w\-]*"),
        ("embed/iframe", r"<(iframe|embed|video|audio)\b"),
        ("Gutenberg block", r"<!--\s*wp:"),
    ):
        o = _count(pat, old_content)
        n = _count(pat, content)
        if o > 0 and n < o:
            warnings.append(f"Có thể mất {label}: {o} → {n}")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def build_change_summary(
    *,
    old_title: str,
    new_title: str,
    old_content: str,
    new_content: str,
    old_excerpt: str = "",
    new_excerpt: str = "",
    seo_before: dict[str, Any] | None = None,
    seo_after: dict[str, Any] | None = None,
    post_status: str = "",
    patches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    diff = build_content_diff(
        old_title=old_title,
        new_title=new_title,
        old_content=old_content,
        new_content=new_content,
        old_excerpt=old_excerpt,
        new_excerpt=new_excerpt,
    )
    old_h = _headings(old_content)
    new_h = _headings(new_content)
    old_texts = [h["text"] for h in old_h]
    new_texts = [h["text"] for h in new_h]
    added_headings = [t for t in new_texts if t and t not in old_texts]
    removed_headings = [t for t in old_texts if t and t not in new_texts]
    changed_headings = []
    for i, nh in enumerate(new_h):
        if i < len(old_h) and old_h[i]["text"] != nh["text"] and nh["text"] not in added_headings:
            changed_headings.append({"from": old_h[i]["text"], "to": nh["text"], "level": nh["level"]})

    old_paras = re.findall(r"<p\b[^>]*>[\s\S]*?</p>", old_content or "", flags=re.I)
    new_paras = re.findall(r"<p\b[^>]*>[\s\S]*?</p>", new_content or "", flags=re.I)
    paras_edited = abs(len(new_paras) - len(old_paras))
    # count changed overlapping paras
    for i in range(min(len(old_paras), len(new_paras))):
        if old_paras[i] != new_paras[i]:
            paras_edited += 1

    old_w = _word_count(old_content)
    new_w = _word_count(new_content)
    words_added = max(0, new_w - old_w)
    words_removed = max(0, old_w - new_w)

    old_links = set(re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', old_content or "", flags=re.I))
    new_links = set(re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', new_content or "", flags=re.I))
    old_imgs = set(re.findall(r'<img\b[^>]*src=["\']([^"\']+)["\']', old_content or "", flags=re.I))
    new_imgs = set(re.findall(r'<img\b[^>]*src=["\']([^"\']+)["\']', new_content or "", flags=re.I))

    seo_b = int((seo_before or {}).get("score") or 0) if seo_before else None
    seo_a = int((seo_after or {}).get("score") or 0) if seo_after else None

    content_field = next((f for f in (diff.get("fields") or []) if f.get("field") == "content"), {})
    return {
        "seo_before": seo_b,
        "seo_after": seo_a,
        "seo_delta": (seo_a - seo_b) if seo_a is not None and seo_b is not None else None,
        "headings_added": added_headings[:20],
        "headings_removed": removed_headings[:20],
        "headings_changed": changed_headings[:20],
        "paragraphs_edited": paras_edited,
        "words_added": words_added,
        "words_removed": words_removed,
        "words_before": old_w,
        "words_after": new_w,
        "internal_links_added": sorted(new_links - old_links)[:30],
        "internal_links_removed": sorted(old_links - new_links)[:30],
        "images_added": sorted(new_imgs - old_imgs)[:30],
        "images_removed": sorted(old_imgs - new_imgs)[:30],
        "post_status": post_status,
        "diff": diff,
        "diff_lines": (content_field.get("diff_lines") or [])[:80],
        "patches": list(patches or [])[:100],
        "patches_count": len(patches or []),
    }


def assert_session_owned(session: dict[str, Any] | None, user_id: int) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=404, detail="Không tìm thấy session.")
    if int(session.get("user_id") or 0) != int(user_id):
        raise HTTPException(status_code=403, detail="Không có quyền với session này.")
    return session


def assert_site_matches_session(session: dict[str, Any], site_id: str | None = None) -> None:
    sess_site = str(session.get("site_id") or "")
    if site_id and str(site_id) != sess_site:
        raise HTTPException(status_code=403, detail="site_id không khớp session.")


def detect_wp_conflict(
    *,
    expected_modified: str,
    remote_modified: str,
    remote_modified_alt: str = "",
    baseline_content: str = "",
    remote_content: str = "",
) -> dict[str, Any] | None:
    base_key = content_baseline_key(baseline_content)
    remote_key = content_baseline_key(remote_content)
    if base_key and remote_key:
        if base_key == remote_key:
            return None
        return {
            "conflict": True,
            "expected_modified": expected_modified,
            "remote_modified": remote_modified or remote_modified_alt,
            "message": "Bài trên WordPress đã thay đổi sau khi bạn mở Sửa SEO. Không cập nhật để tránh ghi đè.",
        }

    exp = normalize_modified(expected_modified)
    if not exp:
        return None
    remote_candidates = {
        normalize_modified(remote_modified),
        normalize_modified(remote_modified_alt),
    }
    remote_candidates.discard("")
    if not remote_candidates:
        return None
    if exp in remote_candidates:
        return None
    return {
        "conflict": True,
        "expected_modified": expected_modified,
        "remote_modified": remote_modified or remote_modified_alt,
        "message": "Bài trên WordPress đã thay đổi sau khi bạn mở Sửa SEO. Không cập nhật để tránh ghi đè.",
    }
