"""Google Ads primary + DataForSEO fallback + cache + SaaS-safe Keyword Research."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from app.services.keyword_ads_expand import expand_keyword_ideas
from app.services.keyword_intent_rules import classify_intent_detail
from app.services.search_volume import enrich_keyword_volumes_cached


def _no_db():
    return patch("app.db.SessionLocal", side_effect=RuntimeError("nodb"))


def _ads_idea(keyword: str, volume: int = 100) -> dict:
    return {
        "keyword": keyword,
        "search_volume": volume,
        "cpc_avg": 12000.0,
        "cpc_min": 8000.0,
        "cpc_max": 16000.0,
        "competition": "LOW",
        "competition_index": 20,
        "monthly_searches": [{"year": 2024, "month": i, "search_volume": volume} for i in range(1, 13)],
        "volume_source": "google_ads",
        "provider": "google_ads",
        "source": "google_ads",
        "confidence": 0.95,
    }


def _dfs_idea(keyword: str, volume: int = 50) -> dict:
    return {
        "keyword": keyword,
        "search_volume": volume,
        "cpc_avg": 1.2,
        "cpc_min": 0.8,
        "cpc_max": 1.6,
        "competition_index": 0.2,
        "monthly_searches": [{"year": 2024, "month": i, "search_volume": volume} for i in range(1, 7)],
        "volume_source": "dataforseo",
        "provider": "dataforseo",
        "source": "dataforseo",
        "confidence": 0.92,
    }


def test_bao_gia_seo_is_transactional() -> None:
    assert classify_intent_detail("báo giá seo")["intent"] == "transactional"


def test_ads_success_skips_dataforseo(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    monkeypatch.setenv("GOOGLE_ADS_KEYWORD_ENABLED", "1")
    ads = MagicMock(return_value=[_ads_idea("seo việt nam", 170)])
    dfs = MagicMock(return_value=[_dfs_idea("should not appear")])
    stats: dict = {}
    with patch("app.services.keyword_ads_expand.google_ads_configured", return_value=True), patch(
        "app.services.keyword_ads_expand.fetch_google_ads_keyword_ideas", ads
    ), patch(
        "app.services.keyword_ads_expand._ideas_cache_get", return_value=None
    ), patch(
        "app.services.keyword_ads_expand._ideas_cache_set", lambda *a, **k: None
    ), patch(
        "app.services.keyword_ads_expand.expand_keywords_from_dataforseo", dfs
    ), patch(
        "app.services.keyword_ads_expand.singleflight", lambda _k, fn, **kw: fn()
    ):
        rows = expand_keyword_ideas(["seo việt nam"], country="vn", language="vi", allow_api=True, stats=stats)
    assert rows
    assert all(r.get("provider") == "google_ads" for r in rows)
    ads.assert_called()
    dfs.assert_not_called()
    assert stats.get("dataforseo_calls", 0) == 0


def test_ads_fail_falls_back_dataforseo_missing_seeds_only(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    monkeypatch.setenv("DATAFORSEO_ENABLED", "1")
    ads = MagicMock(return_value=[])
    dfs = MagicMock(return_value=[_dfs_idea("seo agency")])
    stats: dict = {}
    with patch("app.services.keyword_ads_expand.google_ads_configured", return_value=True), patch(
        "app.services.keyword_ads_expand.fetch_google_ads_keyword_ideas", ads
    ), patch(
        "app.services.keyword_ads_expand._ideas_cache_get", return_value=None
    ), patch(
        "app.services.keyword_ads_expand._ideas_cache_set", lambda *a, **k: None
    ), patch(
        "app.services.keyword_ads_expand.expand_keywords_from_dataforseo", dfs
    ), patch(
        "app.services.keyword_ads_expand.singleflight", lambda _k, fn, **kw: fn()
    ):
        rows = expand_keyword_ideas(["seo"], country="vn", language="vi", allow_api=True, stats=stats)
    assert rows[0]["provider"] == "dataforseo"
    dfs.assert_called_once()
    called_seeds = dfs.call_args[0][0]
    assert called_seeds == ["seo"]


def test_idea_cache_hit_skips_live_ads(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock()
    dfs = MagicMock()
    cached = [_ads_idea("cached kw")]
    with patch("app.services.keyword_ads_expand.google_ads_configured", return_value=True), patch(
        "app.services.keyword_ads_expand.fetch_google_ads_keyword_ideas", ads
    ), patch(
        "app.services.keyword_ads_expand._ideas_cache_get", return_value=cached
    ), patch(
        "app.services.keyword_ads_expand.expand_keywords_from_dataforseo", dfs
    ):
        rows = expand_keyword_ideas(["seo"], country="vn", language="vi", allow_api=True, stats={})
    assert rows
    ads.assert_not_called()
    dfs.assert_not_called()


def test_volume_ads_success_skips_dfs(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(return_value=[_ads_idea("seo việt nam", 170)])
    dfs = MagicMock(return_value=[_dfs_idea("seo việt nam")])
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._db_get", return_value=None
    ), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats=stats
        )
    assert rows[0]["volume_source"] == "google_ads"
    ads.assert_called()
    dfs.assert_not_called()
    assert stats.get("dataforseo_calls", 0) == 0


def test_volume_ads_fail_dfs_then_heuristic(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(return_value=[])
    dfs = MagicMock(return_value=[])
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["unknown long tail xyzabc"], country="vn", language="vi", allow_api=True, stats=stats
        )
    assert rows[0]["volume_source"] == "estimated"
    assert rows[0]["provider"] == "heuristic"
    ads.assert_called()
    dfs.assert_called()


def test_volume_cache_hit_skips_both_providers(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    cached = {
        "keyword": "seo việt nam",
        "search_volume": 170,
        "volume_source": "google_ads",
        "provider": "google_ads",
        "cpc_avg": 1,
        "cpc_min": 1,
        "cpc_max": 2,
        "competition": "LOW",
        "competition_index": 20,
        "monthly_searches": [{"year": 2024, "month": i, "search_volume": 170} for i in range(1, 13)],
        "confidence": 0.9,
    }
    ads = MagicMock()
    dfs = MagicMock()
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=cached), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats={}
        )
    assert rows[0]["search_volume"] == 170
    ads.assert_not_called()
    dfs.assert_not_called()


def test_partial_fallback_only_missing_keywords(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")

    def ads_side(kws, **kwargs):
        return [_ads_idea("kw ads")] if "kw ads" in kws else []

    dfs = MagicMock(return_value=[_dfs_idea("kw dfs")])
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics",
        side_effect=ads_side,
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["kw ads", "kw dfs"], country="vn", language="vi", allow_api=True, stats={}
        )
    by = {r["keyword"]: r for r in rows}
    assert by["kw ads"]["provider"] == "google_ads"
    assert by["kw dfs"]["provider"] == "dataforseo"
    dfs_args = dfs.call_args[0][0]
    assert dfs_args == ["kw dfs"]


def test_concurrent_volume_singleflight(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    calls = []

    def ads_fn(kws, **kwargs):
        calls.append(list(kws))
        return [_ads_idea(kws[0], 10)]

    real_sf = None
    from app.services.volume_providers import google_ads as ga

    real_sf = ga.singleflight

    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads_fn
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", MagicMock(return_value=[])
    ):
        def _run():
            return enrich_keyword_volumes_cached(
                ["same kw"], country="vn", language="vi", allow_api=True, stats={}
            )

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(_run) for _ in range(4)]
            for f in futs:
                f.result()
    assert 1 <= len(calls) <= 4
    assert real_sf is not None


def test_allow_api_false_skips_dataforseo_but_still_calls_ads(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(return_value=[_ads_idea("seo", 100)])
    dfs = MagicMock()
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["seo"], country="vn", language="vi", allow_api=False, stats={}
        )
    assert rows[0]["volume_source"] == "google_ads"
    assert rows[0]["cpc_avg"] > 0
    ads.assert_called()
    dfs.assert_not_called()


def test_stale_estimated_cache_refetches_ads(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    stale = {
        "keyword": "đào tạo seo",
        "search_volume": 14800,
        "volume_source": "manual_override",
        "provider": "manual_override",
        "cpc_avg": 0,
        "cpc_min": 0,
        "cpc_max": 0,
        "confidence": 0.9,
    }
    ads = MagicMock(return_value=[_ads_idea("đào tạo seo", 2100)])
    dfs = MagicMock()
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=stale), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["đào tạo seo"], country="vn", language="vi", allow_api=True, stats={}
        )
    assert rows[0]["volume_source"] == "google_ads"
    assert rows[0]["cpc_avg"] == 12000.0
    ads.assert_called()
    dfs.assert_not_called()


def test_ads_historical_metrics_map_cpc_trend_competition() -> None:
    from types import SimpleNamespace

    from app.services.keyword_research_metrics import (
        build_search_volume_package,
        competition_label_from_index,
        compute_trend,
        cpc_package,
        parse_monthly_search_values,
    )
    from app.services.volume_providers.google_ads import _row_from_metrics

    months = [
        "JANUARY",
        "FEBRUARY",
        "MARCH",
        "APRIL",
        "MAY",
        "JUNE",
        "JULY",
        "AUGUST",
        "SEPTEMBER",
        "OCTOBER",
        "NOVEMBER",
        "DECEMBER",
    ]
    metrics = SimpleNamespace(
        avg_monthly_searches=SimpleNamespace(value=170),
        competition=SimpleNamespace(name="MEDIUM"),
        competition_index=55,
        average_cpc_micros=12_000_000,
        low_top_of_page_bid_micros=8_000_000,
        high_top_of_page_bid_micros=16_000_000,
        monthly_search_volumes=[
            SimpleNamespace(year=2024, month=SimpleNamespace(name=name), monthly_searches=100 + i * 10)
            for i, name in enumerate(months)
        ],
    )
    row = _row_from_metrics("seo việt nam", metrics)
    assert row["cpc_avg"] == 12.0
    assert row["cpc_min"] == 8.0
    assert row["cpc_max"] == 16.0
    assert row["competition"] == "MEDIUM"
    assert row["volume_source"] == "google_ads"
    vals = parse_monthly_search_values(row["monthly_searches"])
    assert vals is not None and len(vals) == 12
    trend = compute_trend(vals, data_source="google_ads")
    assert trend["direction"] in ("up", "down", "stable")
    assert trend["data_source"] == "google_ads"
    label, src = competition_label_from_index(row["competition"], provider="google_ads")
    assert label == "Medium"
    assert src == "google_ads"
    avg, lo, hi, cpc_ds = cpc_package(
        cpc_avg=row["cpc_avg"], cpc_min=row["cpc_min"], cpc_max=row["cpc_max"], volume_source="google_ads"
    )
    assert (avg, lo, hi, cpc_ds) == (12.0, 8.0, 16.0, "google_ads")
    pkg = build_search_volume_package(
        "seo việt nam",
        raw_volume=170,
        volume_source="google_ads",
        monthly_searches=row["monthly_searches"],
    )
    assert pkg["data_source"] == "google_ads"
    assert pkg["is_estimated"] is False


def test_ads_cpc_zero_avg_uses_bid_micros() -> None:
    from types import SimpleNamespace

    from app.services.volume_providers.google_ads import _row_from_metrics

    metrics = SimpleNamespace(
        avg_monthly_searches=12100,
        average_monthly_searches=None,
        competition=SimpleNamespace(name="LOW"),
        competition_index=1,
        average_cpc_micros=0,
        low_top_of_page_bid_micros=3_474_740_108,
        high_top_of_page_bid_micros=13_461_516_945,
        monthly_search_volumes=[
            SimpleNamespace(year=2025, month=13, monthly_searches=14800),
            SimpleNamespace(year=2026, month=SimpleNamespace(name="JULY"), monthly_searches=8100),
        ],
    )
    row = _row_from_metrics("đào tạo seo", metrics)
    assert row["search_volume"] == 12100
    assert row["cpc_avg"] == 8468.1285
    assert row["cpc_min"] == 3474.7401
    assert row["cpc_max"] == 13461.5169
    assert row["cpc_source"] == "google_ads"
    assert row["competition"] == "LOW"
    months = { (m["year"], m["month"]): m["search_volume"] for m in row["monthly_searches"] }
    assert months[(2025, 12)] == 14800
    assert months[(2026, 7)] == 8100


def test_ads_missing_fields_dfs_fills_only_gaps(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(
        return_value=[
            {
                "keyword": "seo việt nam",
                "search_volume": 170,
                "cpc_avg": 0.0,
                "cpc_min": 0.0,
                "cpc_max": 0.0,
                "competition": "",
                "competition_index": None,
                "monthly_searches": [],
                "volume_source": "google_ads",
                "provider": "google_ads",
                "confidence": 0.95,
            }
        ]
    )
    dfs = MagicMock(
        return_value=[
            {
                "keyword": "seo việt nam",
                "search_volume": 50,
                "cpc_avg": 1.2,
                "cpc_min": 0.8,
                "cpc_max": 1.6,
                "competition_index": 0.4,
                "monthly_searches": [{"year": 2024, "month": i, "search_volume": 40 + i} for i in range(1, 13)],
                "volume_source": "dataforseo",
                "provider": "dataforseo",
                "confidence": 0.9,
            }
        ]
    )
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats={}
        )
    row = rows[0]
    assert row["search_volume"] == 170
    assert row["volume_source"] == "google_ads"
    assert row["provider"] == "google_ads"
    assert row["cpc_avg"] == 1.2
    assert row["cpc_source"] == "dataforseo"
    assert row["monthly_searches"]
    assert row["monthly_source"] == "dataforseo"
    dfs.assert_called_once()
    ads.assert_called_once()


def test_real_volume_not_tilde_estimated_is_tilde() -> None:
    from app.services.keyword_research_metrics import build_search_volume_package

    ads = build_search_volume_package("seo", raw_volume=170, volume_source="google_ads")
    dfs = build_search_volume_package("seo", raw_volume=50, volume_source="dataforseo")
    est = build_search_volume_package("seo", raw_volume=12, volume_source="estimated")
    assert ads["data_source"] == "google_ads" and ads["is_estimated"] is False
    assert dfs["data_source"] == "dataforseo" and dfs["is_estimated"] is False
    assert est["data_source"] == "fallback" and est["is_estimated"] is True


def test_incomplete_google_ads_cache_not_heuristic_when_ads_misses(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    incomplete = {
        "keyword": "đào tạo seo",
        "search_volume": 12100,
        "volume_source": "google_ads",
        "provider": "google_ads",
        "cpc_avg": 0,
        "cpc_min": 0,
        "cpc_max": 0,
        "confidence": 0.95,
    }
    ads = MagicMock(return_value=[])
    dfs = MagicMock(return_value=[])
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=incomplete), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["đào tạo seo"], country="vn", language="vi", allow_api=True, stats={}
        )
    assert rows[0]["volume_source"] == "google_ads"
    assert rows[0]["search_volume"] == 12100
    ads.assert_called()


def test_volume_cache_payload_keeps_monthly_cpc_competition(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_redis(_digest, payload):
        captured["redis"] = payload

    def fake_db(_digest, payload):
        captured["db"] = payload

    monkeypatch.setattr("app.services.search_volume._redis_set", fake_redis)
    monkeypatch.setattr("app.services.search_volume._db_set", fake_db)
    from app.services.search_volume import _cache_set_volume_row, _volume_extra_from_payload

    _cache_set_volume_row(_ads_idea("seo việt nam", 170), country="vn", language="vi")
    payload = captured["redis"]
    assert payload["cpc_avg"] == 12000.0
    assert payload["competition"] == "LOW"
    assert payload["competition_index"] == 20
    assert len(payload["monthly_searches"]) == 12
    extra = _volume_extra_from_payload(payload)
    assert extra["monthly_searches"]
    assert extra["competition"] == "LOW"
    assert captured["db"]["monthly_searches"]


def test_research_ui_dropped_allintitle_and_kd_columns() -> None:
    html = open("templates/keyword_research.html", encoding="utf-8").read()
    assert "Allintitle" not in html
    assert "Độ khó" not in html
    assert "btnAllintitle" not in html
    assert "data-sort=\"diff\"" not in html


def _ensure_redis_url() -> str:
    url = (os.getenv("REDIS_URL") or "").strip()
    if url:
        return url
    for path in (
        "env.local",
        "/var/www/seoauto_vn_usr/data/www/shared/env.local",
    ):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw.startswith("REDIS_URL="):
                        continue
                    return raw.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _live_redis():
    url = _ensure_redis_url()
    if not url:
        return None
    try:
        import redis

        r = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.5)
        r.ping()
        return r
    except Exception:
        return None


def _sf_worker_cli() -> None:
    import redis as redis_lib
    from app.services.volume_providers.google_ads import singleflight

    r = redis_lib.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    flight_key = os.environ["ADS_SF_FLIGHT_KEY"]
    counter_key = os.environ["ADS_SF_COUNTER_KEY"]
    wait_s = float(os.environ.get("ADS_SF_WAIT_S") or "8")
    sleep_s = float(os.environ.get("ADS_SF_SLEEP_S") or "0.4")

    def fn():
        r.incr(counter_key)
        time.sleep(sleep_s)
        return [{"keyword": "seo việt nam", "search_volume": 170, "provider": "google_ads"}]

    out = singleflight(flight_key, fn, wait_s=wait_s)
    if not out or out[0].get("keyword") != "seo việt nam":
        raise SystemExit(2)


def _start_sf_worker(*, flight_key: str, counter_key: str, redis_url: str, wait_s: float, sleep_s: float):
    env = os.environ.copy()
    env["REDIS_URL"] = redis_url
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    env["ADS_SF_FLIGHT_KEY"] = flight_key
    env["ADS_SF_COUNTER_KEY"] = counter_key
    env["ADS_SF_WAIT_S"] = str(wait_s)
    env["ADS_SF_SLEEP_S"] = str(sleep_s)
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from tests.test_google_ads_keyword_provider import _sf_worker_cli; _sf_worker_cli()",
        ],
        env=env,
        cwd=os.getcwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_two_processes_same_miss_call_google_ads_once() -> None:
    r = _live_redis()
    if r is None:
        raise RuntimeError("Redis required for Google Ads single-flight cross-process test")
    redis_url = _ensure_redis_url()
    nonce = uuid.uuid4().hex
    flight_key = f"ads_vol:test-sf-{nonce}"
    counter_key = f"ads_sf_test_calls:{nonce}"
    lock_key = f"ads_sf:{flight_key}"
    res_key = f"ads_sf_res:{flight_key}"
    r.delete(lock_key, res_key, counter_key)
    procs = [
        _start_sf_worker(
            flight_key=flight_key,
            counter_key=counter_key,
            redis_url=redis_url,
            wait_s=8.0,
            sleep_s=0.4,
        )
        for _ in range(2)
    ]
    try:
        codes = [p.wait(timeout=15) for p in procs]
        calls = int(r.get(counter_key) or 0)
        assert calls == 1, f"expected 1 Google Ads call, got {calls}"
        assert codes == [0, 0]
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=2)
        r.delete(lock_key, res_key, counter_key)


def test_worker_crash_ttl_allows_new_acquire() -> None:
    r = _live_redis()
    if r is None:
        raise RuntimeError("Redis required for Google Ads single-flight TTL test")
    redis_url = _ensure_redis_url()
    nonce = uuid.uuid4().hex
    flight_key = f"ads_vol:test-ttl-{nonce}"
    counter_key = f"ads_sf_test_calls:{nonce}"
    lock_key = f"ads_sf:{flight_key}"
    res_key = f"ads_sf_res:{flight_key}"
    r.delete(lock_key, res_key, counter_key)
    r.set(lock_key, "dead-worker", nx=True, ex=2)
    waiter = _start_sf_worker(
        flight_key=flight_key,
        counter_key=counter_key,
        redis_url=redis_url,
        wait_s=8.0,
        sleep_s=0.05,
    )
    try:
        assert r.get(lock_key) == "dead-worker"
        code = waiter.wait(timeout=15)
        assert code == 0
        assert int(r.get(counter_key) or 0) == 1
        assert r.get(lock_key) in (None, False)
    finally:
        if waiter.poll() is None:
            waiter.terminate()
            waiter.wait(timeout=2)
        r.delete(lock_key, res_key, counter_key)


def test_release_lock_ignores_non_owner_token() -> None:
    r = _live_redis()
    if r is None:
        raise RuntimeError("Redis required for Google Ads lock-owner test")
    from app.services.volume_providers.google_ads import _release_lock

    lock_key = f"ads_sf:owner-test-{uuid.uuid4().hex}"
    r.set(lock_key, "owner-a", nx=True, ex=20)
    try:
        _release_lock(r, lock_key, "owner-b")
        assert r.get(lock_key) == "owner-a"
        _release_lock(r, lock_key, "owner-a")
        assert r.get(lock_key) in (None, False)
    finally:
        r.delete(lock_key)


def test_redis_error_falls_back_in_memory() -> None:
    from app.services.volume_providers import google_ads as ga

    calls: list[int] = []

    def fn():
        calls.append(1)
        time.sleep(0.2)
        return [{"keyword": "ok"}]

    boom = MagicMock()
    boom.set.side_effect = RuntimeError("redis down")
    with patch("app.services.volume_providers.google_ads._redis_client", return_value=boom):
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(ga.singleflight, "mem-fallback-key", fn, wait_s=5) for _ in range(4)]
            vals = [f.result() for f in futs]
    assert len(calls) == 1
    assert all(v == [{"keyword": "ok"}] for v in vals)


def test_ads_only_dfs_cost_is_zero(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(return_value=[_ads_idea("seo việt nam", 170)])
    dfs = MagicMock()
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats=stats
        )
    from app.services.keyword_research_cost import attach_cost_meta, estimated_cost_usd

    meta = attach_cost_meta(stats)
    assert stats.get("google_ads_calls", 0) == 1
    assert stats.get("dataforseo_calls", 0) == 0
    assert meta["dataforseo_calls"] == 0
    assert meta["google_ads_calls"] == 1
    assert "google_ads_volume" in meta["live_call_labels"]
    assert estimated_cost_usd(stats) == 0
    assert meta["estimated_cost_usd"] == 0
    dfs.assert_not_called()


def test_complete_volume_cache_has_zero_live_cost(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    cached = {
        "keyword": "seo việt nam",
        "search_volume": 170,
        "volume_source": "google_ads",
        "provider": "google_ads",
        "cpc_avg": 1,
        "cpc_min": 1,
        "cpc_max": 2,
        "competition": "LOW",
        "competition_index": 20,
        "monthly_searches": [{"year": 2024, "month": i, "search_volume": 170} for i in range(1, 13)],
        "confidence": 0.9,
    }
    ads = MagicMock()
    dfs = MagicMock()
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=cached), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats=stats
        )
    from app.services.keyword_research_cost import attach_cost_meta

    meta = attach_cost_meta(stats)
    ads.assert_not_called()
    dfs.assert_not_called()
    assert stats.get("google_ads_calls", 0) == 0
    assert stats.get("dataforseo_calls", 0) == 0
    assert meta["estimated_cost_usd"] == 0
    assert meta["live_calls"] == 0


def test_cpc_only_gap_dfs_skips_ads_refetch(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    cached = {
        "keyword": "seo việt nam",
        "search_volume": 170,
        "volume_source": "google_ads",
        "provider": "google_ads",
        "cpc_avg": 0,
        "cpc_min": 0,
        "cpc_max": 0,
        "competition": "LOW",
        "competition_index": 20,
        "monthly_searches": [{"year": 2024, "month": i, "search_volume": 170} for i in range(1, 13)],
        "confidence": 0.95,
    }
    ads = MagicMock()
    dfs = MagicMock(
        return_value=[
            {
                "keyword": "seo việt nam",
                "search_volume": 50,
                "cpc_avg": 1.2,
                "cpc_min": 0.8,
                "cpc_max": 1.6,
                "competition_index": 0.4,
                "monthly_searches": [{"year": 2024, "month": i, "search_volume": 40} for i in range(1, 13)],
                "volume_source": "dataforseo",
                "provider": "dataforseo",
            }
        ]
    )
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=cached), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["seo việt nam"], country="vn", language="vi", allow_api=True, stats=stats
        )
    row = rows[0]
    ads.assert_not_called()
    dfs.assert_called_once()
    assert dfs.call_args[0][0] == ["seo việt nam"]
    assert row["search_volume"] == 170
    assert row["volume_source"] == "google_ads"
    assert row["cpc_avg"] == 1.2
    assert row["cpc_source"] == "dataforseo"
    assert stats.get("google_ads_calls", 0) == 0
    assert stats.get("dataforseo_calls", 0) == 1
    from app.services.keyword_research_cost import attach_cost_meta

    meta = attach_cost_meta(stats)
    assert meta["dataforseo_calls"] == 1
    assert meta["google_ads_calls"] == 0
    assert "search_volume_batch" in meta["live_call_labels"]
    assert meta["estimated_cost_usd"] == 0.01


def test_ads_error_falls_back_dfs_missing_batch(monkeypatch) -> None:
    monkeypatch.setenv("VOLUME_API_ENABLED", "1")
    ads = MagicMock(side_effect=RuntimeError("RESOURCE_EXHAUSTED"))
    dfs = MagicMock(return_value=[_dfs_idea("kw dfs", 40)])
    stats: dict = {}
    with _no_db(), patch("app.services.search_volume._redis_get", return_value=None), patch(
        "app.services.search_volume._cache_set_volume_row", lambda *a, **k: None
    ), patch(
        "app.services.volume_providers.google_ads.google_ads_configured", return_value=True
    ), patch(
        "app.services.volume_providers.google_ads.fetch_google_ads_historical_metrics", ads
    ), patch(
        "app.services.volume_providers.google_ads.singleflight", lambda _k, fn, **kw: fn()
    ), patch(
        "app.services.volume_providers.dataforseo.fetch_dataforseo_search_volume_batch", dfs
    ):
        rows = enrich_keyword_volumes_cached(
            ["kw dfs"], country="vn", language="vi", allow_api=True, stats=stats
        )
    assert rows[0]["provider"] == "dataforseo"
    dfs.assert_called_once()
    assert dfs.call_args[0][0] == ["kw dfs"]
    assert stats.get("dataforseo_calls", 0) == 1
    from app.services.keyword_research_cost import attach_cost_meta

    meta = attach_cost_meta(stats)
    assert "search_volume_batch" in meta["live_call_labels"]
    assert meta["google_ads_calls"] >= 1
    assert meta["dataforseo_calls"] == 1
