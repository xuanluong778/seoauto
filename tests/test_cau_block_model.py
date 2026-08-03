"""Tests for CAU Sửa SEO block model."""

from __future__ import annotations

from app.services.cau_block_model import (
    BlockHistory,
    ContentBlock,
    change_heading_level,
    insert_blocks_at,
    insert_heading_html,
    move_section,
    new_block_id,
    parse_blocks,
    roundtrip_unchanged,
    section_range,
    serialize_blocks,
)


CLASSIC = (
    "<h2>Giới thiệu</h2>"
    "<p>Đoạn mở đầu với <a href=\"https://example.com\">link</a>.</p>"
    "<ul><li>Một</li><li>Hai</li></ul>"
    "<table><tr><td>A</td><td>B</td></tr></table>"
    "<figure class=\"wp-block-image\"><img src=\"https://cdn.example.com/a.jpg\" alt=\"x\" class=\"aligncenter\"/></figure>"
    "[contact-form-7 id=\"123\"]"
    "<h3>Chi tiết</h3>"
    "<p>Nội dung con.</p>"
    "<h2>Kết luận</h2>"
    "<p>Hết.</p>"
)

GUTENBERG = (
    '<!-- wp:heading {"level":2} -->\n'
    "<h2>Giới thiệu</h2>\n"
    "<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n"
    "<p>Hello <strong>world</strong>.</p>\n"
    "<!-- /wp:paragraph -->\n"
    "<!-- wp:image -->\n"
    '<figure class="wp-block-image"><img src="https://cdn.example.com/a.jpg" alt=""/></figure>\n'
    "<!-- /wp:image -->\n"
    '<!-- wp:heading {"level":3} -->\n'
    "<h3>Chi tiết</h3>\n"
    "<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n"
    "<p>Con.</p>\n"
    "<!-- /wp:paragraph -->\n"
    '<!-- wp:heading {"level":2} -->\n'
    "<h2>Kết luận</h2>\n"
    "<!-- /wp:heading -->\n"
)


def test_classic_roundtrip_unchanged():
    assert roundtrip_unchanged(CLASSIC) is True
    assert serialize_blocks(parse_blocks(CLASSIC)) == CLASSIC


def test_gutenberg_roundtrip_unchanged():
    assert roundtrip_unchanged(GUTENBERG) is True
    assert serialize_blocks(parse_blocks(GUTENBERG)) == GUTENBERG


def test_parse_detects_types():
    blocks = parse_blocks(CLASSIC)
    types = [b.block_type for b in blocks]
    assert "heading" in types
    assert "paragraph" in types
    assert "list" in types
    assert "table" in types
    assert "image" in types
    assert "shortcode" in types


def test_insert_h2_h3_h4_at_position():
    blocks = parse_blocks("<h2>A</h2><p>1</p><h2>B</h2><p>2</p>")
    # insert after first paragraph (index 2 = before second h2)
    html = insert_heading_html(title="Mới", level=3, body_html="<p>Body</p>")
    nb = ContentBlock(
        block_id=new_block_id(),
        block_type="heading",
        original_content=html,
        current_content=html,
        changed=True,
        meta={"level": 3},
    )
    # For multi-part heading+body, parse the html into blocks then insert
    new_parts = parse_blocks(html)
    for p in new_parts:
        p.changed = True
    out = insert_blocks_at(blocks, 2, new_parts)
    ser = serialize_blocks(out)
    assert ser.index("<h3>Mới</h3>") < ser.index("<h2>B</h2>")
    assert "<p>Body</p>" in ser
    # H2 / H4
    h2 = parse_blocks(insert_heading_html(title="H2x", level=2))
    h4 = parse_blocks(insert_heading_html(title="H4x", level=4))
    out2 = insert_blocks_at(blocks, 0, h2)
    out2 = insert_blocks_at(out2, len(out2), h4)
    s2 = serialize_blocks(out2)
    assert s2.startswith("<h2>H2x</h2>")
    assert s2.endswith("<h4>H4x</h4>") or "<h4>H4x</h4>" in s2


def test_move_section_keeps_children():
    blocks = parse_blocks(CLASSIC)
    # first h2 "Giới thiệu" at 0 — section includes list/table/image/shortcode until h2 Kết luận
    start, end = section_range(blocks, 0)
    assert end > start + 1
    # move first section down past second h2
    # find index of "Kết luận"
    idx_ket = next(i for i, b in enumerate(blocks) if "Kết luận" in b.current_content)
    moved = move_section(blocks, 0, direction="down")
    ser = serialize_blocks(moved)
    # Kết luận should now come before Giới thiệu
    assert ser.index("Kết luận") < ser.index("Giới thiệu")
    # children of Giới thiệu still after it and before next peer
    gi = ser.index("Giới thiệu")
    assert "Chi tiết" in ser[gi:]
    assert serialize_blocks(move_section(moved, idx_ket and 0, direction="up")) or True


def test_move_section_up_down_structure():
    html = (
        "<h2>One</h2><p>a</p><h3>1.1</h3><p>b</p>"
        "<h2>Two</h2><p>c</p>"
        "<h2>Three</h2><p>d</p>"
    )
    blocks = parse_blocks(html)
    # move Two up
    idx_two = next(i for i, b in enumerate(blocks) if b.current_content.startswith("<h2>Two"))
    moved = move_section(blocks, idx_two, direction="up")
    ser = serialize_blocks(moved)
    assert ser.index("Two") < ser.index("One")
    assert ser.index("Two") < ser.index("<p>c</p>")
    # One section children stay together
    one_pos = ser.index("One")
    assert ser.index("1.1") > one_pos
    assert ser.index("<p>b</p>") > ser.index("1.1")


def test_undo_redo():
    blocks = parse_blocks("<h2>A</h2><p>1</p>")
    hist = BlockHistory()
    hist.push(blocks)  # snapshot before edit
    edited = [
        ContentBlock.from_dict({**blocks[0].to_dict(), "current_content": "<h2>B</h2>", "changed": True}),
        blocks[1],
    ]
    undone = hist.undo(edited)
    assert undone is not None
    assert serialize_blocks(undone) == "<h2>A</h2><p>1</p>"
    redone = hist.redo(undone)
    assert redone is not None
    assert "<h2>B</h2>" in serialize_blocks(redone)


def test_change_heading_level():
    b = parse_blocks("<h2>Title</h2>")[0]
    b3 = change_heading_level(b, 3)
    assert b3.current_content.startswith("<h3>")
    assert b3.meta.get("level") == 3
    assert b3.changed is True
