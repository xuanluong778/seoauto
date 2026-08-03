"""
Cluster health: orphan clusters, thin coverage, cannibalization, fragmentation.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def _slug_sig(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        t = soup.find("title")
        h1 = soup.find("h1")
        title = t.get_text(" ", strip=True)[:120] if t else ""
        h1t = h1.get_text(" ", strip=True)[:120] if h1 else ""
        return f"{title}|{h1t}".lower()
    except Exception:
        return ""


def _path_bucket(url: str) -> str:
    try:
        p = urlparse(url).path.strip("/").lower()
        parts = [x for x in p.split("/") if x][:2]
        return "/".join(parts) if parts else "/"
    except Exception:
        return ""


def analyze_cluster_health(
    cluster: dict[str, Any],
    *,
    coverage_score: float,
    authority_flow_score: float,
    pages_by_url: dict[str, dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Return cluster_health + structured issues (explainable, conservative)."""
    label = str(cluster.get("topic_label") or "")
    urls = [u for u in (cluster.get("pages") or []) if u]
    size = len(urls)
    issues: list[dict[str, Any]] = []

    nodes = dict(graph.get("nodes") or {})
    entry = set(graph.get("entry_urls_normalized") or [])
    orphan_in_cluster = 0
    for u in urls:
        inc = len((nodes.get(u) or {}).get("incoming") or [])
        if inc == 0 and u not in entry:
            orphan_in_cluster += 1
    if size >= 2 and orphan_in_cluster >= max(1, size // 2):
        issues.append(
            {
                "type": "orphan_cluster",
                "detail": f"{orphan_in_cluster}/{size} URLs trong cluster không có internal link vào (ngoài entry).",
                "severity": "medium",
            }
        )

    if coverage_score < 0.32 and size >= 2:
        issues.append(
            {
                "type": "thin_cluster",
                "detail": "Cluster thiếu chiều sâu thực thể / từ vựng so với kỳ vọng cho số trang.",
                "severity": "medium",
            }
        )

    # Cannibalization: same cluster + very similar title/H1
    sigs: list[tuple[str, str]] = []
    for u in urls:
        html = str((pages_by_url.get(u) or {}).get("html") or "")
        sigs.append((u, _slug_sig(html)))
    buckets: dict[str, list[str]] = {}
    for u, s in sigs:
        if len(s) < 12:
            continue
        key = re.sub(r"\s+", " ", s)[:80]
        buckets.setdefault(key, []).append(u)
    for key, us in buckets.items():
        if len(us) >= 2:
            issues.append(
                {
                    "type": "cannibalization_risk",
                    "detail": f"Hai+ URL trùng intent (title/H1 gần giống): {', '.join(us[:4])}",
                    "severity": "low",
                }
            )

    # Over-fragmentation: many URLs same path bucket + small cluster spread
    path_groups: dict[str, int] = {}
    for u in urls:
        path_groups[_path_bucket(u)] = path_groups.get(_path_bucket(u), 0) + 1
    if size >= 5 and path_groups and max(path_groups.values()) >= size - 1:
        issues.append(
            {
                "type": "over_fragmentation",
                "detail": "Hầu hết URL cluster nằm cùng nhánh đường dẫn — dễ trùng lặp micro-topic.",
                "severity": "low",
            }
        )

    if authority_flow_score < 0.28 and size >= 3:
        issues.append(
            {
                "type": "weak_authority_flow",
                "detail": "PageRank / liên kết có trọng số trong cluster không đủ mạnh để truyền authority.",
                "severity": "medium",
            }
        )

    sev_rank = {"high": 3, "medium": 2, "low": 1}
    score_health = 1.0 - min(0.85, 0.12 * len(issues))
    if any(sev_rank.get(str(i.get("severity")), 0) >= 3 for i in issues):
        cluster_health = "weak"
    elif coverage_score < 0.4 or len(issues) >= 2:
        cluster_health = "medium"
    else:
        cluster_health = "strong"

    return {
        "cluster_health": cluster_health,
        "issues": issues[:12],
        "metrics": {
            "orphan_pages_in_cluster": orphan_in_cluster,
            "cluster_size": size,
            "topic_label": label,
        },
        "explain": "Heuristic: internal graph orphans, coverage thinness, duplicate title/H1 intent, path concentration.",
    }
