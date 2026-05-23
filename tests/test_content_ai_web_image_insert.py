"""Tests for Content AI web image search and insert."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from app.services.content_ai_image_output import (
    figure_snippet_seo,
    resolve_web_image_dimensions,
    validate_web_image_dimensions,
)
from app.services.content_ai_web_image_insert import (
    build_web_image_search_query,
    insert_web_image_into_content,
    search_web_images_for_content,
    web_image_catalog,
)


def test_web_image_catalog_presets():
    cat = web_image_catalog()
    ids = {p["id"] for p in cat["size_presets"]}
    assert "800x400" in ids
    assert "1200x630" in ids
    assert "1024x576" in ids
    assert "600x600" in ids
    assert len(cat["query_modes"]) >= 4


def test_build_web_image_search_query_modes():
    assert build_web_image_search_query(primary_keyword="kw") == "kw"
    assert build_web_image_search_query(query_mode="title", title="Tiêu đề") == "Tiêu đề"
    assert build_web_image_search_query(custom_query="tùy chỉnh") == "tùy chỉnh"
    q = build_web_image_search_query(
        query_mode="h2",
        h2_heading="Sửa laptop tại nhà",
        primary_keyword="sửa laptop",
    )
    assert "laptop" in q.lower() or "sửa" in q.lower()


def test_validate_web_image_dimensions_bounds():
    assert validate_web_image_dimensions(800, 400) == (800, 400)
    with pytest.raises(ValueError, match="tối thiểu"):
        validate_web_image_dimensions(50, 400)
    with pytest.raises(ValueError, match="tối đa"):
        validate_web_image_dimensions(800, 3000)


def test_resolve_web_image_dimensions_preset_and_custom():
    assert resolve_web_image_dimensions(size_preset="1200x630") == (1200, 630)
    assert resolve_web_image_dimensions(target_width=1024, target_height=576) == (1024, 576)


def test_figure_snippet_seo_has_lazy_and_size_attrs():
    html = figure_snippet_seo(
        "/static/uploads/content-ai/demo.webp",
        "Kỹ thuật viên sửa laptop",
        width=800,
        height=400,
    )
    assert 'loading="lazy"' in html
    assert 'decoding="async"' in html
    assert 'width="800"' in html
    assert 'height="400"' in html
    assert "content-ai-web-image" in html


@patch("app.services.content_ai_web_image_insert.search_web_images")
def test_search_web_images_for_content(mock_search):
    mock_search.return_value = (
        [{"link": "https://example.com/a.jpg", "title": "A"}],
        "bing_images",
    )
    out = search_web_images_for_content(primary_keyword="laptop", num=8)
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["source"] == "bing_images"
    mock_search.assert_called_once()


def test_search_web_images_for_content_requires_query():
    with pytest.raises(ValueError, match="từ khóa"):
        search_web_images_for_content(query_mode="title", title="", primary_keyword="")


def _make_png(w: int = 64, h: int = 48) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (w, h), color=(80, 140, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@patch("app.services.content_ai_web_image_insert.download_remote_image_bytes")
def test_insert_web_image_smart_inline(mock_dl, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "static" / "uploads" / "content-ai").mkdir(parents=True)
    mock_dl.return_value = _make_png(400, 300)

    html = """
    <h2>Giới thiệu</h2><p>Đoạn văn đủ dài cho minh họa SEO blog chuyên nghiệp tại nhà.</p>
    <h2>Dịch vụ sửa laptop</h2><p>Mô tả dịch vụ sửa laptop tại nhà quận 7 chi tiết.</p>
    """
    out = insert_web_image_into_content(
        user_id=1,
        remote_url="https://example.com/photo.jpg",
        content_html=html,
        primary_keyword="sửa laptop tại nhà",
        section_heading="Dịch vụ sửa laptop",
        h2_index=1,
        size_preset="800x400",
        download_to_server=True,
    )
    assert out["ok"] is True
    assert "800" in str(out.get("width") or "")
    assert "<img" in out["content"]
    assert 'loading="lazy"' in out["content"]
    assert out["alt"]


def test_template_has_web_image_panel():
    from pathlib import Path

    html = Path("templates/content_ai.html").read_text(encoding="utf-8")
    assert 'id="webImagePanel"' in html
    assert "btnWebImageSearch" in html
    assert "webImageGallery" in html
    assert "Tìm ảnh Google / Web" in html
