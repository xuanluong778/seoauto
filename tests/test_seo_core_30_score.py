"""SEO Core 30 — publish gate & compare."""

from __future__ import annotations

from app.services.seo_core_30_score import (
    build_seo_update_summary,
    compare_seo_scores,
    evaluate_publish_gate,
    factors_not_passed,
    score_seo_core_30,
    seo_factor_counts,
    validate_content_integrity,
)


def _sample_result(score: int, failed_ids: list[str]) -> dict:
    factors = []
    for fid in failed_ids:
        factors.append({
            "id": fid,
            "label": fid,
            "score": 0,
            "max_score": 5,
            "status": "failed",
            "message": "fail",
            "suggestion": "fix",
        })
    factors.append({
        "id": "ok1",
        "label": "OK",
        "score": 5,
        "max_score": 5,
        "status": "passed",
        "message": "",
        "suggestion": "",
    })
    return {"score": score, "factors": factors, "grade_label": "Tốt"}


def test_factors_not_passed():
    r = _sample_result(60, ["a", "b"])
    failed = factors_not_passed(r)
    assert len(failed) == 2
    assert factors_not_passed(r, severe_only=True) == failed


def test_compare_improved_factor():
    before = _sample_result(50, ["kw_title"])
    after = _sample_result(70, [])
    after["factors"] = [
        {
            "id": "kw_title",
            "label": "Keyword in title",
            "score": 5,
            "max_score": 5,
            "status": "passed",
            "message": "",
            "suggestion": "",
        },
        {
            "id": "ok1",
            "label": "OK",
            "score": 5,
            "max_score": 5,
            "status": "passed",
            "message": "",
            "suggestion": "",
        },
    ]
    comp = compare_seo_scores(before, after)
    assert comp["delta"] == 20
    assert comp["improved_factors"]


def test_seo_factor_counts():
    r = score_seo_core_30(
        title="SEO test article",
        content_html="<h2>H</h2><p>" + ("word " * 80) + "</p>",
        primary_keyword="seo",
    )
    counts = seo_factor_counts(r)
    assert counts["total"] >= 20
    assert counts["passed"] + counts["warning"] + counts["failed"] == counts["total"]


def test_build_seo_update_summary():
    comp = {"before_score": 60, "after_score": 72, "delta": 12, "improved_factors": [{"label": "Title"}], "failed_after": []}
    s = build_seo_update_summary(comparison=comp, score_regressed=False)
    assert "72" in s
    assert "cải thiện" in s.lower()


def test_publish_gate_blocks_score_drop():
    before = score_seo_core_30(
        title="SEO test",
        content_html="<h2>Intro</h2><p>Content đủ dài " + ("word " * 80) + "</p>",
        primary_keyword="seo",
    )
    after = dict(before)
    after["score"] = int(before["score"]) - 5
    gate = evaluate_publish_gate(
        backup_id="bk-1",
        seo_before=before,
        seo_after=after,
        old_content="<h2>x</h2><p>" + ("a " * 100) + "</p>",
        new_content="<h2>x</h2><p>" + ("a " * 100) + "</p>",
    )
    assert gate["can_publish_live"] is False
    assert gate["score_regressed"] is True
    assert gate["comparison"]["delta"] < 0


def test_integrity_blocks_empty_content():
    blockers = validate_content_integrity("<h2>x</h2><p>old</p>", "")
    assert any("rỗng" in b.lower() for b in blockers)


def test_build_preview_summary():
    from app.services.content_diff import build_content_diff, build_preview_summary

    diff = build_content_diff(
        old_title="Old",
        new_title="New",
        old_content="<h2>x</h2><p>" + ("word " * 50) + "</p>",
        new_content="<h2>x</h2><p>" + ("word " * 55) + "</p>",
        old_excerpt="",
        new_excerpt="",
    )
    comp = {"before_score": 60, "after_score": 68, "delta": 8, "improved_factors": [], "failed_after": []}
    s = build_preview_summary(diff=diff, comparison=comp, backup_id="bk-1")
    assert s["backup_id"] == "bk-1"
    assert s["word_count"]["old"] > 0


def test_publish_gate_requires_backup():
    before = _sample_result(70, [])
    after = _sample_result(75, [])
    gate = evaluate_publish_gate(
        backup_id=None,
        seo_before=before,
        seo_after=after,
        old_content="<p>" + ("x " * 60) + "</p>",
        new_content="<p>" + ("x " * 60) + "</p>",
    )
    assert gate["can_publish"] is False
