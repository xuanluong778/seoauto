"""Tests for CAU assistant structured patches (Auto Update only)."""

from __future__ import annotations

from app.services.cau_assistant_generate import generate_refresh_patches, generate_template_patch
from app.services.cau_assistant_patches import apply_patch, build_refresh_plan, undo_all_patches, undo_patch
from app.services.cau_block_model import parse_blocks, serialize_blocks


SAMPLE = (
    "<!-- wp:heading -->\n"
    "<h2>Gioi thieu san pham</h2>\n"
    "<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n"
    '<p>Doan mo dau co <a href="/a">link noi bo</a> va '
    '<img src="/x.png" alt="demo"> anh.</p>\n'
    "<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n"
    "<h2>Huong dan dung</h2>\n"
    "<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n"
    "<p>Noi dung huong dan chi tiet.</p>\n"
    "<!-- /wp:paragraph -->"
)


def _first_heading(blocks):
    for b in blocks:
        if b.block_type == "heading":
            return b
    raise AssertionError("no heading")


def test_expand_does_not_overwrite_heading():
    blocks = parse_blocks(SAMPLE)
    heading = _first_heading(blocks)
    old_heading = heading.current_content
    patch = generate_template_patch(
        action="expand_1_2",
        blocks=blocks,
        target_block_id=heading.block_id,
        keyword="may in",
    )
    new_blocks, updated, err = apply_patch(blocks, patch)
    assert err is None
    assert updated.status == "applied"
    h = next(b for b in new_blocks if b.block_id == heading.block_id)
    assert h.current_content == old_heading
    assert len(new_blocks) > len(blocks)
    html = serialize_blocks(new_blocks)
    assert "Gioi thieu san pham" in html
    assert "may in" in html.lower()


def test_locked_block_skipped():
    blocks = parse_blocks(SAMPLE)
    heading = _first_heading(blocks)
    heading.locked = True
    try:
        generate_template_patch(
            action="expand_1_2",
            blocks=blocks,
            target_block_id=heading.block_id,
            keyword="kw",
        )
        raised = False
    except ValueError:
        raised = True
    assert raised

    blocks = parse_blocks(SAMPLE)
    heading = _first_heading(blocks)
    h_idx = next(i for i, b in enumerate(blocks) if b.block_id == heading.block_id)
    blocks[h_idx + 1].locked = True
    try:
        generate_template_patch(
            action="rewrite_heading_sync_section",
            blocks=blocks,
            target_block_id=heading.block_id,
            keyword="kw",
        )
        raised2 = False
    except ValueError as exc:
        raised2 = True
        assert "khoa" in str(exc).lower() or "khóa" in str(exc).lower()
    assert raised2


def test_patch_applies_at_correct_position():
    blocks = parse_blocks(SAMPLE)
    headings = [b for b in blocks if b.block_type == "heading"]
    h2 = headings[1]
    before_ids = [b.block_id for b in blocks]
    patch = generate_template_patch(
        action="add_faq",
        blocks=blocks,
        target_block_id=h2.block_id,
        keyword="may in",
    )
    new_blocks, applied, err = apply_patch(blocks, patch)
    assert err is None
    idx = next(i for i, b in enumerate(new_blocks) if b.block_id == h2.block_id)
    inserted = (applied.meta or {}).get("inserted_block_ids") or []
    assert inserted
    assert new_blocks[idx + 1].block_id == inserted[0]
    assert before_ids[0] in {b.block_id for b in new_blocks}


def test_undo_restores_previous_content():
    blocks = parse_blocks(SAMPLE)
    original = serialize_blocks(blocks)
    heading = _first_heading(blocks)
    patch = generate_template_patch(
        action="expand_3_5",
        blocks=blocks,
        target_block_id=heading.block_id,
        keyword="SEO",
    )
    mid, applied, err = apply_patch(blocks, patch)
    assert err is None
    assert serialize_blocks(mid) != original
    restored, undone, err2 = undo_patch(mid, applied)
    assert err2 is None
    assert undone.status == "undone"
    assert serialize_blocks(restored) == original


def test_preserves_gutenberg_links_images():
    blocks = parse_blocks(SAMPLE)
    html0 = serialize_blocks(blocks)
    assert 'href="/a"' in html0
    assert 'src="/x.png"' in html0
    assert "<!-- wp:paragraph -->" in html0

    heading = _first_heading(blocks)
    patch = generate_template_patch(
        action="expand_100",
        blocks=blocks,
        target_block_id=heading.block_id,
        keyword="demo",
    )
    new_blocks, applied, err = apply_patch(blocks, patch)
    assert err is None
    html1 = serialize_blocks(new_blocks)
    assert 'href="/a"' in html1
    assert 'src="/x.png"' in html1
    assert "<!-- wp:paragraph -->" in html1

    restored, _, err2 = undo_patch(new_blocks, applied)
    assert err2 is None
    assert 'href="/a"' in serialize_blocks(restored)
    assert "<!-- wp:heading -->" in serialize_blocks(restored)


def test_selection_patch_replaces_only_selection():
    blocks = parse_blocks("<p>Alpha <strong>giu</strong> Beta Gamma</p>")
    sel = "<strong>giu</strong>"
    patch = generate_template_patch(
        action="selection_rewrite",
        blocks=blocks,
        target_block_id=blocks[0].block_id,
        selection_html=sel,
        keyword="kw",
    )
    new_blocks, applied, err = apply_patch(blocks, patch)
    assert err is None
    cur = new_blocks[0].current_content
    assert "Alpha" in cur and "Beta" in cur
    restored, _, err2 = undo_patch(new_blocks, applied)
    assert err2 is None
    assert sel in restored[0].current_content


def test_refresh_plan_and_undo_all():
    blocks = parse_blocks(SAMPLE)
    plan = build_refresh_plan(level="light", blocks=blocks, seo_score=55)
    assert plan["credit_max"] > 0
    assert plan["sections_estimated"] >= 1
    assert plan["risk_warning"]
    _plan2, patches = generate_refresh_patches(level="light", blocks=blocks, keyword="kw", seo_score=55)
    assert patches
    cur = blocks
    applied_list = []
    for p in patches:
        cur, ap, err = apply_patch(cur, p)
        assert err is None
        applied_list.append(ap)
    assert serialize_blocks(cur) != serialize_blocks(blocks)
    back, updated = undo_all_patches(cur, applied_list)
    assert all(p.status == "undone" for p in updated)
    assert serialize_blocks(back) == serialize_blocks(blocks)


def test_apply_does_not_set_credit_charged():
    blocks = parse_blocks(SAMPLE)
    heading = _first_heading(blocks)
    patch = generate_template_patch(
        action="add_cta",
        blocks=blocks,
        target_block_id=heading.block_id,
        keyword="kw",
    )
    assert patch.credit_charged == 0
    _nb, applied, err = apply_patch(blocks, patch)
    assert err is None
    assert applied.credit_charged == 0
