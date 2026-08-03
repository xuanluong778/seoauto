"""
Keyword research API bundle: expansion (SERP + DB + GSC) → volume (+ monthly shape) → intent (rules) → KD → TF-IDF clusters.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

from app.services.cluster_planning_output import enrich_tfidf_cluster_for_planning
from app.services.keyword_cluster_tfidf import cluster_keywords_tfidf
from app.services.keyword_clustering_engine import build_keyword_clusters
from app.services.keyword_intent_rules import classify_intent_detail
from app.services.keyword_kd import compute_kd, estimate_allintitle
from app.services.keyword_research_metrics import (
    NA,
    build_data_warnings,
    build_search_volume_package,
    competition_label_from_index,
    compute_trend,
    cpc_package,
    parse_monthly_search_values,
    refresh_volumes_from_search_volume_api,
    volume_debug_row,
)
from app.services.keyword_normalizer import dedupe_keyword_dicts

_LOG = logging.getLogger(__name__)
from app.services.keyword_research_engine import run_keyword_research
from app.services.keyword_dataforseo_expand import expand_keywords_from_dataforseo
from app.services.keyword_research_cost import (
    KeywordResearchCostExceeded,
    attach_cost_meta,
    default_max_keywords,
    serp_enabled_on_initial_run,
)
from app.services.keyword_serp_expansion import expand_keywords_from_serp
from app.services.keyword_difficulty import compute_keyword_difficulty
from app.services.keyword_intelligence import guess_brand_terms
from app.services.search_volume import _COMMERCIAL
from app.services.search_volume import enrich_keyword_volumes_cached, monthly_search_volume_shape
from app.services.serp_competitor_analysis import analyze_serp_competitors
from app.services.serp_fetcher import fetch_serp_for_keyword, fetch_serp_top10_rows, normalize_serp_domain
from app.services.serp_layout_intent import infer_serp_layout_intent
from concurrent.futures import ThreadPoolExecutor, as_completed


def _serp_results_from_snap(snap: dict[str, Any]) -> list[dict[str, Any]]:
    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    snippets = list(snap.get("snippets") or [])
    out: list[dict[str, Any]] = []
    for i, u in enumerate(urls):
        try:
            host = normalize_serp_domain(urlparse(u).hostname or "")
        except Exception:
            host = ""
        out.append(
            {
                "url": u,
                "title": titles[i] if i < len(titles) else "",
                "snippet": snippets[i] if i < len(snippets) else "",
                "domain": host,
            }
        )
    return out


def _serp_top10_payload(keyword: str, *, country: str, language: str, device: str) -> dict[str, Any]:
    snap = fetch_serp_for_keyword(
        keyword,
        top_n=10,
        country=country,
        language=language,
        device=device,
        use_cache=True,
    )
    urls = list(snap.get("serp_urls") or [])
    titles = list(snap.get("titles") or [])
    snippets = list(snap.get("snippets") or [])
    results: list[dict[str, Any]] = []
    for i, u in enumerate(urls[:10]):
        results.append(
            {
                "position": i + 1,
                "url": u,
                "title": titles[i] if i < len(titles) else "",
                "snippet": snippets[i] if i < len(snippets) else "",
            }
        )
    return {
        "keyword": str(snap.get("keyword") or keyword),
        "results": results,
        "features": snap.get("features") or {},
        "source": snap.get("source") or "none",
        "locale": {
            "country": snap.get("country") or country,
            "language": snap.get("language") or language,
            "device": snap.get("device") or device,
        },
        "serp_cache_digest": snap.get("serp_cache_digest"),
        "fetched_at": snap.get("fetched_at"),
    }


def _competition_from_difficulty(d: float) -> str:
    x = float(d)
    if x < 0.35:
        return "Low"
    if x < 0.65:
        return "Medium"
    return "High"


def _cpc_triplet(keyword: str, avg_vol: int) -> tuple[float, float, float]:
    """Heuristic CPC (USD-like) when Keyword Planner API is not configured."""
    k = (keyword or "").strip().lower()
    h = int(hashlib.md5(k.encode(), usedforsecurity=False).hexdigest()[:8], 16)
    base = 0.12 + (h % 110) / 45.0
    if _COMMERCIAL.search(k):
        base *= 1.4
    vol_boost = min(2.4, 1.0 + math.log1p(max(0, int(avg_vol))) / 15.0)
    avg_c = round(min(120.0, base * vol_boost), 2)
    lo = round(avg_c * 0.48, 2)
    hi = round(avg_c * 1.52, 2)
    return lo, avg_c, hi


def _rolling_month_labels_vi() -> list[str]:
    y, m = date.today().year, date.today().month
    labels: list[str] = []
    for _ in range(12):
        labels.append(f"T{m}, {y}")
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return list(reversed(labels))


_MONTH_KEYS_CH = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def _chart_from_search_volume(sv: dict[str, Any], labels: list[str]) -> dict[str, Any]:
    cs = list(sv.get("chart_series") or [])
    if len(cs) != 12:
        all_v = [int(sv.get(m) or 0) for m in _MONTH_KEYS_CH]
        if sum(all_v) == 0:
            return {}
        cs = []
        for av in all_v:
            p = int(av * 0.45)
            cs.append({"all": av, "pc": p, "mobile": max(0, av - p)})
    pc = [int(x.get("pc") or 0) for x in cs]
    mobile = [int(x.get("mobile") or 0) for x in cs]
    all_v = [int(x.get("all") or 0) for x in cs]
    return {
        "labels": labels,
        "pc": pc,
        "mobile": mobile,
        "all": all_v,
    }


def _parse_seeds_from_string(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    parts = re.split(r"[\n\r]+|[+;]|,", s)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p or len(p) > 400:
            continue
        pl = p.lower()
        if pl in seen:
            continue
        seen.add(pl)
        out.append(p)
    return out[:50]


def _normalize_seed_list(seed_keywords: list[str] | None) -> list[str]:
    if not seed_keywords:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in seed_keywords:
        p = str(x or "").strip()
        if not p or len(p) > 400:
            continue
        pl = p.lower()
        if pl in seen:
            continue
        seen.add(pl)
        out.append(p)
    return out[:50]


def _difficulty_0_1_for_seed(
    seed: str,
    *,
    country: str | None = None,
    language: str | None = None,
    device: str | None = None,
) -> float | None:
    try:
        snap = fetch_serp_for_keyword(
            seed.strip(),
            top_n=10,
            country=country,
            language=language,
            device=device,
        )
        if not (snap.get("serp_urls") or []):
            return None
        results = _serp_results_from_snap(snap)
        analysis = analyze_serp_competitors(results, None, keyword=seed)
        kd = compute_keyword_difficulty(analysis)
        return round(float(kd.get("difficulty_score") or 0) / 100.0, 4)
    except Exception:
        return None


def build_keyword_research_api_response(
    *,
    seed_keyword: str | None = None,
    seed_keywords: list[str] | None = None,
    domain: str | None = None,
    url: str | None = None,
    gsc_queries: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    engine: str | None = None,
    language: str | None = None,
    country: str | None = None,
    device: str | None = None,
    cluster_mode: str | None = None,
    cluster_strictness: str | None = None,
    cluster_fetch_serp: bool | None = None,
    cluster_max_keywords: int | None = None,
    max_keywords: int | None = None,
    deep_analysis: bool = False,
    allow_dataforseo_live: bool = True,
    billing_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns ``keywords`` list + ``meta`` including ``clusters``.

    ``cluster_mode``: ``hybrid`` (default), ``tfidf``, hoặc ``both`` (trả cả hai trong meta).
    ``cluster_strictness``: ``strict`` | ``normal`` | ``loose``.
    ``cluster_fetch_serp``: bật/tắt SERP cho hybrid (mặc định theo env).
    ``cluster_max_keywords``: giới hạn số keyword đưa vào clustering (chi phí/tốc độ).
    """
    seeds = _normalize_seed_list(seed_keywords)
    if not seeds and seed_keyword is not None:
        seeds = _parse_seeds_from_string(seed_keyword)
    if not seeds:
        return {"clusters": [], "keywords": [], "meta": {"error": "seed_keyword_required", "entity": "cluster"}}

    primary = seeds[0]
    seed_display = " + ".join(seeds) if len(seeds) > 1 else primary
    seed_lower_set = {s.lower() for s in seeds}

    max_rows = int(max_keywords or default_max_keywords())
    max_rows = max(20, min(2000, max_rows))
    min_related = int(os.getenv("KEYWORD_RESEARCH_MIN_RELATED", "20"))
    min_related = max(5, min(200, min_related))
    enable_serp = bool(deep_analysis) or serp_enabled_on_initial_run()
    expand_provider = (
        os.getenv("KEYWORD_RESEARCH_EXPAND_PROVIDER", "dataforseo").strip().lower()
    )
    serp_on = os.getenv("KEYWORD_RESEARCH_SERP_EXPAND", "0").lower() in ("1", "true", "yes")
    cluster_threshold_base = float(os.getenv("KEYWORD_CLUSTER_DISTANCE_THRESHOLD", "0.5"))
    cluster_strict = (cluster_strictness or os.getenv("KEYWORD_CLUSTER_STRICTNESS", "normal") or "normal").lower().strip()
    if cluster_strict == "strict":
        cluster_threshold = max(0.12, cluster_threshold_base - 0.1)
    elif cluster_strict == "loose":
        cluster_threshold = min(0.95, cluster_threshold_base + 0.1)
    else:
        cluster_threshold = cluster_threshold_base

    loc_country = country or os.getenv("SERP_DEFAULT_COUNTRY", "vn")
    loc_language = language or os.getenv("SERP_DEFAULT_LANGUAGE", "vi")
    loc_device = device or os.getenv("SERP_DEFAULT_DEVICE", "desktop")

    raw: list[dict[str, Any]] = [{"keyword": s, "source": ["user"]} for s in seeds]
    extra: list[dict[str, Any]] = []
    dataforseo_vol_by_kw: dict[str, dict[str, Any]] = {}
    k4k_count = 0
    fallback_count = 0
    expansion_filtered_count = 0
    expansion_provider_used = expand_provider

    if expand_provider == "dataforseo":
        dfs_rows = expand_keywords_from_dataforseo(
            seeds,
            country=loc_country,
            language=loc_language,
            total_cap=min(int(os.getenv("KEYWORD_RESEARCH_DATAFORSEO_K4K_TOTAL", "120")), max_rows),
            allow_api=allow_dataforseo_live,
            stats=billing_stats,
        )
        k4k_count = len(dfs_rows)
        if billing_stats is not None:
            expansion_filtered_count += int(billing_stats.get("k4k_filtered_count") or 0)
        for row in dfs_rows:
            kw = str(row.get("keyword") or "").strip()
            if not kw:
                continue
            extra.append({"keyword": kw, "source": "dataforseo"})
            dataforseo_vol_by_kw[kw.lower()] = {
                "keyword": kw,
                "search_volume": int(row.get("search_volume") or 0),
                "volume_source": "dataforseo",
                "confidence": 0.92,
                "cpc_avg": float(row.get("cpc_avg") or 0.0),
                "cpc_min": float(row.get("cpc_min") or 0.0),
                "cpc_max": float(row.get("cpc_max") or 0.0),
                "competition_index": row.get("competition_index"),
                "monthly_searches": row.get("monthly_searches"),
            }
    elif expand_provider != "dataforseo":
        engine_rows = run_keyword_research(
            seed_keywords=seeds,
            url=url,
            domain=domain,
            gsc_queries=gsc_queries,
            pages=pages,
            force_expand=True,
        )
        fallback_count = len(engine_rows)
        extra.extend(engine_rows)
        if serp_on:
            extra.extend(
                expand_keywords_from_serp(
                    seeds,
                    total_cap=min(200, max_rows),
                    country=loc_country,
                    language=loc_language,
                    device=loc_device,
                )
            )
        if url and len(extra) < 40:
            path = (urlparse(url).path or "").strip("/")
            if path:
                slug_kw = path.replace("-", " ").replace("/", " ")[:80].strip()
                if slug_kw and slug_kw.lower() not in seed_lower_set:
                    extra.append({"keyword": slug_kw, "source": "url_path"})
    elif serp_on:
        extra.extend(
            expand_keywords_from_serp(
                seeds,
                total_cap=min(200, max_rows),
                country=loc_country,
                language=loc_language,
                device=loc_device,
            )
        )
        if url and len(extra) < 40:
            path = (urlparse(url).path or "").strip("/")
            if path:
                slug_kw = path.replace("-", " ").replace("/", " ")[:80].strip()
                if slug_kw and slug_kw.lower() not in seed_lower_set:
                    extra.append({"keyword": slug_kw, "source": "url_path"})

    merged_probe = dedupe_keyword_dicts(list(raw) + extra, key_field="keyword")
    need_fallback = len(merged_probe) < max(len(seeds) + min_related, min_related + 1)
    if expand_provider == "dataforseo" and (k4k_count == 0 or need_fallback):
        expansion_provider_used = "dataforseo+fallback"
        fallback_rows = run_keyword_research(
            seed_keywords=seeds,
            url=url,
            domain=domain,
            gsc_queries=gsc_queries,
            pages=pages,
            force_expand=True,
        )
        fallback_count = len(fallback_rows)
        extra.extend(fallback_rows)
        if enable_serp:
            serp_fallback = expand_keywords_from_serp(
                seeds,
                total_cap=min(200, max_rows),
                country=loc_country,
                language=loc_language,
                device=loc_device,
            )
            extra.extend(serp_fallback)
    elif expand_provider != "dataforseo" and len(merged_probe) < max(len(seeds) + min_related, min_related + 1):
        expansion_provider_used = "engine+fallback"
        fallback_rows = run_keyword_research(
            seed_keywords=seeds,
            url=url,
            domain=domain,
            gsc_queries=gsc_queries,
            pages=pages,
            force_expand=True,
        )
        fallback_count = max(fallback_count, len(fallback_rows))
        extra.extend(fallback_rows)

    merged = dedupe_keyword_dicts(list(raw) + extra, key_field="keyword")
    merged = merged[:max_rows]
    final_count = len(merged)
    if final_count < max(len(seeds) + min_related, min_related + 1):
        _LOG.warning(
            "keyword_research_expand insufficient seeds=%s provider=%s k4k_count=%s fallback_count=%s final_count=%s",
            seeds,
            expansion_provider_used,
            k4k_count,
            fallback_count,
            final_count,
        )

    _LOG.info(
        "keyword_research_expand seeds=%s provider=%s k4k_count=%s fallback_count=%s final_count=%s filtered_count=%s",
        seeds,
        expansion_provider_used,
        k4k_count,
        fallback_count,
        final_count,
        expansion_filtered_count,
    )

    all_kw_phrases = [str(r.get("keyword") or "").strip() for r in merged if str(r.get("keyword") or "").strip()]
    vol_by_kw: dict[str, dict[str, Any]] = dict(dataforseo_vol_by_kw)
    if expand_provider == "dataforseo" and dataforseo_vol_by_kw:
        missing_for_vol = [k for k in all_kw_phrases if k.lower() not in dataforseo_vol_by_kw]
        if missing_for_vol:
            vol_rows = enrich_keyword_volumes_cached(
                missing_for_vol,
                country=loc_country,
                language=loc_language,
                allow_api=allow_dataforseo_live,
                stats=billing_stats,
            )
            for v in vol_rows or []:
                kw = str(v.get("keyword") or "").strip().lower()
                if kw:
                    vol_by_kw[kw] = v
    else:
        vol_rows = enrich_keyword_volumes_cached(
            all_kw_phrases,
            country=loc_country,
            language=loc_language,
            allow_api=allow_dataforseo_live,
            stats=billing_stats,
        )
        vol_by_kw = {str(v.get("keyword") or "").strip().lower(): v for v in (vol_rows or []) if v.get("keyword")}

    # Authoritative monthly volume from Google Ads search_volume/live (fixes stale K4K cache).
    refresh_volume_on_run = bool(deep_analysis) or os.getenv("KEYWORD_RESEARCH_REFRESH_VOLUME", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    if refresh_volume_on_run:
        vol_by_kw = refresh_volumes_from_search_volume_api(
            all_kw_phrases,
            vol_by_kw,
            country=loc_country,
            language=loc_language,
            allow_api=allow_dataforseo_live,
            stats=billing_stats,
        )

    volume_debug_samples: list[dict[str, Any]] = []
    keywords_out: list[dict[str, Any]] = []
    for row in merged:
        kw = str(row.get("keyword") or "").strip()
        if not kw:
            continue
        vol_pkg = vol_by_kw.get(kw.lower()) or {}
        vol_raw = vol_pkg.get("search_volume")
        raw_volume: int | None
        try:
            raw_volume = int(vol_raw) if vol_raw is not None else None
        except (TypeError, ValueError):
            raw_volume = None
        vsrc = str(vol_pkg.get("volume_source") or NA)
        from_cache = vsrc in ("api_cache", "cache")
        monthly_searches = vol_pkg.get("monthly_searches")
        updated_at = str(vol_pkg.get("updated_at") or vol_pkg.get("fetched_at") or "")
        monthly = build_search_volume_package(
            kw,
            raw_volume=raw_volume,
            volume_source=vsrc,
            monthly_searches=monthly_searches,
            from_cache=from_cache,
            updated_at=updated_at or None,
        )

        intent_pkg = classify_intent_detail(kw)
        intent = str(intent_pkg.get("intent") or "unknown")

        comp, comp_ds = competition_label_from_index(vol_pkg.get("competition_index"))
        if comp_ds == NA:
            comp = "Unknown"

        wc = len(kw.split())
        cpc_avg, cpc_lo, cpc_hi, cpc_ds = cpc_package(
            cpc_avg=vol_pkg.get("cpc_avg"),
            cpc_min=vol_pkg.get("cpc_min"),
            cpc_max=vol_pkg.get("cpc_max"),
            volume_source=vsrc if vol_pkg else NA,
            from_cache=from_cache,
        )

        parsed_monthly = parse_monthly_search_values(monthly_searches)
        trend = compute_trend(parsed_monthly)

        vol_for_kd = monthly.get("display_volume")
        vol_for_kd_i = int(vol_for_kd) if vol_for_kd is not None else None
        ai_est = estimate_allintitle(kw) if deep_analysis else None
        kd_pkg = (
            compute_kd(
                allintitle=ai_est,
                volume=vol_for_kd_i,
                cpc=cpc_avg,
                competition_label=comp,
            )
            if deep_analysis
            else {"kd": None, "kd_label": "N/A", "allintitle": None}
        )

        raw_src = row.get("source")
        if isinstance(raw_src, str):
            src = [raw_src]
        elif isinstance(raw_src, list):
            src = [str(x) for x in raw_src]
        else:
            src = ["user"]

        vol_ds = str(monthly.get("data_source") or NA)
        data_source = {
            "volume": vol_ds,
            "cpc": cpc_ds,
            "competition": comp_ds,
            "trend": str(trend.get("data_source") or NA),
            "intent": str(intent_pkg.get("source") or NA),
            "kd": "computed" if kd_pkg.get("kd") is not None else NA,
            "allintitle": "fallback" if ai_est is not None else NA,
        }
        warnings = build_data_warnings(
            volume_ds=vol_ds,
            cpc_ds=cpc_ds,
            competition_ds=comp_ds,
            trend_ds=str(trend.get("data_source") or NA),
            intent=intent,
            kd_label=str(kd_pkg.get("kd_label") or NA),
        )

        canonical = kw.lower().strip()
        debug = volume_debug_row(
            kw,
            canonical_keyword=canonical,
            raw_volume=monthly.get("raw_volume"),
            display_volume=monthly.get("display_volume"),
            data_source=vol_ds,
            updated_at=monthly.get("updated_at"),
        )
        if len(volume_debug_samples) < 120:
            volume_debug_samples.append(debug)
        _LOG.info(
            "keyword_volume keyword=%s canonical=%s raw=%s display=%s source=%s updated_at=%s",
            debug["keyword"],
            debug["canonical_keyword"],
            debug["raw_volume"],
            debug["display_volume"],
            debug["data_source"],
            debug["updated_at"],
        )

        keywords_out.append(
            {
                "keyword": kw,
                "canonical_keyword": canonical,
                "raw_volume": monthly.get("raw_volume"),
                "display_volume": monthly.get("display_volume"),
                "search_volume": monthly,
                "difficulty": kd_pkg["kd"],
                "kd": kd_pkg["kd"],
                "kd_label": kd_pkg["kd_label"],
                "word_count": wc,
                "cpc_avg": cpc_avg,
                "cpc_min": cpc_lo,
                "cpc_max": cpc_hi,
                "competition": comp,
                "intent": intent,
                "intent_confidence": float(intent_pkg.get("confidence") or 0.0),
                "intent_source": str(intent_pkg.get("source") or NA),
                "trend": trend,
                "source": src,
                "allintitle_estimate": kd_pkg["allintitle"],
                "data_source": data_source,
                "data_warnings": warnings,
                "updated_at": monthly.get("updated_at"),
                "volume_debug": debug,
            }
        )

    # SERP top10 layer — only on deep analysis or explicit env (costly).
    serp_layer_on = enable_serp and os.getenv("KEYWORD_RESEARCH_FETCH_SERP_TOP10", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    if serp_layer_on and os.getenv("SERP_FETCH_ENABLED", "0").lower() in ("1", "true", "yes") and keywords_out:
        max_kw = int(os.getenv("KEYWORD_RESEARCH_SERP_TOP10_MAX", "40"))
        max_kw = max(1, min(250, max_kw))
        workers = int(os.getenv("KEYWORD_RESEARCH_SERP_TOP10_WORKERS", "6"))
        workers = max(1, min(12, workers))

        target_rows = keywords_out[:max_kw]
        t0_serp = time.perf_counter()
        ok_n = 0

        def _one(kw: str) -> tuple[str, list[dict[str, str]], str]:
            payload = fetch_serp_top10_rows(
                kw,
                country=loc_country,
                language=loc_language,
                device=loc_device,
                use_cache=True,
            )
            rows = payload.get("rows") or []
            src = str(payload.get("source") or "none")
            return kw, rows, src

        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_one, str(r.get("keyword") or "")): r for r in target_rows}
                for fut in as_completed(futs):
                    base_row = futs[fut]
                    kw = str(base_row.get("keyword") or "").strip()
                    if not kw:
                        continue
                    try:
                        _kw, rows, src = fut.result()
                        base_row["serp_top10"] = rows
                        base_row["serp_source"] = src
                        ok_n += 1 if rows else 0
                    except Exception:
                        base_row["serp_top10"] = []
                        base_row["serp_source"] = "error"
        except Exception:
            # If threadpool/requests fails broadly, keep pipeline usable.
            pass

        meta_hint = {
            "enabled": True,
            "max_keywords": max_kw,
            "workers": workers,
            "keywords_with_rows": ok_n,
            "duration_ms": int((time.perf_counter() - t0_serp) * 1000),
            "cache": "serp_fetcher.fetch_serp_for_keyword (redis+mem+disk snapshot optional)",
        }
    else:
        meta_hint = {"enabled": False}

    cluster_cap = int(cluster_max_keywords or os.getenv("KEYWORD_RESEARCH_CLUSTER_MAX", str(default_max_keywords())))
    cluster_cap = max(15, min(int(os.getenv("KEYWORD_RESEARCH_CLUSTER_MAX_CAP", "200")), cluster_cap))
    keywords_cluster_in = keywords_out[:cluster_cap]
    keywords_cluster_truncated = len(keywords_out) > len(keywords_cluster_in)

    cluster_mode_eff = (
        cluster_mode
        or os.getenv("KEYWORD_RESEARCH_RUN_CLUSTER_MODE")
        or os.getenv("KEYWORD_RESEARCH_CLUSTER_MODE", "tfidf")
        or "tfidf"
    ).lower().strip()
    if cluster_fetch_serp is None:
        hybrid_fetch_serp = bool(deep_analysis) and os.getenv("KEYWORD_RESEARCH_FETCH_SERP_CLUSTER", "0").lower() in (
            "1",
            "true",
            "yes",
        )
    else:
        hybrid_fetch_serp = bool(cluster_fetch_serp)

    t_cluster = time.perf_counter()
    brand_hint = ""
    if url:
        try:
            brand_hint = urlparse(url).hostname or ""
        except Exception:
            brand_hint = ""
    if not brand_hint:
        brand_hint = (domain or "")[:200]
    brand = guess_brand_terms(f"https://{brand_hint}" if brand_hint and not brand_hint.startswith("http") else (brand_hint or "https://example.com"))

    clusters_hybrid: list[dict[str, Any]] = []
    if cluster_mode_eff in ("hybrid", "best", "accurate", "both"):
        try:
            raw_clusters = build_keyword_clusters(
                [{"keyword": str(r.get("keyword") or "").strip(), "source": "research"} for r in keywords_cluster_in if str(r.get("keyword") or "").strip()],
                brand_terms=brand,
                fetch_serp=hybrid_fetch_serp,
                serp_country=loc_country,
                serp_language=loc_language,
                serp_device=loc_device,
                cluster_strictness=cluster_strict,
            )
            kw_map = {str(r.get("keyword") or "").strip().lower(): r for r in keywords_out}
            for i, c in enumerate(raw_clusters):
                members = [str(x.get("keyword") or "").strip() for x in (c.get("keywords") or []) if x.get("keyword")]
                members = [m for m in members if m]
                members = list(dict.fromkeys(members))
                total_vol = 0
                for m in members:
                    row = kw_map.get(m.lower())
                    if row:
                        total_vol += int((row.get("search_volume") or {}).get("avg_monthly") or 0)
                ex = c.get("explain")
                primary_kw = str(c.get("main_keyword") or c.get("cluster_name") or (members[0] if members else "")).strip()
                if primary_kw and primary_kw.lower() not in {m.lower() for m in members}:
                    members = [primary_kw, *members]
                clusters_hybrid.append(
                    {
                        "cluster_id": f"cluster_{i + 1}",
                        "primary_keyword": primary_kw,
                        "variations": members,
                        "intent": str(c.get("intent") or "unknown"),
                        "cohesion_score": c.get("cohesion_score"),
                        "cluster_size": int(c.get("cluster_size") or len(members)),
                        "total_volume": int(total_vol),
                        "serp_overlap_score": float(c.get("serp_overlap_score") or 0.0),
                        "detail": {
                            "explain": ex if isinstance(ex, dict) else {"note": str(ex or "hybrid_clusterer")},
                            "serp_data_available": bool((ex or {}).get("serp_data_available")) if isinstance(ex, dict) else True,
                            "cluster_strictness": cluster_strict,
                        },
                    }
                )
        except Exception:
            clusters_hybrid = []

    clusters_tfidf = cluster_keywords_tfidf(keywords_cluster_in, distance_threshold=cluster_threshold)
    kw_lower_map = {str(r.get("keyword") or "").strip().lower(): r for r in keywords_out}
    for tc in clusters_tfidf:
        enrich_tfidf_cluster_for_planning(tc, kw_rows_by_lower=kw_lower_map)

    def _cluster_entity_from_any(c: dict[str, Any], i: int) -> dict[str, Any]:
        primary = str(c.get("primary_keyword") or c.get("main_keyword") or c.get("cluster_name") or "").strip()
        raw_vars = c.get("variations") or c.get("keywords") or c.get("supporting_keywords") or []
        vals: list[str] = []
        seen_v: set[str] = set()
        for x in raw_vars:
            kw = str(x.get("keyword") if isinstance(x, dict) else x or "").strip()
            if not kw:
                continue
            low = kw.lower()
            if low in seen_v:
                continue
            seen_v.add(low)
            vals.append(kw)
        if primary and primary.lower() not in seen_v:
            vals.insert(0, primary)
        if not primary and vals:
            primary = vals[0]
        total = int(c.get("total_volume") or c.get("cluster_total_volume") or c.get("total_search_volume") or 0)
        return {
            "cluster_id": str(c.get("cluster_id") or f"cluster_{i + 1}"),
            "primary_keyword": primary,
            "variations": vals,
            "total_volume": total,
            "cluster_size": int(c.get("cluster_size") or len(vals)),
            "intent": str(c.get("intent") or "unknown"),
            "cohesion_score": c.get("cohesion_score"),
            "serp_overlap_score": float(c.get("serp_overlap_score") or 0.0),
            "detail": c.get("detail") if isinstance(c.get("detail"), dict) else {},
        }

    if cluster_mode_eff == "tfidf":
        clusters_payload = [_cluster_entity_from_any(c, i) for i, c in enumerate(clusters_tfidf)]
    elif cluster_mode_eff == "both":
        src = clusters_hybrid if clusters_hybrid else clusters_tfidf
        clusters_payload = [_cluster_entity_from_any(c, i) for i, c in enumerate(src)]
    else:
        src = clusters_hybrid if clusters_hybrid else clusters_tfidf
        clusters_payload = [_cluster_entity_from_any(c, i) for i, c in enumerate(src)]

    # SERP-based SEO-priority scoring (normalized to 0-100):
    # raw = (w_vol*volume_norm + w_intent*intent_weight + w_diff*(1-difficulty)) * opportunity_boost
    intent_weights = {
        "transactional": float(os.getenv("KEYWORD_INTENT_WEIGHT_TRANSACTIONAL", "1.25")),
        "commercial": float(os.getenv("KEYWORD_INTENT_WEIGHT_COMMERCIAL", "1.15")),
        "ecommerce": float(os.getenv("KEYWORD_INTENT_WEIGHT_ECOMMERCE", "1.2")),
        "informational": float(os.getenv("KEYWORD_INTENT_WEIGHT_INFORMATIONAL", "0.95")),
        "navigational": float(os.getenv("KEYWORD_INTENT_WEIGHT_NAVIGATIONAL", "0.8")),
        "mixed_intent": float(os.getenv("KEYWORD_INTENT_WEIGHT_MIXED", "0.98")),
    }
    w_vol = max(0.0, float(os.getenv("KEYWORD_SCORE_WEIGHT_VOLUME", "0.45")))
    w_int = max(0.0, float(os.getenv("KEYWORD_SCORE_WEIGHT_INTENT", "0.35")))
    w_diff = max(0.0, float(os.getenv("KEYWORD_SCORE_WEIGHT_DIFFICULTY", "0.20")))
    w_sum = max(1e-9, (w_vol + w_int + w_diff))
    w_vol, w_int, w_diff = (w_vol / w_sum), (w_int / w_sum), (w_diff / w_sum)

    kw_metrics_by_lower = {str(r.get("keyword") or "").strip().lower(): r for r in keywords_out}
    kw_difficulty_by_lower = {
        str(r.get("keyword") or "").strip().lower(): float(r.get("difficulty") or r.get("kd") or 0.0)
        for r in keywords_out
        if str(r.get("keyword") or "").strip()
    }

    # Batch SERP intent fetch for cluster primary keywords (cache-aware).
    serp_intent_by_primary: dict[str, tuple[str | None, list[str]]] = {}
    # SERP intent per cluster primary — expensive (DataForSEO live); off by default on research run.
    serp_intent_on = bool(deep_analysis) and os.getenv("KEYWORD_RESEARCH_SERP_CLUSTER_INTENT", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    if serp_intent_on and os.getenv("SERP_FETCH_ENABLED", "0").lower() in ("1", "true", "yes") and clusters_payload:
        uniq_primary = list(
            dict.fromkeys(
                str(c.get("primary_keyword") or "").strip()
                for c in clusters_payload
                if str(c.get("primary_keyword") or "").strip()
            )
        )
        if uniq_primary:
            workers_serp_intent = int(os.getenv("KEYWORD_RESEARCH_SERP_INTENT_WORKERS", "6"))
            workers_serp_intent = max(1, min(12, workers_serp_intent))

            def _fetch_primary_serp_intent(pk: str) -> tuple[str, str | None, list[str]]:
                try:
                    snap = fetch_serp_for_keyword(
                        pk,
                        top_n=10,
                        use_cache=True,
                        country=loc_country,
                        language=loc_language,
                        device=loc_device,
                    )
                    sig = infer_serp_layout_intent(snap or {})
                    if sig:
                        return pk, (str(sig.get("effective_intent") or "").strip() or None), [str(x) for x in (sig.get("top_page_types") or [])][:5]
                except Exception:
                    pass
                return pk, None, []

            with ThreadPoolExecutor(max_workers=workers_serp_intent) as ex:
                futs = [ex.submit(_fetch_primary_serp_intent, pk) for pk in uniq_primary]
                for fut in as_completed(futs):
                    pk, it, pts = fut.result()
                    serp_intent_by_primary[pk.lower()] = (it, pts)

    max_cluster_volume = max([int(c.get("total_volume") or 0) for c in clusters_payload] or [1])
    score_raw_values: list[float] = []
    for c in clusters_payload:
        primary_kw = str(c.get("primary_keyword") or "").strip()
        variations = [str(v).strip() for v in (c.get("variations") or []) if str(v).strip()]

        serp_intent = None
        serp_page_types: list[str] = []
        if primary_kw:
            serp_intent, serp_page_types = serp_intent_by_primary.get(primary_kw.lower(), (None, []))

        if serp_intent:
            c["intent"] = serp_intent

        # Difficulty proxy from member keywords already scored in keywords_out.
        kd_vals = [kw_difficulty_by_lower.get(kw.lower()) for kw in variations if kw_difficulty_by_lower.get(kw.lower()) is not None]
        difficulty = float(sum(kd_vals) / len(kd_vals)) if kd_vals else 0.5
        difficulty = max(0.0, min(1.0, difficulty))

        volume = int(c.get("total_volume") or 0)
        intent_key = str(c.get("intent") or "unknown").strip().lower()
        iw = float(intent_weights.get(intent_key, 1.0))
        # Normalize volume by log scale to avoid huge-volume domination.
        vol_norm = (math.log1p(max(0, volume)) / math.log1p(max(1, max_cluster_volume))) if max_cluster_volume > 0 else 0.0
        diff_headroom = (1.0 - difficulty)
        # Small opportunity boost: lower difficulty with decent volume moves up.
        opportunity_boost = 1.0 + 0.25 * (vol_norm * diff_headroom)
        raw_score = (w_vol * vol_norm + w_int * iw + w_diff * diff_headroom) * opportunity_boost
        score_raw_values.append(float(raw_score))

        c["difficulty"] = round(difficulty, 4)
        c["intent_weight"] = round(iw, 4)
        c["score_raw"] = round(float(raw_score), 6)
        detail = c.get("detail") if isinstance(c.get("detail"), dict) else {}
        detail["serp_intent_detected"] = serp_intent
        detail["serp_result_types"] = serp_page_types
        c["detail"] = detail

    # Normalize scores into 0-100 for stable ranking/UX.
    if clusters_payload:
        s_min = min(score_raw_values) if score_raw_values else 0.0
        s_max = max(score_raw_values) if score_raw_values else 0.0
        for c in clusters_payload:
            rv = float(c.get("score_raw") or 0.0)
            if s_max > s_min:
                s100 = 100.0 * (rv - s_min) / (s_max - s_min)
            else:
                s100 = 50.0 if rv > 0 else 0.0
            c["score"] = round(max(0.0, min(100.0, s100)), 2)

    clusters_payload.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    cluster_duration_ms = int((time.perf_counter() - t_cluster) * 1000)

    est_count = sum(1 for k in keywords_out if k["search_volume"].get("is_estimated"))
    chart_labels = _rolling_month_labels_vi()
    chart_payload: dict[str, Any] = {}
    seed_row = next((r for r in keywords_out if r["keyword"].lower() in seed_lower_set), None)
    ref = seed_row or (keywords_out[0] if keywords_out else None)
    if ref:
        chart_payload = _chart_from_search_volume(ref.get("search_volume") or {}, chart_labels)
        chart_payload["seed_keyword"] = seed_display
        chart_payload["related_count"] = len(keywords_out)

    total_vol = sum(int((k["search_volume"] or {}).get("avg_monthly") or 0) for k in keywords_out)
    avg_cpc_all = (
        round(sum(float(k.get("cpc_avg") or 0) for k in keywords_out) / len(keywords_out), 2) if keywords_out else 0.0
    )

    _LOG.info("keyword_research_cost %s", attach_cost_meta(billing_stats))

    meta_out: dict[str, Any] = {
        "entity": "cluster",
        "seed_keyword": primary,
        "seed_keywords": seeds,
        "seed_query": seed_display,
        "count": len(clusters_payload),
        "keyword_count_deduped": len(keywords_out),
        "estimated_volume_rows": est_count,
        "serp_expansion": serp_on if expand_provider != "dataforseo" else False,
        "expand_provider": expansion_provider_used,
        "expansion": {
            "seeds": seeds,
            "provider": expansion_provider_used,
            "k4k_count": k4k_count,
            "fallback_count": fallback_count,
            "final_count": final_count,
            "filtered_count": expansion_filtered_count,
            "min_related": min_related,
            "deep_analysis": bool(deep_analysis),
            "serp_enabled": enable_serp,
        },
        "cost": attach_cost_meta(billing_stats),
        "engine": (engine or "google").lower(),
        "language": language or "vi",
        "country": country or "vn",
        "device": loc_device,
        "serp_snapshot_disk": os.getenv("SERP_SNAPSHOT_DISK", "1"),
        "serp_fetch_enabled": os.getenv("SERP_FETCH_ENABLED", "0"),
        "chart": chart_payload,
        "clusters": clusters_payload,
        "clusters_mode": cluster_mode_eff,
        "clusters_primary_source": "hybrid" if clusters_hybrid else "tfidf",
        "clusters_tfidf": clusters_tfidf,
        "cluster_metrics": {
            "duration_ms": cluster_duration_ms,
            "strictness": cluster_strict,
            "hybrid_fetch_serp": hybrid_fetch_serp,
            "keywords_in_cluster_run": len(keywords_cluster_in),
            "keywords_truncated_for_cluster": keywords_cluster_truncated,
            "cluster_cap": cluster_cap,
            "tfidf_distance_threshold": cluster_threshold,
            "serp_cache": "redis+digest(keyword+country+language+device); see SERP_CACHE_TTL_SECONDS",
            "scoring_formula": "score_raw=(w_vol*vol_norm + w_intent*intent_weight + w_diff*(1-difficulty))*opportunity_boost; score=normalize_0_100(score_raw)",
            "scoring_weights": {
                "volume": round(w_vol, 4),
                "intent": round(w_int, 4),
                "difficulty": round(w_diff, 4),
            },
        },
        "totals": {
            "search_volume_sum": int(total_vol),
            "cpc_avg": avg_cpc_all,
        },
        "volume_debug": volume_debug_samples[:120],
        "serp_top10_layer": meta_hint,
    }
    # Attach SERP top10 snapshot for the primary seed (scalable default).
    # For 50–200 keywords, fetching SERP for every row is too expensive; clustering already fetches
    # SERP when enabled. You can opt-in to more via env if needed later.
    if enable_serp and os.getenv("SERP_FETCH_ENABLED", "0").lower() in ("1", "true", "yes"):
        try:
            meta_out["seed_serp_top10"] = _serp_top10_payload(
                primary,
                country=loc_country,
                language=loc_language,
                device=loc_device,
            )
        except Exception:
            meta_out["seed_serp_top10"] = {}
    if cluster_mode_eff == "both":
        meta_out["clusters_hybrid"] = clusters_hybrid
    # Keep backward compatibility for UIs that render keyword-level table/volume directly.
    return {"clusters": clusters_payload, "keywords": keywords_out, "meta": meta_out}
