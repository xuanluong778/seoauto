"""
Iterative PageRank on the induced internal-link graph (damping 0.85, normalized scores).
"""

from __future__ import annotations

from typing import Any


def compute_pagerank(
    graph: dict[str, Any],
    *,
    damping: float = 0.85,
    max_iter: int = 80,
    tol: float = 1e-6,
) -> dict[str, float]:
    """
    ``graph`` is the return value of ``build_link_graph`` (expects ``nodes``).

    Dead ends redistribute mass uniformly to all nodes (standard teleport fix).

    Returns mapping ``url -> score`` in ``[0, 1]`` (min–max normalized across the crawl).
    """
    nodes_dict: dict[str, dict[str, list[str]]] = dict(graph.get("nodes") or {})
    urls = sorted(nodes_dict.keys())
    n = len(urls)
    if n == 0:
        return {}
    if n == 1:
        return {urls[0]: 1.0}

    idx = {u: i for i, u in enumerate(urls)}
    out_adj: list[list[int]] = []
    for u in urls:
        outs = nodes_dict[u].get("outgoing") or []
        out_adj.append([idx[v] for v in outs if v in idx])

    pr = [1.0 / n] * n
    base = (1.0 - damping) / n

    for _ in range(max_iter):
        new = [base] * n
        dangling_mass = 0.0
        for i, targets in enumerate(out_adj):
            share = damping * pr[i]
            if not targets:
                dangling_mass += share
            else:
                w = share / len(targets)
                for j in targets:
                    new[j] += w
        if dangling_mass > 0:
            add = dangling_mass / n
            for i in range(n):
                new[i] += add
        delta = sum(abs(new[i] - pr[i]) for i in range(n))
        pr = new
        if delta < tol:
            break

    mn, mx = min(pr), max(pr)
    span = mx - mn
    if span <= 1e-12:
        norm = {urls[i]: 1.0 / n for i in range(n)}
    else:
        norm = {urls[i]: (pr[i] - mn) / span for i in range(n)}
    return norm
