from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.services.internal_linking.models import InternalLinkArticle, InternalLinkChunk

log = logging.getLogger(__name__)


DEFAULT_MODEL = os.getenv("IL_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2").strip()


@lru_cache(maxsize=1)
def get_embedding_model(model_name: str | None = None) -> SentenceTransformer:
    name = (model_name or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    log.info("Loading sentence-transformers model=%s", name)
    # SentenceTransformer handles its own caching under ~/.cache by default.
    return SentenceTransformer(name)


def _to_bytes_f32(vec: np.ndarray) -> bytes:
    v = np.asarray(vec, dtype=np.float32)
    return v.tobytes(order="C")


def _from_bytes_f32(blob: bytes, dim: int) -> np.ndarray:
    if not blob or dim <= 0:
        return np.zeros((0,), dtype=np.float32)
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.size != dim:
        # corrupted or model changed; caller should handle
        return arr.astype(np.float32, copy=False)
    return arr


@dataclass(frozen=True)
class EmbedResult:
    embedding_model: str
    embedded_chunks: int
    skipped_chunks: int


def embed_chunks_for_site(
    *,
    db: Session,
    wp_site: str,
    model_name: str | None = None,
    batch_size: int = 48,
    only_missing: bool = True,
) -> EmbedResult:
    """
    Generate embeddings for chunks and store them in SQLite as float32 bytes.
    """
    mname = (model_name or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    model = get_embedding_model(mname)
    bs = max(8, min(int(batch_size), 256))

    q = (
        db.query(InternalLinkChunk)
        .join(InternalLinkArticle, InternalLinkChunk.article_id == InternalLinkArticle.id)
        .filter(InternalLinkArticle.wp_site == wp_site)
        .order_by(InternalLinkChunk.article_id.asc(), InternalLinkChunk.chunk_index.asc())
    )
    if only_missing:
        q = q.filter((InternalLinkChunk.embedding == b"") | (InternalLinkChunk.embedding_model != mname))

    embedded = 0
    skipped = 0

    buf: list[InternalLinkChunk] = []
    texts: list[str] = []

    def _flush() -> None:
        nonlocal embedded, skipped, buf, texts
        if not buf:
            return
        # SentenceTransformer returns float32 typically; we enforce.
        try:
            embs = model.encode(texts, batch_size=min(bs, len(texts)), normalize_embeddings=True, show_progress_bar=False)
        except Exception as exc:
            log.exception("Embedding encode failed for batch size=%s: %s", len(texts), exc)
            # Skip this batch (do not mark embedded) so it can be retried.
            skipped += len(buf)
            buf = []
            texts = []
            return
        embs = np.asarray(embs, dtype=np.float32)
        now = dt.datetime.now(dt.timezone.utc)
        for i, ch in enumerate(buf):
            vec = embs[i]
            ch.embedding_model = mname
            ch.embedding_dim = int(vec.shape[0])
            ch.embedding = _to_bytes_f32(vec)
            ch.embedded_at = now
            embedded += 1
        db.commit()
        buf = []
        texts = []

    for ch in q.yield_per(500):
        t = (ch.text or "").strip()
        if len(t) < 30:
            skipped += 1
            continue
        buf.append(ch)
        texts.append(t)
        if len(buf) >= bs:
            _flush()
    _flush()

    # Update counters per article (best-effort)
    try:
        arts = db.query(InternalLinkArticle).filter(InternalLinkArticle.wp_site == wp_site).all()
        for a in arts:
            total = db.query(InternalLinkChunk).filter(InternalLinkChunk.article_id == a.id).count()
            emb = (
                db.query(InternalLinkChunk)
                .filter(InternalLinkChunk.article_id == a.id, InternalLinkChunk.embedding_model == mname)
                .count()
            )
            a.chunk_count = int(total)
            a.embedded_chunk_count = int(emb)
        db.commit()
    except Exception:
        db.rollback()

    log.info("IL embed done wp_site=%s model=%s embedded=%s skipped=%s", wp_site, mname, embedded, skipped)
    return EmbedResult(embedding_model=mname, embedded_chunks=embedded, skipped_chunks=skipped)


def load_chunk_vectors(
    chunks: Sequence[InternalLinkChunk],
    *,
    expected_model: str,
) -> np.ndarray:
    """
    Return matrix shape (n, d). Any missing/corrupt vectors are dropped.
    """
    vecs: list[np.ndarray] = []
    for ch in chunks:
        if ch.embedding_model != expected_model or not ch.embedding or ch.embedding_dim <= 0:
            continue
        v = _from_bytes_f32(ch.embedding, ch.embedding_dim)
        if v.size <= 0:
            continue
        vecs.append(v.astype(np.float32, copy=False))
    if not vecs:
        return np.zeros((0, 0), dtype=np.float32)
    d = int(vecs[0].shape[0])
    out = np.zeros((len(vecs), d), dtype=np.float32)
    for i, v in enumerate(vecs):
        if v.shape[0] != d:
            continue
        out[i] = v
    return out

