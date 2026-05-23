"""Sanitize ảnh bịa từ LLM trong content HTML."""

from app.services.content_ai_content_images import (
    is_valid_content_image_src,
    sanitize_invalid_content_images,
)


def test_fake_src_invalid():
    assert not is_valid_content_image_src("")
    assert not is_valid_content_image_src("#")
    assert not is_valid_content_image_src("placeholder.jpg")
    assert not is_valid_content_image_src("https://example.com/a.jpg")
    assert is_valid_content_image_src("/api/user-files/1/uploads/x.png")
    assert is_valid_content_image_src("/static/uploads/content-ai/x.png")


def test_removes_broken_figure_keeps_caption():
    html = (
        '<figure class="editor-image">'
        '<img src="https://example.com/x.jpg" alt="Dịch vụ sửa máy tính uy tín" />'
        "<figcaption>Dịch vụ sửa máy tính uy tín tại IT Siêu Việt</figcaption>"
        "</figure>"
    )
    out, n = sanitize_invalid_content_images(html)
    assert n >= 1
    assert "<img" not in out.lower()
    assert "IT Siêu Việt" in out


def test_keeps_valid_upload_image():
    url = "/static/uploads/content-ai/abc.png"
    html = f'<figure><img src="{url}" alt="ok" /><figcaption>Chú thích</figcaption></figure>'
    out, n = sanitize_invalid_content_images(html, allowed_urls=[url])
    assert n == 0
    assert url in out
    assert "<img" in out.lower()
