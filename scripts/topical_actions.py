"""
Actionable topical recommendations (cluster-level), explainable.
"""

from __future__ import annotations

from typing import Any


def build_topical_actions(
    *,
    topic: str,
    coverage: dict[str, Any],
    gap: dict[str, Any],
    health: dict[str, Any],
    flow: dict[str, Any],
    authority: dict[str, Any],
    serp_pkg: dict[str, Any] | None = None,
    cluster_intent: dict[str, Any] | None = None,
    entity_groups: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Return high-signal action strings (Vietnamese + English mix like rest of platform)."""
    actions: list[str] = []

    for r in gap.get("misalignment_reasons") or []:
        if isinstance(r, str) and r.strip():
            actions.append(f"SERP alignment: {r}")

    if serp_pkg:
        sf = list(serp_pkg.get("serp_formats") or [])
        st = str(serp_pkg.get("serp_dominant_type") or "")
        if sf:
            actions.append(
                f"Ưu tiên format theo SERP: {', '.join(sf)} (dominant site type SERP: {st or 'blog'})."
            )
        si = str(serp_pkg.get("serp_intent") or "")
        ci = str((cluster_intent or {}).get("dominant_intent") or "")
        if si and ci and si != ci:
            actions.append(f"Align content tới intent SERP «{si}»; cluster hiện lệch «{ci}».")

    if entity_groups:
        weak_e = [g.get("canonical_entity") for g in entity_groups[:5] if float(g.get("confidence") or 1) < 0.72]
        if weak_e:
            actions.append(
                "Củng cố entity chưa chắc chắn: " + ", ".join(str(x) for x in weak_e if x) + " — thêm mention ngữ cảnh + internal link."
            )

    cov_lvl = str(coverage.get("coverage_level") or "")
    miss = list(coverage.get("missing_subtopics") or [])
    if cov_lvl == "low" or float(coverage.get("coverage_score") or 0) < 0.38:
        actions.append("Bổ sung 3–6 supporting articles bao phủ subtopic còn thiếu trong cluster.")
    if miss[:5]:
        actions.append(
            "Mở rộng entity/subtopic: " + ", ".join(miss[:5]) + " — xuất hiện trên SERP nhưng chưa thấy trong cụm."
        )

    for m in gap.get("missing_content_types") or []:
        if m == "pillar_page" or m == "deep_guide_or_pillar":
            actions.append("Tạo hoặc củng cố pillar page (depth + outline theo SERP leaders).")
        elif m == "supporting_articles":
            actions.append("Add supporting articles: tăng số URL có intent phụ cùng topic cluster.")
        elif m == "faq_or_comparison_block":
            actions.append("Thêm khối FAQ / so sánh thực thể để khớp heading patterns của top SERP.")
        elif m == "entity_expansion":
            actions.append("Mở rộng ngữ cảnh thực thể (ví dụ, ví dụ case, thuật ngữ liên quan) trong body.")

    if float(flow.get("authority_flow_score") or 0) < 0.42:
        actions.append(
            "Cải thiện internal linking có anchor mô tả: nối các URL yếu trong cluster tới hub mạnh nhất."
        )

    for iss in health.get("issues") or []:
        t = str(iss.get("type") or "")
        if t == "cannibalization_risk":
            actions.append("Gộp hoặc phân vai trò canonical: giảm cannibalization giữa URL cùng intent.")
        elif t == "orphan_cluster":
            actions.append("Thêm inbound internal links từ menu/category/pillar vào các URL orphan trong cluster.")
        elif t == "over_fragmentation":
            actions.append("Giảm phân mảnh: map lại URL vào ít landing hơn với internal link rõ ràng.")

    if str(health.get("cluster_health") or "") == "weak":
        actions.append("Ưu tiên cluster này trong editorial calendar — cluster_health = weak.")

    if float(authority.get("authority_score") or 0) >= 0.62 and not actions:
        actions.append("Duy trì cluster: bổ sung freshness + case study nhỏ để giữ vị thế topical.")

    if not actions:
        actions.append("Tiếp tục đo SERP + entity graph định kỳ; hiện tại không có gap rõ ràng từ heuristic.")

    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out[:12]
