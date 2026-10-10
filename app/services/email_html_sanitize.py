"""Sanitize marketing HTML and validate link/image URLs (XSS-safe)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "a",
        "img",
        "h1",
        "h2",
        "h3",
        "h4",
        "ul",
        "ol",
        "li",
        "span",
        "div",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "blockquote",
        "hr",
        "pre",
        "code",
    }
)
VOID_TAGS = frozenset({"br", "img", "hr"})
ALLOWED_ATTRS = {
    "a": frozenset({"href", "title", "target", "rel", "style"}),
    "img": frozenset({"src", "alt", "width", "height", "style"}),
    "td": frozenset({"colspan", "rowspan", "style", "align"}),
    "th": frozenset({"colspan", "rowspan", "style", "align"}),
    "table": frozenset({"style", "width", "cellpadding", "cellspacing", "border"}),
    "*": frozenset({"style", "align"}),
}

_PLACEHOLDER_RE = re.compile(r"^\{\{[a-z_][a-z0-9_]*\}\}$", re.I)
_SAFE_STYLE_RE = re.compile(r"^(?:[a-z\-]+\s*:\s*[^;{}]+;?\s*)+$", re.I)
_DANGEROUS_STYLE = re.compile(r"expression|javascript|url\s*\(\s*['\"]?\s*javascript", re.I)
_STRIP_BLOCKS = re.compile(r"(?is)<(script|style|iframe|object|embed)[^>]*>.*?</\1>")


def is_safe_http_url(raw: str, *, allow_relative: bool = True) -> bool:
    value = str(raw or "").strip()
    if not value:
        return False
    if _PLACEHOLDER_RE.match(value):
        return True
    if value.startswith("mailto:") and "@" in value:
        rest = value[7:]
        return "\n" not in rest and "javascript:" not in rest.lower()
    if allow_relative and value.startswith("/") and not value.startswith("//"):
        return "javascript:" not in value.lower()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    return True


def validate_link_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not is_safe_http_url(value, allow_relative=True):
        raise ValueError("URL không hợp lệ. Chỉ chấp nhận http(s), mailto, path nội bộ hoặc {{placeholder}}.")
    return value


def validate_image_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not is_safe_http_url(value, allow_relative=True):
        raise ValueError("URL ảnh không hợp lệ. Chỉ chấp nhận http(s) hoặc path /static/...")
    if value.startswith("mailto:"):
        raise ValueError("URL ảnh không được dùng mailto.")
    return value


def _fmt_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    allowed = ALLOWED_ATTRS.get(tag, ALLOWED_ATTRS["*"]) | ALLOWED_ATTRS["*"]
    parts: list[str] = []
    has_target = False
    for key, val in attrs:
        k = str(key or "").lower()
        if k.startswith("on") or k in {"srcset", "srcdoc"}:
            continue
        if k not in allowed:
            continue
        raw = "" if val is None else str(val)
        if k in {"href", "src"}:
            if not is_safe_http_url(raw, allow_relative=True):
                continue
            if tag == "img" and raw.lower().startswith("mailto:"):
                continue
        if k == "style":
            if not _SAFE_STYLE_RE.match(raw) or _DANGEROUS_STYLE.search(raw):
                continue
        if k == "target":
            if raw not in {"_blank", "_self"}:
                continue
            has_target = True
        parts.append(f'{k}="{html.escape(raw, quote=True)}"')
    if tag == "a" and has_target and not any(p.startswith("rel=") for p in parts):
        parts.append('rel="noopener noreferrer"')
    return (" " + " ".join(parts)) if parts else ""


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag not in ALLOWED_TAGS:
            if tag not in VOID_TAGS:
                self._skip_depth += 1
            return
        attr_s = _fmt_attrs(tag, attrs)
        if tag in VOID_TAGS:
            self._out.append(f"<{tag}{attr_s} />")
            return
        self._stack.append(tag)
        self._out.append(f"<{tag}{attr_s}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag not in ALLOWED_TAGS:
            return
        self._out.append(f"<{tag}{_fmt_attrs(tag, attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag not in VOID_TAGS:
                self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in VOID_TAGS or tag not in ALLOWED_TAGS:
            return
        if tag in self._stack:
            while self._stack:
                last = self._stack.pop()
                self._out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        self._out.append(html.escape(data, quote=False))

    def close(self) -> str:
        super().close()
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out)


def sanitize_email_html(raw: str) -> str:
    cleaned = _STRIP_BLOCKS.sub("", str(raw or ""))
    parser = _Sanitizer()
    try:
        parser.feed(cleaned)
        return parser.close().strip()
    except Exception:
        return html.escape(re.sub(r"<[^>]+>", "", cleaned))


def html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", str(raw_html or ""))
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r" {2,}", " ", text).strip()


def unsubscribe_footer_html(unsub_url: str) -> str:
    href = html.escape(unsub_url or "#", quote=True)
    return (
        '<p style="margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;'
        'color:#6b7280;font-size:12px;line-height:1.5;">'
        "Bạn nhận email này vì đang dùng SEOAuto.vn. "
        f'<a href="{href}" style="color:#6b7280;text-decoration:underline;">Huỷ đăng ký nhận email</a>.'
        "</p>"
    )


def unsubscribe_footer_text(unsub_url: str) -> str:
    return f"\n\nHuỷ đăng ký: {unsub_url}\n"
