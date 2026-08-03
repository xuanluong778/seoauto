"""Internal link contextual paragraphs (LLM / rule) — phân bổ đều, validate, fallback."""

from app.services.wp_internal_link_apply import (
    _is_bare_link_paragraph,
    _rule_context_paragraph_inner,
    apply_merged_internal_links,
    norm_url_for_compare,
    url_matches_allowed,
    validate_internal_link_output,
    verify_internal_links_html,
)
from app.services.wp_internal_link_scoring import assign_links_to_paragraphs
from bs4 import BeautifulSoup


def _long_article_html() -> str:
    """~1500 từ, nhiều section — dùng cho test phân bổ 5 link."""
    sections = []
    filler = (
        "Dịch vụ sửa laptop tại nhà cung cấp kỹ thuật viên giàu kinh nghiệm, "
        "linh kiện chính hãng và bảo hành rõ ràng sau sửa chữa. "
        "Khách hàng có thể đặt lịch linh hoạt theo khung giờ buổi sáng hoặc chiều tối. "
    )
    for i in range(1, 9):
        sections.append(f"<h2>Phần {i}: chủ đề dịch vụ khu vực {i}</h2>")
        for j in range(4):
            sections.append(f"<p>{filler} Mục {i}.{j} mô tả quy trình kiểm tra mainboard pin màn hình.</p>")
    sections.append("<h2>Câu hỏi thường gặp</h2>")
    sections.append("<p>Bao lâu thì sửa xong? Thường từ một đến ba giờ tùy hư hỏng.</p>")
    sections.append("<h2>Liên hệ</h2>")
    sections.append("<p>Gọi hotline hoặc Zalo để đặt lịch tư vấn miễn phí ngay hôm nay.</p>")
    return "\n".join(sections)


def _paragraphs_with_internal(soup: BeautifulSoup) -> list:
    return [p for p in soup.find_all("p") if p.find("a", href=True)]


def test_bare_link_paragraph_detected():
    soup = BeautifulSoup(
        '<p><a href="https://ex.com/a">Sửa laptop tại nhà huyện nhà bè</a></p>',
        "html.parser",
    )
    p = soup.find("p")
    assert _is_bare_link_paragraph(p)


def test_rule_context_has_full_sentence():
    inner = _rule_context_paragraph_inner(
        target_url="https://ex.com/a",
        anchor_text="Sửa laptop tại nhà",
        title="Dịch vụ sửa laptop",
        section_heading="Quy trình sửa chữa",
    )
    assert "<a " in inner
    assert "Sửa laptop" in inner
    assert "— Sửa laptop tại nhà" not in inner
    plain = BeautifulSoup(inner, "html.parser").get_text(" ", strip=True)
    assert len(plain) > 40
    assert not _is_bare_link_paragraph(BeautifulSoup(inner, "html.parser").find("p"))


def test_verify_itsieuviet_three_urls_not_false_reject():
    """Regression: 3 URL đã chọn (có/không slash) không bị báo «không nằm trong danh sách»."""
    urls = [
        "https://itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be/",
        "https://itsieuviet.com/sua-laptop-tai-nha-huyen-hoc-mon/",
        "https://itsieuviet.com/cai-phan-mem-may-tinh-online/",
    ]
    jobs = [{"link": u, "title": "t", "anchor_text": "anchor"} for u in urls]
    filler = (
        "Dịch vụ sửa laptop tại nhà với kỹ thuật viên giàu kinh nghiệm và bảo hành rõ ràng. "
    )
    parts = ["<h2>Dịch vụ</h2>"]
    for i, u in enumerate(urls):
        parts.append(
            f"<h2>Phần {i + 2}</h2>"
            f"<p>{filler} Mục {i + 1} mô tả quy trình kiểm tra mainboard pin màn hình.</p>"
            f'<p>{filler} Xem <a href="{u}">anchor {i + 1}</a> trong hệ thống.</p>'
        )
    html = "\n".join(parts)
    v = verify_internal_links_html(html, jobs=jobs, expected_inserts=[{"target_url": u} for u in urls])
    assert not any("danh sách" in str(i).lower() for i in (v.get("issues") or [])), v.get("issues")


def test_verify_ignores_other_same_host_not_selected():
    jobs = [
        {
            "target_url": "https://itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be",
            "anchor_text": "Sửa laptop",
        }
    ]
    html = (
        "<h2>A</h2>"
        "<p>Đoạn mô tả dịch vụ sửa laptop tại nhà đủ dài để chèn link nội bộ hợp lệ trong bài.</p>"
        '<p>Chọn <a href="https://itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be/">Sửa laptop</a>.</p>'
        "<p>Trang chủ <a href=\"https://itsieuviet.com/\">IT Siêu Việt</a> — không thuộc danh sách chọn.</p>"
    )
    v = verify_internal_links_html(html, jobs=jobs)
    assert not any("danh sách" in str(i).lower() for i in (v.get("issues") or [])), v.get("issues")


