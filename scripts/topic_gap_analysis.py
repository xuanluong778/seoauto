"""
Surface weak topical clusters and expansion opportunities (heuristic).
"""

from __future__ import annotations

from typing import Any


def detect_topic_gaps(
    clusters: dict[str, dict[str, Any]],
    *,
    authority_by_cluster: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    ``clusters``: cluster_id -> { topic_label, pages, cluster_size }.
    ``authority_by_cluster``: optional cluster_id -> output of ``compute_topical_authority``.
    """
    authority_by_cluster = authority_by_cluster or {}
    weak_clusters: list[dict[str, Any]] = []
    missing_topics: list[str] = []
    expansion_opportunities: list[str] = []

    labels_seen: set[str] = set()
    dominant_labels: list[str] = []

    for cid, c in sorted(clusters.items(), key=lambda x: -(x[1].get("cluster_size") or 0)):
        size = int(c.get("cluster_size") or 0)
        label = str(c.get("topic_label") or "mixed")
        auth = authority_by_cluster.get(cid) or {}
        auth_score = float(auth.get("authority_score") or 0.0)
        ils = float(auth.get("internal_linking_score") or 0.0)
        cov = float(auth.get("coverage_score") or 0.0)

        if label and label not in ("mixed", "unknown"):
            labels_seen.add(label)
            if size >= 3:
                dominant_labels.append(label)

        if size < 3 or auth_score < 32.0 or ils < 0.22 or cov < 0.35:
            weak_clusters.append(
                {
                    "cluster_id": cid,
                    "topic_label": label,
                    "cluster_size": size,
                    "authority_score": auth_score,
                    "reasons": _reason_flags(size, auth_score, ils, cov),
                }
            )

    # "Missing" = common head terms not represented as a non-trivial cluster label
    all_pages = sum(len(c.get("pages") or []) for c in clusters.values())
    for cid, c in clusters.items():
        label = str(c.get("topic_label") or "")
        size = int(c.get("cluster_size") or 0)
        if size == 1 and all_pages > 6 and label not in ("unknown", "mixed"):
            missing_topics.append(f"orphan_topic:{label}")

    if weak_clusters:
        expansion_opportunities.append(
            "Tăng số trang và liên kết nội bộ trong các cluster yếu để tạo khối chủ đề rõ ràng."
        )
    if any(w["cluster_size"] < 2 for w in weak_clusters):
        expansion_opportunities.append(
            "Gom các URL đơn lẻ vào hub/pillar cùng chủ đề hoặc viết thêm nội dung hỗ trợ."
        )
    if not expansion_opportunities:
        expansion_opportunities.append(
            "Duy trì nội dung sâu và liên kết ngang trong cluster mạnh; mở ràng biên chủ đề có kiểm soát."
        )

    return {
        "weak_clusters": weak_clusters[:40],
        "missing_topics": missing_topics[:30],
        "expansion_opportunities": expansion_opportunities[:12],
    }


def _reason_flags(size: int, auth: float, ils: float, cov: float) -> list[str]:
    r: list[str] = []
    if size < 3:
        r.append("few_pages")
    if auth < 32.0:
        r.append("low_authority")
    if ils < 0.22:
        r.append("weak_internal_linking")
    if cov < 0.35:
        r.append("shallow_coverage")
    return r
