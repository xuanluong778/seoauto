"""CAU modal update guard — conflict, validation, ownership isolation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import content_backup as backup
from app.services import content_publish as publish
from app.services.cau_block_model import move_section, parse_blocks, serialize_blocks
from app.services.cau_modal_snapshots import get_modal_snapshot_detail, list_modal_snapshots
from app.services.cau_modal_update_guard import (
    build_change_summary,
    detect_wp_conflict,
    normalize_modified,
    pick_wp_modified,
    resolve_expected_modified,
    validate_modal_content,
    wp_remote_matches_session_baseline,
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
    "<!-- wp:paragraph -->\n<p>Para A with <a href=\"/a\">link</a> "
    "and <img src=\"/x.png\" alt=\"x\"></p>\n<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n<h3>Child A1</h3>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Child body</p>\n<!-- /wp:paragraph -->\n"
    "<!-- wp:heading -->\n<h2>Section B</h2>\n<!-- /wp:heading -->\n"
    "<!-- wp:paragraph -->\n<p>Para B [gallery ids=\"1\"]</p>\n<!-- /wp:paragraph -->\n"
    "<table><tr><td>1</td></tr></table>\n"
    "<iframe src=\"https://example.com/e\"></iframe>\n"
)


def test_insert_h2_h3_position_and_expand_no_overwrite():
    from app.services.cau_assistant_generate import generate_template_patch
    from app.services.cau_assistant_patches import apply_patch

    blocks = parse_blocks(SAMPLE)
    h2 = next(b for b in blocks if b.block_type == "heading" and "Section A" in b.current_content)
    idx = next(i for i, b in enumerate(blocks) if b.block_id == h2.block_id)
    # insert H3 after heading
    from app.services.cau_block_model import ContentBlock, new_block_id

    new_h3 = ContentBlock(
        block_id=new_block_id(),
        block_type="heading",
        original_content="<h3>New H3</h3>",
        current_content="<h3>New H3</h3>",
        changed=True,
    )
    blocks2 = blocks[: idx + 1] + [new_h3] + blocks[idx + 1 :]
    assert "New H3" in serialize_blocks(blocks2)
    assert blocks2[idx].current_content == h2.current_content

    patch = generate_template_patch(
        action="expand_1_2",
        blocks=blocks2,
        target_block_id=h2.block_id,
        keyword="kw",
    )
    out, ap, err = apply_patch(blocks2, patch)
    assert err is None
    assert next(b for b in out if b.block_id == h2.block_id).current_content == h2.current_content
    assert len(out) > len(blocks2)


def test_move_section_keeps_child_heading():
    blocks = parse_blocks(SAMPLE)
    ids_before = [b.block_id for b in blocks]
    # Move first section down past the next section
    moved = move_section(blocks, 0, direction="down")
    html = serialize_blocks(moved)
    assert "Section A" in html and "Child A1" in html and "Section B" in html
    a = html.index("Section A")
    c = html.index("Child A1")
    assert a < c
    assert set(ids_before) == {x.block_id for x in moved}


def test_preserve_media_markup_and_undo_redo_history():
    from copy import deepcopy

    blocks = parse_blocks(SAMPLE)
    html0 = serialize_blocks(blocks)
    assert 'href="/a"' in html0
    assert 'src="/x.png"' in html0
    assert "[gallery" in html0
    assert "<table" in html0
    assert "<iframe" in html0
    assert "<!-- wp:heading -->" in html0

    snapshot = deepcopy(blocks)
    blocks[1].current_content = blocks[1].current_content + "<p>extra</p>"
    blocks[1].changed = True
    # undo = restore snapshot
    restored = deepcopy(snapshot)
    assert 'href="/a"' in serialize_blocks(restored)
    assert serialize_blocks(restored) == html0


def test_validate_empty_and_markup_warnings():
    v = validate_modal_content(title="", content_html="")
    assert not v["ok"]
    v2 = validate_modal_content(
        title="T",
        content_html="<p>ok</p>",
        old_content=SAMPLE,
    )
    assert v2["ok"]
    assert any("img" in w.lower() or "ảnh" in w.lower() or "shortcode" in w.lower() or "wp-block" in w.lower() for w in v2["warnings"])


def test_change_summary_and_conflict():
    s = build_change_summary(
        old_title="Old",
        new_title="New",
        old_content="<h2>A</h2><p>one two</p>",
        new_content="<h2>A</h2><h2>B</h2><p>one two three four</p><a href='/x'>x</a>",
        seo_before={"score": 40},
        seo_after={"score": 55},
        post_status="publish",
        patches=[{"patch_id": "p1"}],
    )
    assert s["seo_before"] == 40 and s["seo_after"] == 55
    assert "B" in s["headings_added"]
    assert s["words_added"] >= 1
    assert s["post_status"] == "publish"
    assert detect_wp_conflict(expected_modified="2024-01-01T10:00:00", remote_modified="2024-01-01T10:00:00") is None
    c = detect_wp_conflict(expected_modified="2024-01-01T10:00:00", remote_modified="2024-01-02T10:00:00")
    assert c and c["conflict"] is True
    assert normalize_modified("2024-01-01T10:00:00Z") == "2024-01-01T10:00:00"
    # Local modified vs remote GMT same instant — must NOT conflict
    assert detect_wp_conflict(
        expected_modified="2026-03-02T18:28:20",
        remote_modified="2026-03-02T11:28:20",
        remote_modified_alt="2026-03-02T18:28:20",
    ) is None
    assert pick_wp_modified({"modified_gmt": "2026-01-01T00:00:00", "modified": "2026-01-01T07:00:00"}) == "2026-01-01T00:00:00"
    assert wp_remote_matches_session_baseline(
        baseline_content="<p>Hello</p>",
        remote_content="<p>Hello</p>",
    )
    # Timestamp differs but WP body unchanged — allow update (local edits only)
    assert detect_wp_conflict(
        expected_modified="2024-01-01T10:00:00",
        remote_modified="2024-01-02T10:00:00",
        baseline_content="<h2>A</h2><p>one two</p>",
        remote_content="<h2>A</h2><p>one two</p>",
    ) is None
    # WP body changed — real conflict
    c2 = detect_wp_conflict(
        expected_modified="2024-01-01T10:00:00",
        remote_modified="2024-01-01T10:00:00",
        baseline_content="<p>old</p>",
        remote_content="<p>new from wp</p>",
    )
    assert c2 and c2["conflict"] is True
    sess = {"wp_modified": "gmt-1", "original": {"modified": "orig-1"}}
    assert resolve_expected_modified(session=sess, client_expected="client-wrong") == "gmt-1"


def test_backup_restore_and_isolation():
    b = backup.create_backup(
        user_id=1,
        session_id="sess-a",
        site_id="site-1",
        wp_id=10,
        post_type="post",
        post_url="https://example.com/p",
        snapshot={
            "old_title": "Old",
            "old_content": SAMPLE,
            "old_excerpt": "Ex",
            "old_status": "publish",
        },
    )
    assert backup.get_backup(b["id"], 1) is not None
    assert backup.get_backup(b["id"], 2) is None  # user B
    assert get_modal_snapshot_detail(b["id"], 2) is None
    items_a = list_modal_snapshots(1, wp_id=10)
    items_b = list_modal_snapshots(2, wp_id=10)
    assert len(items_a) == 1
    assert items_b == []

    # restore requires ownership via get_backup
    monkey_calls = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"status": "publish", "link": "https://example.com/p", "modified": "2024-01-03T00:00:00"}

    def fake_post(url, headers=None, auth=None, json=None, timeout=60):
        monkey_calls["body"] = json
        return _Resp()

    import app.services.content_publish as pub

    pub_mod = pub
    # restore as user 2 must fail
    with pytest.raises(HTTPException) as exc:
        publish.restore_from_backup(user_id=2, backup_id=b["id"])
    assert exc.value.status_code == 404


def test_publish_conflict_blocked_and_preserve_status(monkeypatch):
    b = backup.create_backup(
        user_id=1,
        session_id="sess-1",
        site_id="site-1",
        wp_id=10,
        post_type="post",
        post_url="https://example.com/p",
        snapshot={
            "old_title": "Old",
            "old_content": "Old body",
            "old_excerpt": "Ex",
            "old_status": "private",
        },
    )
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"status": "private", "link": "https://example.com/p", "modified": "2024-02-01T00:00:00"}

    def fake_post(url, headers=None, auth=None, json=None, timeout=60):
        captured["body"] = json
        return _Resp()

    monkeypatch.setattr(publish, "get_site_credentials", lambda site_id, user_id: {
        "url": "https://example.com",
        "username": "u",
        "app_password": "p",
    })
    monkeypatch.setattr(publish.requests, "post", fake_post)

    # conflict detection unit
    assert detect_wp_conflict(expected_modified="t1", remote_modified="t2")["conflict"]

    result = publish.publish_update(
        user_id=1,
        site_id="site-1",
        backup_id=b["id"],
        wp_id=10,
        post_type="post",
        title="New",
        content="Body",
        excerpt="",
        mode="draft",
        preserve_wp_status=True,
        status="private",
    )
    assert captured["body"]["status"] == "private"
    assert "status" in captured["body"]
    assert result["status"] == "private"

    # preserve without explicit status omits status field
    captured.clear()
    publish.publish_update(
        user_id=1,
        site_id="site-1",
        backup_id=b["id"],
        wp_id=10,
        post_type="post",
        title="New2",
        content="Body2",
        excerpt="",
        mode="draft",
        preserve_wp_status=True,
    )
    assert "status" not in captured["body"]


def test_session_isolation():
    s = backup.save_session(1, {"site_id": "s1", "wp_id": 9, "original": {"title": "A"}})
    assert backup.get_session(s["id"], 1) is not None
    assert backup.get_session(s["id"], 2) is None
