from __future__ import annotations

from app.services.content_draft_builder import _make_meta_description, build_draft_payload
from app.services.seo_content_prompt import build_llm_field_instructions


def test_build_llm_field_instructions_title_has_length_rule() -> None:
    out = build_llm_field_instructions(field="title", primary_keyword="dịch vụ seo")
    assert "60" in out
    assert "Helpful Content" in out or "E-E-A-T" in out


def test_build_llm_field_instructions_content_has_fifteen_requirements() -> None:
    out = build_llm_field_instructions(
        field="content",
        primary_keyword="audit seo",
        target_word_count=800,
    )
    for needle in ("FAQ", "Schema", "internal", "external", "Checklist SEO", "semantic"):
        assert needle.lower() in out.lower(), needle
    assert "±10%" in out
    assert str(int(800 * 0.90)) in out
    assert str(int(800 * 1.10)) in out


def test_make_meta_description_truncates_over_160() -> None:
    long = "x" * 200
    meta = _make_meta_description(long, "", "Title")
    assert len(meta) <= 160


def test_build_draft_keeps_ld_json_script() -> None:
    html = (
        '<h1>Test</h1><p>Body.</p>'
        '<script type="application/ld+json">{"@context":"https://schema.org"}</script>'
        '<script>alert(1)</script>'
    )
    draft = build_draft_payload(title="SEO test title here for length", content=html)
    assert "application/ld+json" in draft["content"]
    assert "alert(1)" not in draft["content"]
