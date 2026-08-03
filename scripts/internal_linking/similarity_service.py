from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.services.internal_linking.embeddings import DEFAULT_MODEL, get_embedding_model
from app.services.internal_linking.models import InternalLinkArticle, InternalLinkChunk
from app.services.internal_linking.similarity import SimilarityHit, cosine_top_k, dedupe_by_article

log = logging.getLogger(__name__)


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v) + 1e-12)
    return (v / n).astype(np.float32, copy=False)


def _vec_from_chunk(ch: InternalLinkChunk) -> np.ndarray | None:
    if not ch.embedding or ch.embedding_dim <= 0:
        return None
    try:
        arr = np.frombuffer(ch.embedding, dtype=np.float32)
        if arr.size != ch.embedding_dim:
            return None
        return arr.astype(np.float32, copy=False)
    except Exception:
        return None


@dataclass(frozen=True)
class SuggestOptions:
    k: int = 24
    min_score: float = 0.30
    max_results: int = 8
    max_per_article: int = 1
    model_name: str = DEFAULT_MODEL


def suggest_related_articles_for_text(
    *,
    db: Session,
    wp_site: str,
    source_text: str,
    exclude_url: str = "",
    options: SuggestOptions | None = None,
) -> list[SimilarityHit]:
    opt = options or SuggestOptions()
    model = get_embedding_model(opt.model_name)
    qvec = model.encode([source_text], normalize_embeddings=True, show_progress_bar=False)
    q = _norm(np.asarray(qvec[0], dtype=np.float32))

    # Load candidate chunks with embeddings
    chunks = (
        db.query(InternalLinkChunk, InternalLinkArticle)
        .join(InternalLinkArticle, InternalLinkChunk.article_id == InternalLinkArticle.id)
        .filter(InternalLinkArticle.wp_site == wp_site, InternalLinkChunk.embedding_model == opt.model_name)
        .all()
    )
    if not chunks:
        return []

    vecs: list[np.ndarray] = []
    meta: list[tuple[InternalLinkChunk, InternalLinkArticle]] = []
    for ch, art in chunks:
        if exclude_url and str(art.url or "").strip() == exclude_url:
            continue
        v = _vec_from_chunk(ch)
        if v is None:
            continue
        vecs.append(v)
        meta.append((ch, art))
    if not vecs:
        return []

    mat = np.vstack([_norm(v) for v in vecs]).astype(np.float32, copy=False)
    top = cosine_top_k(query=q, matrix=mat, k=int(opt.k), min_score=float(opt.min_score))

    hits: list[SimilarityHit] = []
    for idx, score in top:
        ch, art = meta[int(idx)]
        hits.append(
            SimilarityHit(
                chunk_id=int(ch.id),
                article_id=int(art.id),
                url=str(art.url or ""),
                title=str(art.title or ""),
                score=float(score),
                heading_path=str(ch.heading_path or ""),
                heading_text=str(ch.heading_text or ""),
            )
        )

    hits.sort(key=lambda x: x.score, reverse=True)
    hits = dedupe_by_article(hits, max_per_article=int(opt.max_per_article))
    return hits[: int(opt.max_results)]

