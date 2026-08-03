"""CAU «Thêm nội dung» — per-type forms, suggestions, insert position, undo, isolation."""

from __future__ import annotations

import pytest

from app.services import content_backup as backup
from app.services.cau_block_model import parse_blocks, serialize_blocks
from app.services.cau_insert_generate import (
    INSERT_TYPES,
    _body_word_count,
    build_insert_context,
    estimate_insert_credit,
    fit_word_count,
    generate_insert_preview,
    insert_word_target,
    split_service_location,
    suggest_insert,
    validate_internal_url,
)


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    backups = tmp_path / "backups.json"
    sessions = tmp_path / "sessions.json"
    history = tmp_path / "history.json"
    monkeypatch.setattr(backup, "BACKUPS_FILE", backups)
    monkeypatch.setattr(backup, "SESSIONS_FILE", sessions)
    monkeypatch.setattr(backup, "HISTORY_FILE", history)
    backups.write_text("[]", encoding="utf-8")
    sessions.write_text("[]", encoding="utf-8")
    history.write_text("[]", encoding="utf-8")
    yield


SAMPLE = (
    "<!-- wp:heading -->\n<h2>Section A</h2>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Para A with <a href=\"https://mysite.vn/old\">link</a> "
    "and <img src=\"/x.png\" alt=\"x\"></p>\n<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n<h2>Section B</h2>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Para B [gallery ids=\"1\"]</p>\n<!-- /wp:paragraph -->\n"
)


def _ctx(blocks, idx=2, kw="seo local"):
    return build_insert_context(blocks=blocks, insert_index=idx, title="Bai viet", keyword=kw)


# --- 1. Per-type generation (each type has its own output shape) ---

def test_every_insert_type_generates_distinct_form_output():
    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks)
    opts_by_type = {
        "heading": {"title": "Muc moi", "level": 3},
        "paragraph": {"purpose": "example", "length": "short", "tone": "friendly"},
        "cta": {"channel": "zalo", "target": "https://zalo.me/090"},
        "faq": {"items": [{"question": "Gia bao nhieu?", "answer": ""}]},
        "list": {"list_kind": "checklist", "items": ["Buoc 1", "Buoc 2"]},
        "table": {"table_kind": "pricing"},
        "internal_link": {"url": "https://mysite.vn/bai-lien-quan", "anchor": "bai lien quan",
                          "site_base": "https://mysite.vn"},
        "image": {"url": "https://cdn.mysite.vn/a.jpg", "alt": "", "caption": ""},
    }
    assert set(opts_by_type) == set(INSERT_TYPES)
    markers = {
        "heading": "<h3>",
        "paragraph": "<p>",
        "cta": "wp-block-button__link",
        "faq": "<strong>Hỏi:</strong>",
        "list": "<ul>",
        "table": "<table>",
        "internal_link": 'href="https://mysite.vn/bai-lien-quan"',
        "image": "wp-block-image",
    }
    for t, opts in opts_by_type.items():
        p = generate_insert_preview(insert_type=t, options=opts, context=ctx)
        assert p["insert_type"] == t
        assert markers[t] in p["html"], f"{t}: {p['html']}"
        assert p["word_count"] >= (0 if t == "image" else 1)
        assert p["credit_estimate"] >= 0
        assert p["insert_index"] == 2


def test_unknown_type_rejected():
    blocks = parse_blocks(SAMPLE)
    with pytest.raises(ValueError):
        generate_insert_preview(insert_type="video", options={}, context=_ctx(blocks))


# --- 2. AI suggestions for heading and CTA (and FAQ) ---

def test_heading_suggestions_3_to_5_and_no_duplicates_with_existing():
    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks)
    items = suggest_insert(kind="heading", context=ctx, count=5)
    assert 3 <= len(items) <= 5
    titles = [i["title"] for i in items]
    assert len(set(t.lower() for t in titles)) == len(titles)
    for t in titles:
        assert t.lower() not in {"section a", "section b"}


