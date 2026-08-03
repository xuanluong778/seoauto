"""
Gap analysis: your page vs aggregated SERP benchmark.
"""

from __future__ import annotations

from typing import Any


def analyze_serp_gaps(
    your_page: dict[str, Any],
    benchmark: dict[str, Any],
    *,
    keyword: str,
    competitor_domains: list[str],
) -> list[dict[str, Any]]:
    """
    ``your_page``: ``{word_count, heading_structure_score, internal_link_count?, title?, ...}``
    from crawl + content analysis.

    Returns issues with ``why``, ``triggered_by_competitors`` (domains), ``gap_score`` 0–1.
    """
    issues: list[dict[str, Any]] = []
    doms = ", ".join(competitor_domains[:5]) if competitor_domains else "SERP leaders"

    y_wc = int(your_page.get("word_count") or 0)
    b_wc = int(benchmark.get("avg_word_count") or 0)
    if b_wc > 0 and y_wc < b_wc * 0.55:
        issues.append(
            {
                "issue": "content_too_thin_vs_serp",
                "severity": "high" if y_wc < b_wc * 0.35 else "medium",
                "gap_score": round(min(1.0, (b_wc - y_wc) / max(b_wc, 1)), 3),
                "recommendation": f"Expand substantive body copy toward ~{int(b_wc * 0.95)}+ words; top results average {b_wc} words.",
                "why": f"Your page has {y_wc} words vs SERP average {b_wc}; thin pages rarely win this query class.",
                "triggered_by_competitors": doms,
            }
        )

    y_h = float(your_page.get("heading_structure_score") or 0.0)
    b_h = float(benchmark.get("avg_heading_score") or 0.0)
    if b_h > 0.45 and y_h + 0.18 < b_h:
        issues.append(
            {
                "issue": "heading_structure_behind_serp",
                "severity": "medium",
                "gap_score": round(min(1.0, b_h - y_h), 3),
                "recommendation": "Rebuild H1 + logical H2/H3 outline mirroring winning SERP patterns (FAQ, comparison blocks).",
                "why": f"Heading structure score {y_h:.2f} lags benchmark {b_h:.2f}.",
                "triggered_by_competitors": doms,
            }
        )

    y_il = int(your_page.get("internal_link_count") or your_page.get("internal_links") or 0)
    b_il = float(benchmark.get("avg_internal_links") or 0.0)
    if b_il >= 8 and y_il < b_il * 0.4:
        issues.append(
            {
                "issue": "weak_internal_linking_vs_serp",
                "severity": "medium",
                "gap_score": round(min(1.0, (b_il - y_il) / max(b_il, 1)), 3),
                "recommendation": "Add contextual internal links to hubs, related guides, and commercial pages crawlers can follow.",
                "why": f"Top results average {b_il:.0f} internal links in fetch window; you show fewer ({y_il}).",
                "triggered_by_competitors": doms,
            }
        )

    y_kc = float(your_page.get("keyword_coverage") or 0.0)
    b_kc = float(benchmark.get("avg_keyword_coverage") or 0.0)
    if b_kc > 0.12 and y_kc + 0.08 < b_kc:
        issues.append(
            {
                "issue": "keyword_coverage_gap",
                "severity": "low",
                "gap_score": round(min(1.0, b_kc - y_kc), 3),
                "recommendation": f"Naturally weave query terms and variants for «{keyword}» in intro, H2s, and body without stuffing.",
                "why": "Lexical coverage of the target query trails the SERP centroid.",
                "triggered_by_competitors": doms,
            }
        )

    y_d = float(your_page.get("content_depth_score") or 0.35)
    b_d = float(benchmark.get("avg_content_depth_score") or 0.5)
    if b_d > 0.55 and y_d + 0.15 < b_d:
        issues.append(
            {
                "issue": "semantic_depth_gap",
                "severity": "medium",
                "gap_score": round(min(1.0, b_d - y_d), 3),
                "recommendation": "Add entities, examples, data tables, and FAQs so topical breadth matches high-ranking pages.",
                "why": "Depth / richness proxy is below SERP leaders.",
                "triggered_by_competitors": doms,
            }
        )

    return issues
