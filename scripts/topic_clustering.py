"""
Topic clusters from per-page keyword/topic features — overlap + cosine on tiny bags.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


def _bag(page: dict[str, Any]) -> Counter[str]:
    primary = str(page.get("primary_topic") or "").strip().lower()
    secs = [str(x).strip().lower() for x in (page.get("secondary_topics") or []) if str(x).strip()]
    kws = [str(x).strip().lower() for x in (page.get("keywords") or []) if str(x).strip()]
    c: Counter[str] = Counter()
    if primary and primary != "unknown":
        c[primary] += 4
    for s in secs[:12]:
        c[s] += 2
    for k in kws[:80]:
        c[k] += 1
    return c


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _similarity(bag_a: Counter[str], bag_b: Counter[str]) -> float:
    sa = set(bag_a)
    sb = set(bag_b)
    jac = _jaccard(sa, sb)
    cos = _cosine(bag_a, bag_b)
    return max(jac, 0.65 * cos + 0.35 * jac)


def cluster_topics(pages_topics: list[dict[str, Any]], *, merge_threshold: float = 0.18) -> dict[str, Any]:
    """
    Group pages into topic clusters using keyword overlap / cosine on small bags.

    ``pages_topics`` items: ``url`` + fields from ``extract_topics`` (``primary_topic``,
    ``secondary_topics``, ``keywords``).

    Returns:
        clusters: cluster_id -> { topic_label, pages, cluster_size }
        page_cluster: url -> cluster_id
    """
    pages = [p for p in pages_topics if str(p.get("url") or "").strip()]
    if not pages:
        return {"clusters": {}, "page_cluster": {}}

    bags = [_bag(p) for p in pages]
    n = len(pages)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if _similarity(bags[i], bags[j]) >= merge_threshold:
                union(i, j)

    root_to_pages: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        root_to_pages.setdefault(r, []).append(i)

    clusters: dict[str, dict[str, Any]] = {}
    page_cluster: dict[str, str] = {}
    cid = 0
    for _root, idxs in sorted(root_to_pages.items(), key=lambda x: -len(x[1])):
        cluster_pages = [str(pages[i].get("url")) for i in idxs]
        label_counter: Counter[str] = Counter()
        for i in idxs:
            pt = str(pages[i].get("primary_topic") or "").strip().lower()
            if pt and pt != "unknown":
                label_counter[pt] += 3
            for s in pages[i].get("secondary_topics") or []:
                st = str(s).strip().lower()
                if st:
                    label_counter[st] += 1
        topic_label = "mixed"
        if label_counter:
            topic_label = label_counter.most_common(1)[0][0]
        key = f"c{cid}"
        clusters[key] = {
            "topic_label": topic_label,
            "pages": cluster_pages,
            "cluster_size": len(cluster_pages),
        }
        for u in cluster_pages:
            page_cluster[u] = key
        cid += 1

    return {"clusters": clusters, "page_cluster": page_cluster}