def test_verify_accepts_selected_urls_with_www_and_slash():
    jobs = [
        {
            "link": "https://itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be",
            "anchor_text": "Sửa laptop tại nhà huyện nhà bè",
        },
    ]
    html = (
        '<h2>Dịch vụ</h2><p>Đoạn mô tả dịch vụ sửa laptop tại nhà đủ dài để chèn link nội bộ hợp lệ.</p>'
        '<p>Khách tại Nhà Bè thường cần <a href="https://www.itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be/">'
        "Sửa laptop tại nhà huyện nhà bè</a> khi máy gặp lỗi phần mềm hoặc phần cứng.</p>"
    )
    allowed = {
        norm_url_for_compare("https://itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be"),
    }
    href_norm = norm_url_for_compare(
        "https://www.itsieuviet.com/sua-laptop-tai-nha-huyen-nha-be/"
    )
    assert url_matches_allowed(href_norm, allowed)
    v = verify_internal_links_html(html, jobs=jobs, expected_inserts=jobs)
    assert v["ok"], v.get("issues")


def test_append_with_rule_inner_not_bare():
    html = """
    <h2>Dịch vụ sửa chữa tại các quận</h2>
    <p>IT Siêu Việt phục vụ nhiều quận trong thành phố.</p>
    <h2>Lợi ích</h2><p>Nội dung lợi ích chi tiết gamma delta.</p>
    """
    out = apply_merged_internal_links(
        content_html=html,
        custom_links=[],
        selected_posts=[
            {
                "link": "https://ex.com/nha-be",
                "anchor_text": "Sửa laptop tại nhà huyện nhà bè",
                "title": "Nhà Bè",
            },
            {
                "link": "https://ex.com/hoc-mon",
                "anchor_text": "Sửa laptop tại nhà huyện hóc môn",
                "title": "Hóc Môn",
            },
        ],
        current_url="",
        use_llm_rewrite=False,
        llm_available=False,
        apply_mode="full",
        confirmed_append_urls=["https://ex.com/nha-be", "https://ex.com/hoc-mon"],
    )
    soup = BeautifulSoup(out["content_html"], "html.parser")
    ref_ps = _paragraphs_with_internal(soup)
    assert len(ref_ps) >= 1
    contextual = [p for p in ref_ps if not _is_bare_link_paragraph(p)]
    assert len(contextual) >= 1


def test_five_links_spread_in_long_article():
    html = _long_article_html()
    jobs = [
        {
            "link": f"https://ex.com/khu-vuc-{i}",
            "anchor_text": f"sửa laptop khu vực {i}",
            "title": f"Dịch vụ sửa laptop khu vực {i}",
        }
        for i in range(1, 6)
    ]
    out = apply_merged_internal_links(
        content_html=html,
        custom_links=[],
        selected_posts=jobs,
        current_url="",
        use_llm_rewrite=False,
        llm_available=False,
        apply_mode="full",
    )
    soup = BeautifulSoup(out["content_html"], "html.parser")
    link_ps = _paragraphs_with_internal(soup)
    assert len(link_ps) >= 4
    for p in link_ps:
        assert len(p.find_all("a", href=True)) == 1
    positions = []
    for p in soup.find_all("p"):
        if p.find("a", href=True):
            positions.append(list(soup.find_all("p")).index(p))
    positions.sort()
    for i in range(1, len(positions)):
        assert positions[i] - positions[i - 1] >= 2, "Hai đoạn link quá sát nhau"
    assert positions[-1] - positions[0] >= 8, "Link bị dồn một cụm"
    val = validate_internal_link_output(
        out["content_html"],
        jobs=jobs,
        allowed_urls={f"https://ex.com/khu-vuc-{i}" for i in range(1, 6)},
        expected_inserts=out.get("updates"),
    )
    assert val["ok"], val.get("issues")


def test_validate_fails_clustered_llm_style_html():
    clustered = """
    <h2>A</h2><p>Đoạn một dài đủ để vượt ngưỡng ký tự tối thiểu cho phép chèn link nội bộ.</p>
    <h2>B</h2><p>Đoạn hai cũng đủ dài để kiểm tra validate phân bổ internal link trong bài.</p>
    <p><a href="https://ex.com/1">anchor một</a> và <a href="https://ex.com/2">anchor hai</a> dồn chung.</p>
    <p><a href="https://ex.com/3">anchor ba</a> tiếp theo ngay sau.</p>
    """
    jobs = [
        {"target_url": "https://ex.com/1", "anchor_text": "anchor một"},
        {"target_url": "https://ex.com/2", "anchor_text": "anchor hai"},
        {"target_url": "https://ex.com/3", "anchor_text": "anchor ba"},
    ]
    val = validate_internal_link_output(
        clustered,
        jobs=jobs,
        allowed_urls={"https://ex.com/1", "https://ex.com/2", "https://ex.com/3"},
    )
    assert not val["ok"]
    assert any(
        "tối đa 1" in i or "dồn" in i or "gần" in i or "internal link" in i.lower()
        for i in val["issues"]
    )


