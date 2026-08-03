from __future__ import annotations

from app.services.llm_content_writer import (
    assess_content_word_count,
    content_word_count_bounds,
    resolve_wc_for_content,
)
from app.services.seo_content_prompt import build_content_html_instructions


def test_resolve_wc_for_content_uses_user_value() -> None:
    assert resolve_wc_for_content(1500) == 1500
    assert resolve_wc_for_content(2000) == 2000
    assert resolve_wc_for_content(None) == 1000


def test_content_word_count_bounds_plus_minus_10_percent() -> None:
    lo, hi = content_word_count_bounds(1000)
    assert lo == 900
    assert hi == 1100


def test_assess_content_word_count_ok_in_range() -> None:
    html = "<h1>Test</h1>" + ("<p>word " * 950 + "</p>")
    stats = assess_content_word_count(html, 1000)
    assert stats["word_count_target"] == 1000
    assert stats["word_count_ok"] is True


def test_build_content_html_instructions_word_count_tolerance() -> None:
    out = build_content_html_instructions(
        primary_keyword="dịch vụ seo",
        target_word_count=1000,
        llm_mode="auto",
        user_outline_present=False,
    )
    assert "±10%" in out
    assert "900" in out
    assert "1100" in out
