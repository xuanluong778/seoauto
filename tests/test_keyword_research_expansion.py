from __future__ import annotations

from unittest.mock import patch

from app.services.keyword_intent_rules import classify_intent_detail
from app.services.keyword_research_engine import run_keyword_research
from app.services.keyword_research_pipeline import build_keyword_research_api_response


def test_run_keyword_research_vi_expansion_count() -> None:
    for seed in ("sửa máy tính", "spa", "dịch vụ seo"):
        rows = run_keyword_research(seed_keywords=[seed])
        assert len(rows) > 20, f"expected >20 related keywords for {seed!r}, got {len(rows)}"


def test_pipeline_fallback_when_k4k_empty() -> None:
    with patch(
        "app.services.keyword_research_pipeline.expand_keyword_ideas",
        return_value=[],
    ), patch(
        "app.services.keyword_research_pipeline.expand_keywords_from_dataforseo",
        return_value=[],
    ):
        for seed in ("sửa máy tính", "spa", "dịch vụ seo"):
            out = build_keyword_research_api_response(
                seed_keywords=[seed],
                country="vn",
                language="vi",
                allow_dataforseo_live=False,
            )
            kws = out.get("keywords") or []
            exp = (out.get("meta") or {}).get("expansion") or {}
            assert len(kws) > 20, f"fallback must return >20 for {seed!r}, got {len(kws)}"
            assert exp.get("k4k_count") == 0
            assert int(exp.get("fallback_count") or 0) > 0
            assert int(exp.get("final_count") or 0) == len(kws)


def test_pipeline_fallback_when_expand_env_off() -> None:
    import os

    with patch(
        "app.services.keyword_research_pipeline.expand_keyword_ideas",
        return_value=[],
    ), patch(
        "app.services.keyword_research_pipeline.expand_keywords_from_dataforseo",
        return_value=[],
    ):
        with patch.dict(os.environ, {"KEYWORD_RESEARCH_EXPAND": "0"}, clear=False):
            out = build_keyword_research_api_response(
                seed_keywords=["sửa máy tính"],
                country="vn",
                language="vi",
                allow_dataforseo_live=False,
            )
            kws = out.get("keywords") or []
            exp = (out.get("meta") or {}).get("expansion") or {}
            assert len(kws) > 20, f"pipeline must expand even when KEYWORD_RESEARCH_EXPAND=0, got {len(kws)}"
            assert int(exp.get("fallback_count") or 0) > 20


def test_vi_service_intent_rules() -> None:
    assert classify_intent_detail("sửa máy tính tận nhà")["intent"] == "commercial"
    assert classify_intent_detail("dịch vụ spa tphcm")["intent"] in ("commercial", "local", "mixed")
    assert classify_intent_detail("báo giá dịch vụ seo quận 1")["intent"] in ("commercial", "local", "mixed", "transactional")
