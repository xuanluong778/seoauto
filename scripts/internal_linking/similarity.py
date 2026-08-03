from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

log = logging.getLogger(__name__)


def cosine_top_k(
    *,
    query: np.ndarray,
    matrix: np.ndarray,
    k: int = 10,
    min_score: float = 0.28,
) -> list[tuple[int, float]]:
    """
    Compute cosine similarity between a query vector and a matrix of normalized vectors.
    Assumes query and matrix rows are already L2-normalized.
    Returns list of (row_index, score) sorted desc.
    """
    if query.ndim != 1 or matrix.ndim != 2 or matrix.shape[0] == 0:
        return []
    if matrix.shape[1] != query.shape[0]:
        return []
    kk = max(1, min(int(k), max(1, matrix.shape[0])))
    scores = np.dot(matrix, query).astype(np.float32, copy=False)
    # Partial top-k for speed
    if scores.shape[0] > kk:
        idx = np.argpartition(scores, -kk)[-kk:]
        idx = idx[np.argsort(scores[idx])[::-1]]
    else:
        idx = np.argsort(scores)[::-1]
    out: list[tuple[int, float]] = []
    for i in idx:
        s = float(scores[int(i)])
        if s < float(min_score):
            continue
        out.append((int(i), s))
    return out


@dataclass(frozen=True)
class SimilarityHit:
    chunk_id: int
    article_id: int
    url: str
    title: str
    score: float
    heading_path: str
    heading_text: str


def dedupe_by_article(
    hits: Sequence[SimilarityHit],
    *,
    max_per_article: int = 1,
) -> list[SimilarityHit]:
    out: list[SimilarityHit] = []
    used: dict[int, int] = {}
    for h in hits:
        used.setdefault(h.article_id, 0)
        if used[h.article_id] >= max_per_article:
            continue
        used[h.article_id] += 1
        out.append(h)
    return out

