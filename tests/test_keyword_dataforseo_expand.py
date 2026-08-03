from __future__ import annotations

from app.services.keyword_dataforseo_expand import is_valid_research_keyword


def test_rejects_serp_title_junk() -> None:
    assert is_valid_research_keyword("dịch vụ seo") is True
    assert is_valid_research_keyword("Dịch Vụ SEO tại Việt Nam | Công Ty SEO Seosmart - seosmart.net.vn") is False
    assert is_valid_research_keyword("best dịch vụ seo") is True
