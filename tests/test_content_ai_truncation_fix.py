"""Regression: Content AI must not cut mid-sentence due to trim / extract / detection gaps."""

from __future__ import annotations

from app.services.content_ai_section_writer import (
    _html_has_incomplete_tail,
    _text_looks_cut_mid_sentence,
    iter_incomplete_paragraph_tails,
)
from app.services.content_draft_builder import extract_clean_html_fragment
from app.services.llm_content_writer import (
    _ANTHROPIC_CONTENT_MAX_TOKENS_CAP,
    _anthropic_max_tokens_for_field,
    _finish_reason_is_length,
    _take_first_words_at_sentence,
    _trim_html_to_max_words,
)


def test_screenshot_style_incomplete_sentences_detected() -> None:
    assert _text_looks_cut_mid_sentence("đáp ứng nhu cầu đa dạng của nhiều đối")
    assert _text_looks_cut_mid_sentence("như quán cà phê, thư viện,")
    assert _text_looks_cut_mid_sentence(
        "Không chỉ sửa chữa khi hỏng hóc mà còn đảm bảo"
    )
    assert _text_looks_cut_mid_sentence("là lựa chọn lý tưởng, giúp")
    assert not _text_looks_cut_mid_sentence("Đây là câu hoàn chỉnh.")


def test_html_has_incomplete_across_multiple_h2() -> None:
    html = """
    <h1>Dịch vụ vệ sinh laptop</h1>
    <h2>Phù hợp với ai?</h2>
    <p>Dịch vụ đáp ứng nhu cầu đa dạng của nhiều đối</p>
    <h2>Người dùng cá nhân</h2>
    <p>Làm việc tại quán cà phê, thư viện,</p>
    <h2>Doanh nghiệp</h2>
    <p>Không chỉ sửa chữa khi hỏng hóc mà còn đảm bảo</p>
    <h2>Người bận rộn</h2>
    <p>Dịch vụ tại nhà là lựa chọn lý tưởng, giúp</p>
    """
    tails = iter_incomplete_paragraph_tails(html)
    assert len(tails) >= 4
    assert _html_has_incomplete_tail(html)


def test_trim_html_never_cuts_mid_sentence() -> None:
    html = (
        "<h1>Title</h1>"
        "<h2>Section A</h2>"
        "<p>Đây là câu hoàn chỉnh số một. Đây là câu hoàn chỉnh số hai với nhiều từ hơn.</p>"
        "<h2>Section B</h2>"
        "<p>Đoạn cuối cũng là câu hoàn chỉnh với nội dung dài để kích hoạt trim ngân sách từ.</p>"
        "<p>Thêm một đoạn hoàn chỉnh nữa để vượt giới hạn từ khi rút gọn.</p>"
    )
    out = _trim_html_to_max_words(html, 18)
    assert out
    assert not iter_incomplete_paragraph_tails(out), out


def test_take_first_words_at_sentence_refuses_unsafe_cut() -> None:
    text = "Câu một hoàn chỉnh. Câu hai cũng xong. Câu ba đang viết dở giữa chừng"
    safe = _take_first_words_at_sentence(text, 6)
    assert safe is None or safe.endswith((".", "!", "?", "…"))


def test_extract_clean_keeps_unclosed_truncated_tail() -> None:
    raw = "<h2>X</h2><p>Phần mở đầu bị cắt giữa chừng tại đây"
    kept = extract_clean_html_fragment(raw)
    assert "cắt giữa chừng" in kept


def test_extract_clean_still_drops_preamble_noise() -> None:
    raw = "<h2>X</h2><p>OK.</p>\nHere is the article explanation"
    kept = extract_clean_html_fragment(raw)
    assert "Here is" not in kept
    assert "OK." in kept


def test_anthropic_content_cap_raised() -> None:
    assert _ANTHROPIC_CONTENT_MAX_TOKENS_CAP == 16384
    # Long articles can exceed the old hard 8192 ceiling.
    long_mt = _anthropic_max_tokens_for_field(field="content", word_target=12000)
    assert long_mt == 16384
    assert long_mt > 8192
    assert _anthropic_max_tokens_for_field(field="content", word_target=1000) >= 4096
    assert _anthropic_max_tokens_for_field(field="content", word_target=1000) <= 16384


def test_finish_reason_length_detection() -> None:
    assert _finish_reason_is_length("length")
    assert _finish_reason_is_length("max_tokens")
    assert _finish_reason_is_length("MAX_TOKENS")
    assert not _finish_reason_is_length("end_turn")
    assert not _finish_reason_is_length("stop")


def test_length_continue_appends_without_rewriting(monkeypatch) -> None:
    from app.services import llm_content_writer as m
    from app.services.llm_content_writer import LlmConfig

    calls: list[str] = []

    def fake_result(*, cfg, system, user, max_tokens_oai, max_tokens_ant, timeout_sec):
        calls.append(user)
        if len(calls) == 1:
            return "<p>Dịch vụ vệ sinh laptop giúp</p>", "max_tokens"
        return "<p>khách hàng tiết kiệm thời gian.</p>", "end_turn"

    monkeypatch.setattr(m, "_llm_chat_for_cfg_result", fake_result)
    cfg = LlmConfig(
        provider="anthropic",
        api_key="x",
        model="claude-test",
        temperature=0.2,
        api_base_url="",
    )
    out = m._llm_chat_for_cfg(
        cfg=cfg,
        system="sys",
        user="write article",
        max_tokens_oai=4000,
        max_tokens_ant=4000,
        timeout_sec=30,
    )
    assert "giúp" in out
    assert "tiết kiệm thời gian" in out
    assert len(calls) == 2