def test_validate_rejects_faq_and_cta_links():
    html = """
    <h2>Nội dung</h2>
    <p>Đoạn thân bài đủ dài mô tả dịch vụ sửa laptop chuyên nghiệp tại nhà cho khách hàng.</p>
    <h2>Câu hỏi thường gặp</h2>
    <p>FAQ: <a href="https://ex.com/faq">Sửa laptop FAQ</a> không được phép.</p>
    <h2>Liên hệ</h2>
    <p>Hotline <a href="https://ex.com/cta">đặt lịch ngay</a> — CTA.</p>
    """
    val = validate_internal_link_output(
        html,
        jobs=[{"target_url": "https://ex.com/faq", "anchor_text": "Sửa laptop FAQ"}],
        allowed_urls={"https://ex.com/faq"},
    )
    assert not val["ok"]


def test_assign_links_spreads_positions():
    paragraphs = [
        {"paragraph_id": i, "position": i, "text": f"Đoạn {i} " + ("sửa laptop tại nhà " * 8), "section_heading": f"H{i}"}
        for i in range(12)
    ]
    jobs = [
        {"target_url": f"https://ex.com/{i}", "anchor_text": f"anchor {i}", "title": f"Bài {i}"}
        for i in range(5)
    ]
    placements = assign_links_to_paragraphs(jobs, paragraphs, min_para_gap=2)
    assert len(placements) == 5
    pos = sorted(int(p["position"]) for p in placements)
    for i in range(1, len(pos)):
        assert pos[i] - pos[i - 1] >= 2


def test_three_links_use_diverse_sentences_not_duplicate_template():
    html = """
    <h2>Sửa máy tính uy tín gần đây</h2>
    <p>Chúng tôi cung cấp dịch vụ sửa chữa tại nhà cho khách hàng ở nhiều khu vực khác nhau, giúp tiết kiệm thời gian và công sức di chuyển.</p>
    <h2>Quy trình sửa chữa chuyên nghiệp</h2>
    <p>Kỹ thuật viên kiểm tra máy tại nhà, báo giá minh bạch và sửa đúng lỗi theo quy trình chuẩn của hãng.</p>
    <h2>Chi phí và bảo hành</h2>
    <p>Bảng giá công khai theo hạng mục, bảo hành có cam kết bằng văn bản sau khi hoàn tất sửa chữa.</p>
    <h2>Khu vực phục vụ</h2>
    <p>Phục vụ nhiều quận huyện với thời gian đặt lịch linh hoạt buổi sáng hoặc chiều tối trong tuần.</p>
    """
    jobs = [
        {"link": "https://ex.com/nha-be", "anchor_text": "sửa laptop nhà bè", "title": "Nhà Bè"},
        {"link": "https://ex.com/hoc-mon", "anchor_text": "sửa laptop hóc môn", "title": "Hóc Môn"},
        {"link": "https://ex.com/q7", "anchor_text": "sửa laptop quận 7", "title": "Quận 7"},
    ]
    out = apply_merged_internal_links(
        content_html=html,
        custom_links=[],
        selected_posts=jobs,
        current_url="",
        use_llm_rewrite=False,
        llm_available=False,
        apply_mode="full",
    )
    soup = BeautifulSoup(out["content_html"], "html.parser")
    texts = [p.get_text(" ", strip=True) for p in soup.find_all("p") if p.find("a")]
    assert len(texts) >= 2
    openings = [t[:40].casefold() for t in texts]
    assert len(set(openings)) == len(openings), f"Trùng câu mở đầu: {openings}"
    assert not any("trong phần «" in t and "bạn có thể đọc thêm" in t for t in texts)


def test_llm_cluster_validate_triggers_rule_fallback(monkeypatch):
    """HTML dồn link phải fail validate; apply vẫn chèn được nhờ rule fallback."""
    html = _long_article_html()
    jobs = [
        {
            "link": f"https://ex.com/r{i}",
            "anchor_text": f"sửa laptop khu vực {i}",
            "title": f"Dịch vụ sửa laptop khu vực {i}",
        }
        for i in range(1, 4)
    ]

    bad_llm = """
    <h2>Phần 1: chủ đề dịch vụ khu vực 1</h2>
    <p>Dịch vụ sửa laptop tại nhà cung cấp kỹ thuật viên giàu kinh nghiệm đủ dài.</p>
    <p><a href="https://ex.com/r1">Sửa laptop khu vực 1</a> <a href="https://ex.com/r2">Sửa laptop khu vực 2</a>
    <a href="https://ex.com/r3">Sửa laptop khu vực 3</a> gom một chỗ.</p>
    """

    def fake_rewrite(**kwargs):
        return bad_llm

    monkeypatch.setattr(
        "app.services.wp_internal_link_apply.rewrite_html_insert_internal_links",
        fake_rewrite,
    )

    out = apply_merged_internal_links(
        content_html=html,
        custom_links=[],
        selected_posts=jobs,
        current_url="",
        use_llm_rewrite=True,
        llm_available=True,
        apply_mode="full",
    )
    assert out["inserted_links"] >= 2
    soup = BeautifulSoup(out["content_html"], "html.parser")
    for p in _paragraphs_with_internal(soup):
        assert len(p.find_all("a", href=True)) <= 1
