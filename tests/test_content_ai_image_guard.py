"""Tests for Content AI image URL guard."""

from __future__ import annotations

from unittest.mock import patch

from app.services.content_ai_image_guard import (
    is_llm_hallucinated_external_src,
    is_stored_image_src,
    is_usable_image_src,
    looks_like_text_not_url,
    repair_content_html_images,
    sanitize_content_html_images,
    validate_image_url_for_insert,
)
from app.services.content_ai_image_inserter import (
    build_figure_html,
    count_content_images,
    strip_placeholder_figures,
)


def test_rejects_alt_text_as_src():
    bad = "Dịch vụ sửa máy tính tại Thủ Đức"
    assert looks_like_text_not_url(bad) is True
    assert is_usable_image_src(bad) is False


def test_accepts_https_and_static():
    assert is_usable_image_src("https://example.com/a.jpg") is True
    assert is_usable_image_src("/static/uploads/content-ai/test.webp") is True


def test_sanitize_removes_broken_img():
    html = (
        '<h2>Test</h2><p>Intro</p>'
        '<figure><img src="Dịch vụ sửa máy tính tại Thủ Đức" alt="x"></figure>'
        '<figure><img src="" alt="empty"></figure>'
        '<figure><img src="https://example.com/ok.jpg" alt="OK"></figure>'
    )
    out = sanitize_content_html_images(html, source="test")
    assert "Dịch vụ sửa máy tính" not in out
    assert 'src=""' not in out
    assert "https://example.com/ok.jpg" in out


def test_strip_placeholder_figures():
    html = '<h2>A</h2><figure><img alt="x" src="" /></figure><p>Text</p>'
    cleaned = strip_placeholder_figures(html)
    assert "<img" not in cleaned or 'src=""' not in cleaned


def test_build_figure_rejects_invalid_url():
    try:
        build_figure_html(url="caption only text here", alt="alt")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_validate_insert_keeps_user_files_off_customer_website():
    """Regression: target_website must not rewrite /api/user-files → customer domain."""
    url = "/api/user-files/1/content-ai/general/google-image-abc.jpg"
    out = validate_image_url_for_insert(
        url,
        source="test",
        site_base="https://itsieuviet.com",
        probe_remote=True,
    )
    assert out == url
    assert "itsieuviet.com" not in out

    rewritten_bad = "https://itsieuviet.com/api/user-files/1/content-ai/general/google-image-abc.jpg"
    out2 = validate_image_url_for_insert(
        rewritten_bad,
        source="test",
        site_base="https://itsieuviet.com",
        probe_remote=True,
    )
    assert out2 == "/api/user-files/1/content-ai/general/google-image-abc.jpg"


def test_normalize_never_prefixes_app_media():
    from app.services.content_ai_image_guard import normalize_content_image_src, rehydrate_app_media_src

    assert (
        normalize_content_image_src(
            "/api/user-files/1/a.jpg", site_base="https://itsieuviet.com"
        )
        == "/api/user-files/1/a.jpg"
    )
    assert (
        rehydrate_app_media_src("https://itsieuviet.com/api/user-files/1/a.jpg?token=x")
        == "/api/user-files/1/a.jpg"
    )


def test_sanitize_adds_lazy_and_alt():
    html = '<img src="https://cdn.example.com/pic.png">'
    out = sanitize_content_html_images(html, source="test")
    assert 'loading="lazy"' in out
    assert "alt=" in out


def test_llm_external_detection():
    assert is_llm_hallucinated_external_src("https://itsieuviet.com/images/fake.jpg") is True
    assert is_llm_hallucinated_external_src("/static/uploads/content-ai/x.jpg") is False
    assert is_stored_image_src("/static/uploads/content-ai/x.jpg") is True


def test_repair_strips_llm_hallucinated_urls():
    html = (
        '<h2>Test</h2>'
        '<figure><img src="https://itsieuviet.com/images/sua-may-tinh.jpg" alt="x"></figure>'
        '<figure><img src="/static/uploads/content-ai/real.jpg" alt="OK"></figure>'
    )
    out = repair_content_html_images(html, source="test", probe_remote=False)
    assert "itsieuviet.com" not in out
    assert "/static/uploads/content-ai/real.jpg" in out


def test_strip_placeholder_removes_llm_external():
    html = (
        '<h2>A</h2>'
        '<figure><img alt="x" src="https://example.com/fake.jpg" /></figure>'
        '<figure><img alt="y" src="/static/uploads/content-ai/ok.jpg" /></figure>'
    )
    cleaned = strip_placeholder_figures(html)
    assert "example.com/fake" not in cleaned
    assert "/static/uploads/content-ai/ok.jpg" in cleaned


def test_count_only_stored_images():
    html = (
        '<img src="https://itsieuviet.com/x.jpg">'
        '<img src="/static/uploads/content-ai/a.jpg">'
        '<img src="">'
    )
    assert count_content_images(html) == 1
