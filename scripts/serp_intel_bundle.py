"""
End-to-end SERP intelligence for a keyword: fetch → competitors → difficulty → features → gaps → opportunity → simulation.

Map **keyword → best page → ranking**: pass ``your_pages`` with ``ranking_score`` / ``pagerank_score`` from your crawl + ranking pipeline.
"""

from __future__ import annotations

from typing import Any

from app.services.keyword_difficulty import compute_keyword_difficulty
from app.services.keyword_opportunity import compute_keyword_opportunity
from app.services.ranking_gap import analyze_ranking_gap
from app.services.serp_competitor_analysis import analyze_serp_competitors
from app.services.serp_features import detect_serp_features
from app.services.serp_fetcher import fetch_serp
from app.services.serp_simulation import simulate_serp_ranking


def build_serp_keyword_report(
    keyword: str,
    *,
    search_volume: int | None = None,
    your_pages: list[dict[str, Any]] | None = None,
    crawl_data: dict[str, dict[str, Any]] | None = None,
    topical_authority_score: float | None = None,
    location: str = "US",
    device: str = "desktop",
    num_serp: int | None = None,
) -> dict[str, Any]:
    """
    Single object (Task 8) combining all SERP intelligence submodules.

    ``your_pages``: from site crawl + ranking, e.g. ``[{"url": "...", "ranking_score": 62, "pagerank_score": 0.4,
    "word_count": 900, "primary_topic": "seo", "title": "..."}]``.

    ``crawl_data``: same URL keys as ``analyze_serp_competitors`` expects for internal PageRank.
    """
    your_pages = your_pages or []
    serp = fetch_serp(keyword, location=location, device=device, num=num_serp)
    results = list(serp.get("serp_results") or [])

    serp_analysis = analyze_serp_competitors(results, crawl_data, keyword=keyword)
    difficulty = compute_keyword_difficulty(serp_analysis)
    features = detect_serp_features(serp)

    merged_serp = {**serp, "serp_analysis": serp_analysis}
    gap = analyze_ranking_gap(keyword, your_pages, merged_serp)

    best_url = gap.get("best_matching_url")
    best_page = next((p for p in your_pages if p.get("url") == best_url), your_pages[0] if your_pages else {})
    your_rank = float(best_page.get("ranking_score") or 0.0)

    opportunity = compute_keyword_opportunity(
        keyword,
        search_volume=search_volume,
        difficulty=difficulty,
        your_ranking_score=your_rank,
        topical_authority_score=topical_authority_score,
    )

    simulation = simulate_serp_ranking(
        keyword,
        best_page or {"pagerank_score": 0.3, "word_count": 0},
        serp_analysis.get("competitors") or [],
    )

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "difficulty": difficulty,
        "serp_features": features,
        "serp_analysis": serp_analysis,
        "ranking_gap": gap,
        "opportunity": opportunity,
        "simulation": simulation,
        "serp_fetch_meta": {
            "source": serp.get("source"),
            "location": serp.get("location"),
            "device": serp.get("device"),
            "organic_count": len(results),
            "fetch_error": serp.get("fetch_error"),
        },
    }