def test_cta_and_faq_suggestions():
    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks)
    ctas = suggest_insert(kind="cta", context=ctx, count=4)
    assert len(ctas) >= 3
    assert all(c.get("title") and c.get("button") for c in ctas)
    channels = {c["channel"] for c in ctas}
    assert {"call", "zalo", "booking", "buy"} & channels
    faqs = suggest_insert(kind="faq", context=ctx, count=5)
    assert 3 <= len(faqs) <= 5
    assert all(f["question"].strip().endswith("?") for f in faqs)


# --- Heading suggestions: đúng dịch vụ + đúng địa phương, không chung chung ---

def test_split_service_location():
    assert split_service_location("sửa macbook quận 10") == ("sửa macbook", "quận 10")
    assert split_service_location("thiết kế web đà nẵng") == ("thiết kế web", "đà nẵng")
    assert split_service_location("sửa điều hòa tại huyện Gia Lâm")[1].lower() == "huyện gia lâm"
    svc, loc = split_service_location("seo onpage")
    assert svc == "seo onpage" and loc == ""


def test_heading_suggestions_local_service_keyword():
    blocks = parse_blocks(SAMPLE)
    ctx = build_insert_context(
        blocks=blocks, insert_index=2,
        title="Sửa MacBook quận 10 uy tín", keyword="sửa macbook quận 10",
    )
    items = suggest_insert(kind="heading", context=ctx, count=5)
    assert 3 <= len(items) <= 5
    for it in items:
        t = it["title"]
        low = t.lower()
        # đúng địa phương + đúng chủ đề
        assert "quận 10" in low, t
        assert "macbook" in low, t
        # không chung chung
        assert "là gì" not in low and "trong thực tế" not in low and "chủ đề" not in low, t
    titles = {i["title"] for i in items}
    assert any("Dịch vụ sửa MacBook tại Quận 10" == t for t in titles)
    assert any("Bảng giá" in t for t in titles)


def test_heading_suggestions_never_duplicate_existing():
    html = (
        "<!-- wp:heading -->\n<h2>Dịch vụ sửa MacBook tại Quận 10</h2>\n<!-- /wp:heading -->\n"
        "<!-- wp:paragraph -->\n<p>Đoạn mở đầu.</p>\n<!-- /wp:paragraph -->\n"
    )
    blocks = parse_blocks(html)
    ctx = build_insert_context(blocks=blocks, insert_index=2, title="T", keyword="sửa macbook quận 10")
    items = suggest_insert(kind="heading", context=ctx, count=5)
    lows = [i["title"].strip().lower() for i in items]
    assert "dịch vụ sửa macbook tại quận 10" not in lows


# --- Word count: backend tự đếm, viết tiếp khi thiếu, rút gọn khi thừa ---

def _fake_chat_factory(calls):
    def chat(system, user, need):
        calls.append(int(need))
        sent = "Nội dung bổ sung về dịch vụ sửa chữa. "  # 7 từ/câu
        n_sent = max(1, round(int(need) / 7))
        return "<p>" + (sent * n_sent).strip() + "</p>"
    return chat


@pytest.mark.parametrize("target", [200, 500, 1000])
def test_fit_word_count_expands_short_content(target):
    short = "<h2>Sửa MacBook Quận 10</h2><p>" + ("Câu mô tả ngắn về dịch vụ này. " * 8).strip() + "</p>"
    assert _body_word_count(short) < target * 0.9  # bắt đầu thiếu từ (vd. 59 từ vs 200)
    calls = []
    out = fit_word_count(short, target, chat=_fake_chat_factory(calls), keyword="sửa macbook quận 10")
    wc = _body_word_count(out)
    assert round(target * 0.9) <= wc <= round(target * 1.1), f"target={target}, got {wc}"
    assert calls, "phải gọi AI viết tiếp khi thiếu từ"
    assert "<h2>" in out  # giữ heading


def test_fit_word_count_trims_long_content():
    long_html = "<h2>Tiêu đề</h2><p>" + ("Một câu đủ dài để đếm được sáu từ. " * 60).strip() + "</p>"
    assert _body_word_count(long_html) > 220
    out = fit_word_count(long_html, 200, chat=None)
    assert _body_word_count(out) <= 220
    assert "<h2>" in out


