"""
Semantic cosine similarity matrix from embedding dict (batch-friendly, cache-friendly).
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


def compute_semantic_similarity_matrix(
    keywords: list[str],
    embeddings: dict[str, np.ndarray],
) -> tuple[np.ndarray, list[str]]:
    """
    Returns ``(matrix, ordered_keywords)`` where ``matrix[i,j]`` is cosine similarity
    between ``ordered_keywords[i]`` and ``ordered_keywords[j]``.
    """
    ordered = [k for k in keywords if k in embeddings]
    if not ordered:
        return np.zeros((0, 0)), []
    mat = np.stack([np.asarray(embeddings[k], dtype=np.float32).flatten() for k in ordered])
    sim = cosine_similarity(mat)
    np.clip(sim, 0.0, 1.0, out=sim)
    return sim.astype(np.float32), ordered
