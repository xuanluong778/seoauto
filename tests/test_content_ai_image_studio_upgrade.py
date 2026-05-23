"""Tests for Content AI image studio upgrades (format, size, smart insert, SEO)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.content_ai_content_images import (
    inject_image_smart_into_content_html,
    resolve_smart_inline_h2_index,
)
from app.services.content_ai_image_output import (
    build_seo_image_alt,
    build_seo_image_filename,
    normalize_output_format,
    parse_size_preset,
    process_image_bytes,
    save_content_ai_image,
    validate_dimensions,
)
from app.services.content_ai_image_studio import studio_catalog


def _make_png(w: int = 64, h: int = 48) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (w, h), color=(40, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_normalize_output_format_aliases():
    assert normalize_output_format("jpg") == "jpeg"
    assert normalize_output_format("WEBP") == "webp"
    assert normalize_output_format("png") == "png"


def test_validate_dimensions_bounds():
    assert validate_dimensions(800, 400) == (800, 400)
    with pytest.raises(ValueError, match="tối thiểu"):
        validate_dimensions(100, 400)
    with pytest.raises(ValueError, match="tối đa"):
        validate_dimensions(800, 3000)


def test_parse_size_preset():
    assert parse_size_preset("800x400") == (800, 400)
    assert parse_size_preset("16:9") is None


def test_process_image_bytes_resize_and_webp():
    raw = _make_png(512, 256)
    out, ext, mime = process_image_bytes(raw, output_format="webp", width=800, height=400)
    assert ext == ".webp"
    assert mime == "image/webp"
    from PIL import Image

    img = Image.open(io.BytesIO(out))
    assert img.size == (800, 400)


def test_build_seo_image_filename_and_alt():
    name = build_seo_image_filename(
        "Sửa laptop tại nhà Quận 7",
        section_heading="Dịch vụ tận nơi",
        output_format="webp",
    )
    assert name.endswith(".webp")
    assert " " not in name
    assert "sua-laptop" in name or "quan-7" in name

    alt = build_seo_image_alt(
        primary_keyword="sửa laptop tại nhà Quận 7",
        section_heading="Kỹ thuật viên sửa laptop tại nhà Quận 7",
    )
    assert "laptop" in alt.lower() or "Quận" in alt


def test_save_content_ai_image_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "static" / "uploads" / "content-ai").mkdir(parents=True)
    data = _make_png()
    url = save_content_ai_image(
        data,
        filename="test-seo-banner.webp",
        output_format="webp",
        width=320,
        height=256,
    )
    assert url.startswith("/static/uploads/content-ai/")
    path = tmp_path / "static" / "uploads" / "content-ai" / Path(url).name
    assert path.is_file()
    assert path.suffix == ".webp"


def test_resolve_smart_inline_skips_faq_and_table():
    html = """
    <h2>Giới thiệu</h2><p>Một đoạn đủ dài để chèn ảnh minh họa nội dung bài viết SEO.</p>
    <h2>FAQ — Câu hỏi thường gặp</h2><p>Hỏi đáp.</p>
    <h2>Bảng giá</h2><table><tr><td>x</td></tr></table>
    <h2>Dịch vụ tại Quận 7</h2><p>Nội dung section an toàn cho chèn ảnh minh họa dịch vụ.</p>
    """
    idx, reason = resolve_smart_inline_h2_index(html, preferred_index=1, section_heading="FAQ")
    assert idx != 1
    assert reason in ("h2_smart", "h2_relaxed", "h2_fallback")


def test_inject_image_smart_avoids_faq_block():
    html = """
    <h2>Phần chính</h2><p>Đoạn văn đủ dài cho minh họa SEO blog chuyên nghiệp.</p>
    <h2>FAQ</h2><p>Câu hỏi.</p>
    <h2>Chi tiết dịch vụ</h2><p>Mô tả dịch vụ sửa laptop tại nhà.</p>
    """
    new_html, meta = inject_image_smart_into_content_html(
        html,
        {
            "url": "/static/uploads/content-ai/demo.webp",
            "alt": "Kỹ thuật viên sửa laptop",
            "section_heading": "FAQ",
            "h2_index": 1,
        },
    )
    assert "<img" in new_html
    faq_pos = new_html.lower().find("faq")
    img_pos = new_html.lower().find("<img")
    assert img_pos < faq_pos or "faq" not in new_html[img_pos : img_pos + 200].lower()
    assert meta.get("placement") in ("inline", "append")


def test_studio_catalog_has_formats_and_sizes():
    cat = studio_catalog()
    assert "output_formats" in cat
    assert "size_presets" in cat
    fmt_ids = {x["id"] for x in cat["output_formats"]}
    assert {"png", "jpeg", "webp"}.issubset(fmt_ids)


def test_template_lightbox_has_navigation():
    html = Path("templates/content_ai.html").read_text(encoding="utf-8")
    assert "studioLightboxPrev" in html
    assert "studioLightboxNext" in html
    assert "studioOutputFormat" in html