def test_body_word_count_excludes_heading():
    html = "<h2>Năm từ trong heading này</h2><p>ba từ thôi</p>"
    assert _body_word_count(html) == 3


def test_insert_word_target():
    assert insert_word_target("heading", {"with_content": True, "word_count": 200}) == 200
    assert insert_word_target("heading", {"with_content": False}) is None
    assert insert_word_target("paragraph", {"length": "long"}) == 160
    assert insert_word_target("cta", {}) is None


# --- Context awareness: prev/next headings, existing links ---

def test_context_reads_title_keyword_and_surrounding_sections():
    blocks = parse_blocks(SAMPLE)
    # insert after Section A's paragraph (index 2 = before "Section B" heading)
    ctx = build_insert_context(blocks=blocks, insert_index=2, title="Bai viet", keyword="kw")
    assert ctx["title"] == "Bai viet"
    assert ctx["keyword"] == "kw"
    assert ctx["prev_heading"] == "Section A"
    assert ctx["next_heading"] == "Section B"
    assert "Section A" in ctx["existing_headings"]
    assert "https://mysite.vn/old" in ctx["existing_links"]


def test_duplicate_internal_link_warns():
    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks)
    p = generate_insert_preview(
        insert_type="internal_link",
        options={"url": "https://mysite.vn/old", "anchor": "x", "site_base": "https://mysite.vn"},
        context=ctx,
    )
    assert any("đã có" in w for w in p["warnings"])


# --- Internal link: only real site URLs ---

def test_internal_link_must_be_site_url():
    assert validate_internal_url("https://mysite.vn/bai", "https://mysite.vn")
    assert validate_internal_url("/bai-viet", "https://mysite.vn")
    assert not validate_internal_url("https://other.com/bai", "https://mysite.vn")
    assert not validate_internal_url("javascript:alert(1)", "https://mysite.vn")
    blocks = parse_blocks(SAMPLE)
    with pytest.raises(ValueError):
        generate_insert_preview(
            insert_type="internal_link",
            options={"url": "https://other.com/x", "site_base": "https://mysite.vn"},
            context=_ctx(blocks),
        )


# --- 3. Insert at exact «+» position, no overwrite of old content ---

def test_insert_at_exact_position_no_overwrite():
    from app.services.cau_assistant_patches import build_patch, apply_patch

    blocks = parse_blocks(SAMPLE)
    before_ids = [b.block_id for b in blocks]
    before_html = serialize_blocks(blocks)
    ctx = _ctx(blocks, idx=2)
    prev = generate_insert_preview(
        insert_type="heading", options={"title": "Muc chen", "level": 3}, context=ctx,
    )
    patch = build_patch(
        action="insert_block",
        old_html="",
        new_html=prev["html"],
        insert_index=prev["insert_index"],
        reason="insert",
    )
    out, applied, err = apply_patch(blocks, patch)
    assert err is None
    assert applied.applied
    # inserted exactly at index 2
    inserted_ids = applied.meta["inserted_block_ids"]
    assert [b.block_id for b in out[2:2 + len(inserted_ids)]] == inserted_ids
    # all original blocks intact, in order, contents unchanged
    remaining = [b for b in out if b.block_id in set(before_ids)]
    assert [b.block_id for b in remaining] == before_ids
    for b in remaining:
        orig = next(x for x in blocks if x.block_id == b.block_id)
        assert b.current_content == orig.current_content
    assert "Muc chen" in serialize_blocks(out)
    assert before_html in serialize_blocks(out) or all(
        seg in serialize_blocks(out) for seg in ["Section A", "Section B", "Para A", "Para B"]
    )


