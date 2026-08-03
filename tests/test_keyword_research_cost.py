from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app.services.keyword_dataforseo_expand import _k4k_cache_key, _k4k_cache_set, expand_keywords_from_dataforseo
from app.services.keyword_research_pipeline import build_keyword_research_api_response

_DFS_ENV = {"DATAFORSEO_ENABLED": "1", "VOLUME_API_ENABLED": "1"}


def test_initial_research_skips_bulk_serp() -> None:
    serp_top10 = MagicMock(return_value={"rows": [], "source": "mock"})
    serp_expand = MagicMock(return_value=[])
    with (
        patch("app.services.keyword_research_pipeline.expand_keywords_from_dataforseo", return_value=[]),
        patch("app.services.keyword_research_pipeline.fetch_serp_top10_rows", serp_top10),
        patch("app.services.keyword_research_pipeline.expand_keywords_from_serp", serp_expand),
        patch("app.services.keyword_research_pipeline.fetch_serp_for_keyword") as serp_kw,
    ):
        out = build_keyword_research_api_response(
            seed_keywords=["sửa máy tính"],
            country="vn",
            language="vi",
            deep_analysis=False,
            allow_dataforseo_live=False,
        )
        assert len(out.get("keywords") or []) > 20
        serp_top10.assert_not_called()
        serp_expand.assert_not_called()
        serp_kw.assert_not_called()
        assert (out.get("meta") or {}).get("expansion", {}).get("serp_enabled") is False


def test_k4k_cache_prevents_second_live_call(monkeypatch) -> None:
    for k, v in _DFS_ENV.items():
        monkeypatch.setenv(k, v)
    live_calls: list[str] = []

    def fake_k4k(seeds, **kwargs):
        live_calls.append("k4k")
        return [
            {
                "keyword": "spa tphcm",
                "search_volume": 200,
                "cpc_avg": 0.5,
                "cpc_min": 0.2,
                "cpc_max": 0.8,
                "competition_index": 0.2,
            }
        ]

    cache_key = _k4k_cache_key("spa", country="vn", language="vi", limit=120)
    _k4k_cache_set(
        cache_key,
        [
            {
                "keyword": "spa tphcm",
                "search_volume": 200,
                "cpc_avg": 0.5,
                "cpc_min": 0.2,
                "cpc_max": 0.8,
                "competition_index": 0.2,
            }
        ],
    )

    with patch(
        "app.services.keyword_dataforseo_expand.fetch_dataforseo_keywords_for_keywords",
        side_effect=fake_k4k,
    ):
        rows1 = expand_keywords_from_dataforseo(["spa"], country="vn", language="vi", allow_api=True)
        rows2 = expand_keywords_from_dataforseo(["spa"], country="vn", language="vi", allow_api=True)
        assert len(rows1) >= 1
        assert len(rows2) >= 1
        assert live_calls == []
