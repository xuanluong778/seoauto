"""
Site-aware ranking *potential* model: internal links, content, indexability, technical + simulation gates.
"""

from __future__ import annotations

from typing import Any


def get_graph_metrics_for_url(graph: dict[str, Any], url: str, pagerank: dict[str, float]) -> dict[str, Any]:
    nodes = dict(graph.get("nodes") or {})
    node = nodes.get(url) or {"outgoing": [], "incoming": []}
    inc = node.get("incoming") or []
    out = node.get("outgoing") or []
    entry = set(graph.get("entry_urls_normalized") or [])
    orphans = set(graph.get("orphan_urls") or [])
    depth_map = dict(graph.get("crawl_depth") or {})
    return {
        "pagerank_score": float(pagerank.get(url) or 0.0),
        "crawl_depth": depth_map.get(url),
        "is_orphan": url in orphans,
        "in_degree": len(inc),
        "out_degree": len(out),
        "is_entry_url": url in entry,
    }


def compute_ranking_score(
    data: dict[str, Any],
    graph_metrics: dict[str, Any],
    content_metrics: dict[str, Any],
    simulation: dict[str, Any] | None,
    *,
    topical_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Aggregate indexability, PageRank, content, JS, cloaking, canonical hints, crawl depth, orphan status.

    ``data`` may include:
      - ``indexable`` (bool), ``js_dependency`` (bool), ``js_dependency_level`` (str),
      - ``cloaking_risk`` (bool), ``cloaking_advanced`` (dict),
      - ``canonical_valid`` (bool), ``technical_score`` (0–100 from decision summary).
    """
    sim = dict(simulation or {})
    limiting: list[str] = []
    strengths: list[str] = []
    why_not: list[str] = []
    improve: list[str] = []

    indexable = bool(data.get("indexable", True))
    if not indexable:
        why_not.append("Trang không được đánh giá là indexable — không có ranking organic thực tế trên Google.")
        improve.append("Sửa noindex/X-Robots-Tag/HTTP để URL có thể index trước khi tối ưu ranking.")
        return {
            "ranking_score": 0.0,
            "ranking_potential": "low",
            "limiting_factors": ["not_indexable"],
            "strengths": [],
            "why_not_ranking": why_not,
            "what_to_improve": improve,
            "topical_modifiers": {"applied": False},
        }

    tech = float(data.get("technical_score") or 70.0)
    tech = max(0.0, min(100.0, tech))

    pr = float(graph_metrics.get("pagerank_score") or 0.0)
    depth = graph_metrics.get("crawl_depth")
    is_orphan = bool(graph_metrics.get("is_orphan"))
    in_deg = int(graph_metrics.get("in_degree") or 0)

    js_level = str(data.get("js_dependency_level") or ("high" if data.get("js_dependency") else "low")).lower()
    if js_level not in ("low", "medium", "high"):
        js_level = "low"

    cloak_adv = dict(data.get("cloaking_advanced") or {})
    cloak_lvl = str(cloak_adv.get("cloaking_risk_level") or "low").lower()
    cloak_heur = bool(data.get("cloaking_risk"))

    canon_ok = bool(data.get("canonical_valid", True))

    depth_bucket = str(content_metrics.get("content_depth") or "normal")
    wc = int(content_metrics.get("word_count") or 0)
    h_score = float(content_metrics.get("heading_structure_score") or 0.0)
    kd = content_metrics.get("keyword_density_estimate") or {}
    conc = str(kd.get("concentration") or "low")

    score = 18.0 + tech * 0.34
    score += pr * 24.0

    if depth_bucket == "deep":
        score += 16.0
        strengths.append("Khối lượng nội dung dài hơn ngưỡng 'deep' — phù hợp nhiều truy vấn thông tin.")
    elif depth_bucket == "normal":
        score += 10.0
    else:
        score += 4.0
        limiting.append("thin_content")
        why_not.append("Nội dung text mỏng so với đối thủ SERP nhiều chủ đề.")
        improve.append("Mở rộng nội dung có giá trị (FAQ, ví dụ, dữ liệu) trong khi giữ intent trang.")

    score += h_score * 11.0
    if h_score >= 0.72:
        strengths.append("Cấu trúc heading hợp lý (H1/H2) theo heuristic.")

    if js_level == "high":
        score -= 14.0
        limiting.append("js_dependency_high")
        why_not.append("Phụ thuộc JS cao — tín hiệu chính có thể xuất hiện muộn hoặc không ổn định cho crawl.")
        improve.append("SSR/hybrid cho title, H1, nội dung chính; giảm shell trống trên HTML thô.")
    elif js_level == "medium":
        score -= 7.0
        limiting.append("js_dependency_medium")
        improve.append("Đưa phần quan trọng ra HTML tĩnh để giảm rủi ro render/crawl budget.")

    if cloak_lvl == "high" or cloak_heur:
        score -= 20.0 if cloak_lvl == "high" else 11.0
        limiting.append("cloaking_risk")
        why_not.append("Chênh lệch raw vs rendered lớn — giảm tin cậy và dễ trùng pattern rủi ro chính sách.")
        improve.append("Đồng nhất phản hồi cho Googlebot với user; rà A/B, inject title/canonical.")

    if conc == "high":
        score -= 5.0
        limiting.append("keyword_concentration_high")
        improve.append("Giảm lặp lại từ khóa không tự nhiên; đa dạng hóa ngữ cảnh.")

    if is_orphan:
        score -= 12.0
        limiting.append("orphan_page")
        why_not.append("Không có internal link vào URL này trong phạm vi crawl — PageRank nội bộ yếu.")
        improve.append("Thêm liên kết nội bộ từ trang mạnh (hub/category) và breadcrumb.")
    elif in_deg >= 3:
        strengths.append("Nhiều liên kết nội bộ trỏ tới trang (in-degree cao trong crawl).")

    if depth is None:
        score -= 6.0
        limiting.append("unreachable_from_entry")
        why_not.append("Không tìm thấy đường đi ngắn từ entry crawl — có thể xa hub hoặc thiếu liên kết.")
        improve.append("Kết nối URL với homepage hoặc category chính qua menu/footer/contextual links.")
    elif isinstance(depth, int) and depth >= 5:
        score -= min(16.0, 4.0 + (depth - 4) * 3.0)
        limiting.append("deep_crawl_distance")
        why_not.append("Độ sâu click từ entry lớn — tín hiệu liên kết nội bộ suy giảm theo khoảng cách.")
        improve.append("Rút ngắn đường đi bằng liên kết từ trang authority gần gốc site.")
    elif isinstance(depth, int) and depth <= 2 and in_deg > 0:
        strengths.append("Gần entry crawl và có liên kết vào — điều kiện thuận lợi cho discovery.")

    if not canon_ok:
        score -= 8.0
        limiting.append("canonical_signal_weak")
        improve.append("Chuẩn hóa canonical/redirect để tránh cluster không chắc chắn.")

    if sim.get("will_index") is False:
        score *= 0.52
        limiting.append("simulation_will_index_false")
        why_not.append("Mô phỏng indexing: URL khó là bản primary được index (duplicate/canonical).")
        improve.append("Xác định URL canonical đích; 301 hoặc self-canonical đúng intent.")

    rel = str(sim.get("ranking_eligibility") or "high").lower()
    if rel == "low":
        score = min(score, 38.0)
        limiting.append("ranking_eligibility_low")
    elif rel == "medium":
        score = min(score, score * 0.92)

    topical_meta: dict[str, Any] = {"applied": False}
    if topical_signals:
        topical_meta["applied"] = True
        ca = float(topical_signals.get("cluster_authority_normalized") or 0.0)
        tr = float(topical_signals.get("topic_relevance_score") or 0.0)
        ca = max(0.0, min(1.0, ca))
        tr = max(0.0, min(1.0, tr))
        score += ca * 7.0
        score += tr * 9.0
        if ca > 0.12 or tr > 0.12:
            strengths.append(
                f"Tín hiệu topical: authority cụm ~{round(ca * 100)}%, relevance ~{round(tr * 100)}%."
            )
        if topical_signals.get("outside_main_cluster"):
            score -= 8.0
            limiting.append("outside_dominant_topic_cluster")
            why_not.append("Trang nằm ngoài cụm chủ đề chính của site — thường khó hưởng authority theo chủ đề.")
            improve.append("Liên kết nội bộ về pillar/hub cùng chủ đề hoặc gộp nội dung vào cluster mạnh hơn.")
        if topical_signals.get("weak_topic_coverage"):
            score -= 5.0
            limiting.append("weak_topical_coverage")
            why_not.append("Cụm chủ đề của trang mỏng (ít trang/liên kết nội bộ trong cụm).")
            improve.append("Thêm trang hỗ trợ cùng intent và liên kết chéo trong cụm.")

    kv = float((topical_signals or {}).get("keyword_volume_coverage") or 0.0)
    kr = float((topical_signals or {}).get("keyword_cluster_relevance") or 0.0)
    if kv > 0.02 or kr > 0.02:
        topical_meta["keyword_layer_applied"] = True
        boost = min(14.0, kv * 6.5 + kr * 8.0)
        score += boost
        if boost >= 4.0:
            strengths.append(
                f"Keyword intelligence: estimated demand alignment (coverage {round(kv * 100)}%, relevance {round(kr * 100)}%)."
            )

    sd = float((topical_signals or {}).get("serp_difficulty_score") or 0.0)
    if sd > 2.0:
        topical_meta["serp_difficulty_applied"] = True
        topical_meta["serp_difficulty_score"] = round(sd, 1)
        pen = min(18.0, sd * 0.12)
        score -= pen
        limiting.append("serp_competition_intensity")
        why_not.append(
            f"SERP cho cụm từ khóa liên quan có độ khó ước lượng ~{round(sd)}/100 (nhiều domain mạnh / nội dung dày)."
        )
        improve.append(
            "So khớp chiều sâu nội dung, heading, và internal link với top 10 SERP; ưu tiên đúng intent truy vấn."
        )

    score = max(0.0, min(100.0, round(score, 1)))

    if pr >= 0.55:
        strengths.append("PageRank nội bộ tương đối cao trong đợt crawl.")
    if wc >= 900 and h_score >= 0.5:
        strengths.append("Kết hợp độ sâu nội dung + heading ổn định.")

    if score >= 72.0 and len(limiting) <= 1:
        potential = "high"
    elif score >= 46.0:
        potential = "medium"
    else:
        potential = "low"

    if sd > 70.0 and potential == "high" and score < 64.0:
        potential = "medium"
        improve.append("Tiềm năng bị chặn một phần bởi SERP khó — cần nâng chất lượng on-page vượt benchmark trước khi kỳ vọng high.")

    if not strengths:
        strengths.append("Trang indexable — có thể cải thiện khi xử lý các limiting factors.")

    return {
        "ranking_score": score,
        "ranking_potential": potential,
        "limiting_factors": sorted(set(limiting)),
        "strengths": strengths[:7],
        "why_not_ranking": why_not[:8],
        "what_to_improve": improve[:8],
        "topical_modifiers": topical_meta,
    }


def prioritize_pages_for_remediation(page_insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sort URLs where **potential** is under-used (high/medium potential vs low realized score)
    or issues are **structurally fixable** (internal links, JS shell, content depth).
    """
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in page_insights:
        url = str(row.get("url") or "")
        rnk = dict(row.get("ranking") or {})
        score = float(rnk.get("ranking_score") or 0.0)
        pot = str(rnk.get("ranking_potential") or "low")
        lim = list(rnk.get("limiting_factors") or [])

        pot_w = {"high": 1.35, "medium": 1.05, "low": 0.85}.get(pot, 0.9)
        upside = max(0.0, 88.0 - score)
        fixable = sum(
            1
            for x in lim
            if x
            in (
                "orphan_page",
                "js_dependency_high",
                "js_dependency_medium",
                "thin_content",
                "deep_crawl_distance",
                "unreachable_from_entry",
                "serp_competition_intensity",
            )
        )
        pri = upside * pot_w + fixable * 9.0
        scored.append(
            (
                -pri,
                {
                    "url": url,
                    "priority_score": round(pri, 2),
                    "ranking_score": score,
                    "ranking_potential": pot,
                    "limiting_factors": lim,
                    "reason": "high_upside_fixable" if fixable and upside > 22 else "high_upside" if upside > 30 else "balanced",
                },
            )
        )
    scored.sort(key=lambda x: x[0])
    return [t[1] for t in scored]


def build_page_ranking_bundle(
    *,
    url: str,
    graph: dict[str, Any],
    pagerank_scores: dict[str, float],
    html: str,
    decision_audit: dict[str, Any] | None,
    topical_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-URL ranking + explainability using site graph + decision audit."""
    from app.services.content_analysis import analyze_content

    content = analyze_content(html)
    gmet = get_graph_metrics_for_url(graph, url, pagerank_scores)
    audit = dict(decision_audit or {})
    rs = dict(audit.get("resolved_signals") or {})
    summary = dict(audit.get("summary") or {})
    cloaking_adv = dict(audit.get("cloaking_analysis") or {})
    issues = audit.get("issues") or []

    data = {
        "indexable": bool(rs.get("final_indexability", True)),
        "js_dependency": str(rs.get("js_dependency_level") or "low").lower() in ("medium", "high"),
        "js_dependency_level": str(rs.get("js_dependency_level") or "low").lower(),
        "cloaking_risk": any(
            isinstance(it, dict) and str(it.get("rule_id")) == "cloaking_heuristic" for it in issues
        ),
        "cloaking_advanced": cloaking_adv,
        "canonical_valid": bool(rs.get("canonical_valid", True)),
        "technical_score": float(summary.get("score") or 72.0),
    }
    sim = audit.get("simulation")
    if not isinstance(sim, dict):
        sim = rs.get("google_simulation") if isinstance(rs.get("google_simulation"), dict) else {}

    rank = compute_ranking_score(data, gmet, content, sim, topical_signals=topical_signals)
    return {
        **rank,
        "graph_metrics": gmet,
        "content_metrics": content,
    }
