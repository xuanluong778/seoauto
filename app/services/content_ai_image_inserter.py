"""Chèn ảnh vào HTML bài viết — gần H2/H3, kèm ALT/caption/metadata."""

from __future__ import annotations

import re
from html import escape, unescape
from typing import Any


def _strip_html_text(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(s)).strip()


_PLACEHOLDER_SRC_RE = re.compile(
    r"^(?:#|about:blank|javascript:|data:image/svg\+xml|placeholder)(?:\b|$)",
    re.I,
)


def is_valid_image_src(src: str) -> bool:
    """True khi src là URL ảnh thật (không phải placeholder LLM)."""
    from app.services.content_ai_image_guard import is_usable_image_src

    return is_usable_image_src(src)


def strip_placeholder_figures(html: str) -> str:
    """Xóa figure/img placeholder hoặc URL LLM bịa — để chèn ảnh thật theo ngữ cảnh."""
    if not html:
        return html
    from app.services.content_ai_image_guard import is_llm_hallucinated_external_src, is_stored_image_src

    def _fig_repl(m: re.Match[str]) -> str:
        block = m.group(0)
        src_m = re.search(r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']*)["']""", block, flags=re.I)
        if src_m:
            src = src_m.group(1)
            if is_stored_image_src(src):
                return block
            if is_valid_image_src(src) and not is_llm_hallucinated_external_src(src):
                return block
        return ""

    out = re.sub(r"<figure\b[^>]*>.*?</figure>", _fig_repl, html, flags=re.I | re.S)
    out = re.sub(
        r"""<img\b(?=[^>]*\bsrc\s*=\s*["']\s*["'])[^>]*/?\s*>""",
        "",
        out,
        flags=re.I,
    )
    out = re.sub(
        r"<img\b(?![^>]*\bsrc\s*=)[^>]*/?\s*>",
        "",
        out,
        flags=re.I,
    )
    return out


def extract_headings(html: str, outline: str = "") -> list[dict[str, Any]]:
    """Trả danh sách {level, text, index_h2} cho h2/h3."""
    out: list[dict[str, Any]] = []
    h2_idx = -1
    for m in re.finditer(r"<(h[23])\b[^>]*>(.*?)</\1>", html or "", flags=re.I | re.S):
        level = m.group(1).lower()
        text = _strip_html_text(m.group(2))
        if not text:
            continue
        if level == "h2":
            h2_idx += 1
        out.append({"level": level, "text": text, "h2_index": max(0, h2_idx)})
    if not out and outline:
        for m in re.finditer(r"^##\s+(.+?)\s*$", outline, flags=re.M):
            h2_idx += 1
            out.append({"level": "h2", "text": m.group(1).strip(), "h2_index": h2_idx})
    return out[:12]


def extract_h2_headings(html: str, outline: str = "") -> list[str]:
    return [h["text"] for h in extract_headings(html, outline) if h["level"] == "h2"]


def prepare_content_html_for_images(content: str, outline: str = "") -> str:
    html = strip_placeholder_figures(str(content or "").strip())
    if not html:
        return html
    if not re.search(r"<\s*[a-z][^>]*>", html, flags=re.I):
        blocks = [b.strip() for b in re.split(r"\n{2,}", html) if b.strip()]
        parts: list[str] = []
        for b in blocks:
            if re.match(r"^#{1,6}\s+", b):
                hm = re.match(r"^(#+)", b)
                level = len(hm.group(1)) if hm else 2
                text = re.sub(r"^#+\s*", "", b).strip()
                tag = "h2" if level <= 2 else "h3"
                parts.append(f"<{tag}>{escape(text)}</{tag}>")
            elif re.match(r"^[-*]\s+", b):
                items = re.findall(r"^[-*]\s+(.+)$", b, flags=re.M)
                lis = "".join(f"<li>{escape(x)}</li>" for x in items)
                parts.append(f"<ul>{lis}</ul>")
            else:
                parts.append(f"<p>{escape(b)}</p>")
        html = "\n".join(parts)
    if not re.search(r"<h2\b", html, flags=re.I):
        html = re.sub(
            r"^##\s+(.+?)\s*$",
            lambda m: f"<h2>{escape(m.group(1).strip())}</h2>",
            html,
            flags=re.M,
        )
    return html


def _paragraph_end_positions(html: str) -> list[int]:
    return [m.end() for m in re.finditer(r"</p>", html, flags=re.I)]


def build_figure_html(
    *,
    url: str,
    alt: str,
    caption: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    from app.services.content_ai_image_guard import validate_image_url_for_insert

    safe_url = validate_image_url_for_insert(url, source="build_figure", probe_remote=False)
    alt_esc = escape(str(alt or "").strip()[:200])
    cap = str(caption or "").strip()[:220]
    cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
    attrs = []
    m = meta or {}
    if m.get("source_url"):
        attrs.append(f'data-source-url="{escape(str(m["source_url"])[:500])}"')
    if m.get("license"):
        attrs.append(f'data-license="{escape(str(m["license"])[:120])}"')
    if m.get("author"):
        attrs.append(f'data-author="{escape(str(m["author"])[:120])}"')
    if m.get("provider"):
        attrs.append(f'data-provider="{escape(str(m["provider"])[:40])}"')
    if m.get("filename"):
        attrs.append(f'data-filename="{escape(str(m["filename"])[:120])}"')
    extra = (" " + " ".join(attrs)) if attrs else ""
    return (
        f'<figure class="editor-image content-ai-inline-image"{extra}>'
        f'<img src="{escape(safe_url)}" alt="{alt_esc}" loading="lazy" style="max-width:100%;height:auto;" />{cap_html}</figure>'
    )


def inject_images_into_content_html(html: str, inserts: list[dict[str, Any]]) -> str:
    """Chèn figure sau H2/H3 hoặc sau đoạn văn; tránh dồn nếu đã có img gần đó."""
    if not html or not inserts:
        return html
    h2_matches = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html, flags=re.I | re.S))
    h3_matches = list(re.finditer(r"<h3\b[^>]*>.*?</h3>", html, flags=re.I | re.S))
    para_ends = _paragraph_end_positions(html)

    ordered = sorted(
        inserts,
        key=lambda x: (
            -int(x.get("h3_index") if x.get("h3_index") is not None else -1),
            -int(x.get("h2_index") if x.get("h2_index") is not None else -1),
            -int(x.get("paragraph_index") if x.get("paragraph_index") is not None else -1),
        ),
    )

    for ins in ordered:
        url = str(ins.get("url") or "").strip()
        if not url or not is_valid_image_src(url):
            continue
        force = bool(ins.get("force") or ins.get("force_heading") or ins.get("user_pick"))
        # Skip exact duplicate of the same image URL
        base_url = url.split("?", 1)[0]
        if base_url and (base_url in html or url in html):
            continue
        pos = -1
        if ins.get("h3_index") is not None and h3_matches:
            idx = int(ins["h3_index"])
            if 0 <= idx < len(h3_matches):
                pos = h3_matches[idx].end()
        elif ins.get("h2_index") is not None and h2_matches:
            idx = int(ins["h2_index"])
            if 0 <= idx < len(h2_matches):
                pos = h2_matches[idx].end()
        elif ins.get("paragraph_index") is not None and para_ends:
            pi = int(ins["paragraph_index"])
            if 0 <= pi < len(para_ends):
                pos = para_ends[pi]
        if pos < 0:
            continue
        window = html[pos : pos + 700]
        if not force and re.search(r"<img\b", window, flags=re.I):
            from app.services.content_ai_image_guard import is_stored_image_src

            has_stored = False
            for sm in re.finditer(
                r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']*)["']""",
                window,
                flags=re.I,
            ):
                if is_stored_image_src(sm.group(1)):
                    has_stored = True
                    break
            if has_stored:
                continue
        fig = build_figure_html(
            url=url,
            alt=str(ins.get("alt") or ""),
            caption=str(ins.get("caption") or ""),
            meta=ins.get("meta") if isinstance(ins.get("meta"), dict) else None,
        )
        html = html[:pos] + fig + html[pos:]
        # Refresh heading match positions after mutation
        h2_matches = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", html, flags=re.I | re.S))
        h3_matches = list(re.finditer(r"<h3\b[^>]*>.*?</h3>", html, flags=re.I | re.S))
        para_ends = _paragraph_end_positions(html)
    return html


def count_content_images(html: str) -> int:
    from app.services.content_ai_image_guard import is_stored_image_src

    n = 0
    for m in re.finditer(r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']*)["']""", html or "", flags=re.I):
        if is_stored_image_src(m.group(1)):
            n += 1
    return n
