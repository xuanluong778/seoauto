"""
Simulate 5 long Content AI HTML articles through trim + incomplete detection + extract.
Proves system paths no longer introduce mid-sentence cuts (no live LLM required).
"""

from __future__ import annotations

from app.services.content_ai_section_writer import iter_incomplete_paragraph_tails
from app.services.content_draft_builder import extract_clean_html_fragment
from app.services.llm_content_writer import _count_words_html, _trim_html_to_max_words


def _long_article(seed: int, sections: int = 8) -> str:
    parts = [f"<h1>Bai viet dai so {seed}</h1>"]
    for i in range(sections):
        parts.append(f"<h2>Phan {i + 1} chu de dich vu {seed}</h2>")
        parts.append(
            "<p>"
            f"Day la doan van hoan chinh thu {i + 1} cua bai {seed}. "
            "Noi dung mo ta quy trinh, loi ich, chi phi va cam ket bao hanh cho khach hang. "
            "Cau nay ket thuc dung cach."
            "</p>"
        )
        parts.append(
            "<p>"
            f"Them mot doan hoan chinh khac cho bai {seed} muc {i + 1}. "
            "Thong tin thuc te, checklist va FAQ duoc trinh bay ro rang. "
            "Khong co cat ngang giua cau."
            "</p>"
        )
    return "\n".join(parts)


def test_five_long_articles_survive_trim_without_incomplete_tails() -> None:
    results = []
    for seed in range(1, 6):
        html = _long_article(seed, sections=10)
        before_wc = _count_words_html(html)
        assert before_wc > 200
        # Force aggressive trim like CONTENT_AI_SUGGEST_FAST path
        trimmed = _trim_html_to_max_words(html, max(80, before_wc // 3))
        cleaned = extract_clean_html_fragment(trimmed) or trimmed
        tails = iter_incomplete_paragraph_tails(cleaned)
        results.append(
            {
                "seed": seed,
                "before_wc": before_wc,
                "after_wc": _count_words_html(cleaned),
                "incomplete": tails,
            }
        )
        assert not tails, f"seed={seed} incomplete={tails}"
        assert cleaned.strip()
        # Headings preserved
        assert cleaned.lower().count("<h2") >= 2
    assert len(results) == 5


def test_five_articles_with_injected_cuts_are_detectable() -> None:
    """Detector must catch the screenshot-style cuts so repair can run."""
    for seed in range(1, 6):
        html = _long_article(seed, sections=4)
        html += (
            f"<h2>Phù hợp với ai {seed}</h2>"
            "<p>Dịch vụ đáp ứng nhu cầu đa dạng của nhiều đối</p>"
            f"<h2>Người bận rộn {seed}</h2>"
            "<p>Dịch vụ tại nhà là lựa chọn lý tưởng, giúp</p>"
        )
        tails = iter_incomplete_paragraph_tails(html)
        assert len(tails) >= 2, seed
