"""Tests for Content AI output post-processing (related box + phone dedup)."""

from __future__ import annotations

import re

import pytest

from app.services.content_ai_output_postprocess import (
    dedupe_hotline_phones,
    dedupe_related_articles_boxes,
    has_related_articles_box,
    postprocess_content_ai_output,
)

_RELATED_BOX_RE = re.compile(r"<blockquote[^>]*>.*?bài\s*liên\s*quan", re.I | re.S)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84|0)[\s.\-]*(?:3|5|7|8|9)[\s.\-]*(?:\d[\s.\-]*){8}(?!\d)",
    re.I,
)


def _count_related_boxes(html: str) -> int:
    return len(_RELATED_BOX_RE.findall(html))


def _phones(html: str) -> list[str]:
    from app.services.content_ai_output_postprocess import _normalize_phone

    return [_normalize_phone(m.group(0)) for m in _PHONE_RE.finditer(html)]


def _phone_occurrences(html: str, phone: str) -> int:
    from app.services.content_ai_output_postprocess import _normalize_phone

    norm = _normalize_phone(phone)
    return sum(1 for p in _phones(html) if p == norm)


@pytest.fixture()
def duplicate_related_html() -> str:
    box = (
        '<blockquote><strong>Bài liên quan:</strong> '
        '<a href="https://site.vn/a">Bài A</a> · '
        '<a href="https://site.vn/b">Bài B</a>.</blockquote>'
    )
    return f"<h1>Test</h1><p>Intro</p>{box}{box}<h2>FAQ</h2><p>Q?</p>"


ARTICLE_FIXTURES = [
    (
        "dup_blockquote_same_links",
        (
            "<p>Mở đầu</p>"
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/1">One</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/1">One</a></blockquote>'
        ),
    ),
    (
        "dup_blockquote_diff_links",
        (
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/a">A</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/b">B</a></blockquote>'
        ),
    ),
    (
        "h2_section_plus_blockquote",
        (
            "<h2>Bài liên quan</h2><ul><li><a href='https://ex.com/x'>X</a></li></ul>"
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/y">Y</a></blockquote>'
        ),
    ),
    (
        "triple_related_boxes",
        (
            '<blockquote><strong>Bài liên quan:</strong> <a href="https://ex.com/1">1</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> <a href="https://ex.com/2">2</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> <a href="https://ex.com/3">3</a></blockquote>'
        ),
    ),
    (
        "single_related_ok",
        (
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/only">Only</a></blockquote>'
        ),
    ),
    (
        "no_related_box",
        "<h1>Bài viết</h1><p>Không có box liên quan.</p>",
    ),
    (
        "phone_repeat_body_and_cta",
        (
            "<p>Gọi hotline 0976086500 để tư vấn.</p>"
            "<p>Chi tiết dịch vụ...</p>"
            "<h2>Liên hệ</h2><p>Hotline: 0976 086 500</p>"
        ),
    ),
    (
        "phone_two_numbers",
        (
            "<p>SĐT 0934077360 hỗ trợ.</p>"
            "<p>Hotline phụ 0971050924.</p>"
            "<p>Liên hệ 0934.077.360 cuối bài.</p>"
        ),
    ),
    (
        "phone_tel_links",
        (
            '<p><a href="tel:0976086500">Gọi</a></p>'
            "<p>Nội dung</p>"
            '<p><a href="tel:0976086500">Hotline</a></p>'
        ),
    ),
    (
        "mixed_content_preserve",
        (
            "<h2>Giới thiệu</h2><p>Nội dung SEO giữ nguyên cấu trúc.</p>"
            '<blockquote><strong>Bài liên quan:</strong> <a href="https://ex.com/a">A</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> <a href="https://ex.com/a">A</a></blockquote>'
            "<p>Gọi 0976086500 sớm.</p><p>CTA: 0976086500</p>"
        ),
    ),
    (
        "related_title_dedupe",
        (
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/same">Same Title</a></blockquote>'
            '<blockquote><strong>Bài liên quan:</strong> '
            '<a href="https://ex.com/same/">Same Title</a></blockquote>'
        ),
    ),
]


@pytest.mark.parametrize("name,html", ARTICLE_FIXTURES)
def test_postprocess_gates_on_fixtures(name: str, html: str) -> None:
    out = postprocess_content_ai_output(html)
    related_count = _count_related_boxes(out)
    if "related" in name or "blockquote" in name or "mixed" in name:
        if name == "no_related_box":
            assert related_count == 0
        elif name == "single_related_ok":
            assert related_count == 1
        else:
            assert related_count <= 1, f"{name}: expected <=1 related box, got {related_count}"

    for phone in ("0976086500", "0934077360", "0971050924"):
        if phone.replace("0", "", 1)[:3] in html or phone in html:
            assert _phone_occurrences(out, phone) <= 1, f"{name}: phone {phone} duplicated"

    assert "<h2>Giới thiệu</h2>" in out or "Giới thiệu" not in html
    assert "Nội dung SEO" in out or "Nội dung SEO" not in html


def test_dedupe_related_merges_unique_links(duplicate_related_html: str) -> None:
    out = dedupe_related_articles_boxes(duplicate_related_html)
    assert _count_related_boxes(out) == 1
    assert "site.vn/a" in out
    assert "site.vn/b" in out


def test_has_related_articles_box() -> None:
    assert has_related_articles_box('<blockquote><strong>Bài liên quan:</strong></blockquote>')
    assert not has_related_articles_box("<p>hello</p>")


def test_phone_keeps_last_occurrence() -> None:
    html = "<p>Call 0976086500 now.</p><p>End 0976 086 500.</p>"
    out = dedupe_hotline_phones(html)
    assert _phone_occurrences(out, "0976086500") == 1
    assert "End" in out
    assert "0976086500" in out or "0976 086 500" in out


def test_regression_gates() -> None:
    passed_related = 0
    passed_phone = 0
    for name, html in ARTICLE_FIXTURES:
        out = postprocess_content_ai_output(html)
        if name != "no_related_box":
            if _count_related_boxes(out) <= 1:
                passed_related += 1
        else:
            passed_related += 1
        phones_ok = True
        for m in _PHONE_RE.finditer(html):
            norm_phones = _phones(out)
            from collections import Counter

            counts = Counter(norm_phones)
            if any(v > 1 for v in counts.values()):
                phones_ok = False
        if phones_ok:
            passed_phone += 1
    assert passed_related >= 10
    assert passed_phone >= 10
