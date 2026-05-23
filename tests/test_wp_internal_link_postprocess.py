"""Post-process internal link — template, dedupe, allowed URLs."""

from app.services.wp_internal_link_postprocess import (
    dedupe_internal_links,
    postprocess_internal_links_html,
    remove_template_link_sentences,
    remove_unselected_urls,
    validate_allowed_urls,
)

SELECTED = [
    {
        "target_url": "https://itsieuviet.com/cai-phan-mem-may-tinh-online/",
        "anchor_text": "cài phần mềm máy tính online",
    },
]


def test_remove_template_strips_link_keeps_text():
    html = (
        "<p>Máy tính khởi động chậm. Bạn có thể tham khảo thêm dịch vụ "
        '<a href="https://itsieuviet.com/cai-phan-mem-may-tinh-online/">'
        "cài phần mềm máy tính online</a>.</p>"
    )
    out, n = remove_template_link_sentences(html)
    assert n >= 1
    assert "<a " not in out.lower()
    assert "cài phần mềm máy tính online" in out


def test_remove_unselected_url():
    html = (
        "<p>Đoạn đủ dài mô tả dịch vụ sửa laptop tại nhà với quy trình rõ ràng cho khách.</p>"
        '<p>Link lạ <a href="https://itsieuviet.com/other-page/">khác</a> không chọn.</p>'
        '<p>Link đúng <a href="https://itsieuviet.com/cai-phan-mem-may-tinh-online/">cài PM</a>.</p>'
    )
    out, n = remove_unselected_urls(html, SELECTED)
    assert n >= 1
    assert "other-page" not in out
    assert "cai-phan-mem-may-tinh-online" in out


def test_dedupe_keeps_first_only():
    url = "https://itsieuviet.com/cai-phan-mem-may-tinh-online/"
    html = (
        f'<p>Đoạn một đủ dài mô tả dịch vụ <a href="{url}">a</a>.</p>'
        f'<p>Đoạn hai đủ dài mô tả lại <a href="{url}">b</a>.</p>'
    )
    out, n = dedupe_internal_links(html, SELECTED)
    assert n == 1
    assert out.lower().count("<a ") == 1


def test_postprocess_pipeline_ok():
    good = (
        "<p>Máy tính khởi động chậm có thể do virus hoặc lỗi hệ điều hành; "
        "lúc này, dịch vụ <a href=\"https://itsieuviet.com/cai-phan-mem-may-tinh-online/\">"
        "cài phần mềm máy tính online</a> sẽ phù hợp để kiểm tra và xử lý nhanh.</p>"
    )
    out, stats = postprocess_internal_links_html(good, SELECTED)
    assert "<a " in out.lower()
    assert stats.get("validate_urls", {}).get("ok")