def test_insert_at_start_middle_end():
    from app.services.cau_assistant_patches import build_patch, apply_patch

    blocks = parse_blocks(SAMPLE)
    n = len(blocks)
    for idx, marker in ((0, "Dau bai"), (n // 2, "Giua bai"), (n, "Cuoi bai")):
        prev = generate_insert_preview(
            insert_type="heading",
            options={"title": marker, "level": 2},
            context=build_insert_context(blocks=blocks, insert_index=idx, title="T", keyword="kw"),
        )
        patch = build_patch(
            action="insert_block", old_html="", new_html=prev["html"], insert_index=idx,
        )
        out, applied, err = apply_patch(blocks, patch)
        assert err is None, marker
        first_inserted = applied.meta["inserted_block_ids"][0]
        pos = next(i for i, b in enumerate(out) if b.block_id == first_inserted)
        assert pos == idx, f"{marker}: expected index {idx}, got {pos}"
        html = serialize_blocks(out)
        assert marker in html
        for seg in ("Section A", "Section B", "Para A", "Para B"):
            assert seg in html


# --- 4. Preview -> regenerate -> apply -> undo ---

def test_preview_regen_apply_undo_roundtrip():
    from app.services.cau_assistant_patches import build_patch, apply_patch, undo_patch

    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks, idx=1)
    p1 = generate_insert_preview(insert_type="list", options={"list_kind": "steps"}, context=ctx)
    p2 = generate_insert_preview(insert_type="list", options={"list_kind": "benefits"}, context=ctx)
    assert p1["html"] != p2["html"]  # "Tạo lại" with new options yields new preview

    patch = build_patch(action="insert_block", old_html="", new_html=p2["html"], insert_index=1)
    out, applied, err = apply_patch(blocks, patch)
    assert err is None and "<ul>" in serialize_blocks(out)

    undone_blocks, undone, err2 = undo_patch(out, applied)
    assert err2 is None
    assert undone.status == "undone"
    assert serialize_blocks(undone_blocks) == serialize_blocks(blocks)


# --- 5. Gutenberg / shortcode / image / link preserved ---

def test_insert_preserves_gutenberg_shortcode_media():
    from app.services.cau_assistant_patches import build_patch, apply_patch

    blocks = parse_blocks(SAMPLE)
    ctx = _ctx(blocks)
    prev = generate_insert_preview(
        insert_type="image",
        options={"url": "https://cdn.mysite.vn/new.jpg", "alt": "anh moi", "caption": "chú thích"},
        context=ctx,
    )
    patch = build_patch(action="insert_block", old_html="", new_html=prev["html"], insert_index=2)
    out, _, err = apply_patch(blocks, patch)
    assert err is None
    html = serialize_blocks(out)
    assert "<!-- wp:heading -->" in html
    assert "[gallery" in html
    assert 'src="/x.png"' in html
    assert 'href="https://mysite.vn/old"' in html
    assert 'src="https://cdn.mysite.vn/new.jpg"' in html
    assert "<figcaption>" in prev["html"]


# --- 6. Ownership: user A cannot touch user B's session/backup ---

def test_insert_ownership_session_isolation():
    from fastapi import HTTPException
    from app.routers.content_auto_update import _insert_assert_owned

    s = backup.save_session(1, {"site_id": "site-1", "wp_id": 5, "original": {"title": "A"}})
    # owner passes
    _insert_assert_owned(s["id"], "", 1)
    # user B blocked
    with pytest.raises(HTTPException) as exc:
        _insert_assert_owned(s["id"], "", 2)
    assert exc.value.status_code in {403, 404}


# --- Credit: manual = 0; AI estimate scales; charge only via router on LLM success ---

def test_credit_estimates():
    assert estimate_insert_credit("heading", {}) == 5
    assert estimate_insert_credit("heading", {"with_content": True, "word_count": 400}) == 10
    assert estimate_insert_credit("heading", {"with_content": True, "word_count": 2000}) == 25
    assert estimate_insert_credit("internal_link", {}) == 2
    assert estimate_insert_credit("faq", {"items": [{}, {}, {}, {}]}) == 8
    # template preview itself never charges — router charges only after LLM success
    blocks = parse_blocks(SAMPLE)
    p = generate_insert_preview(insert_type="table", options={}, context=_ctx(blocks))
    assert p["source"] == "template"
    assert "credits_charged" not in p  # charging is the router's job, on success only
