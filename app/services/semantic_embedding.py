"""
Dense keyword embeddings: sentence-transformers, OpenAI, or L2-normalized TF-IDF fallback.

Vectors are L2-normalized for cosine similarity = dot product.

WAVE 5: when EMBEDDING_CELERY_WORKER=1, Uvicorn delegates ST inference to Celery worker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from functools import lru_cache
from typing import Any

import numpy as np

from app.services import embedding_cache
from app.services.embedding_worker_rollout import (
    embedding_celery_enabled,
    is_embedding_worker_process,
    uvicorn_may_load_embedding_model,
)

_LOG = logging.getLogger(__name__)

LAST_BACKEND = "unknown"
_MODEL_LOAD_COUNT = 0


def model_load_count() -> int:
    return int(_MODEL_LOAD_COUNT)


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    n = np.maximum(n, 1e-12)
    return mat / n


@lru_cache(maxsize=1)
def _get_sentence_transformer(model_name: str):
    global _MODEL_LOAD_COUNT
    from sentence_transformers import SentenceTransformer

    _LOG.info("Loading sentence-transformers model=%s", model_name)
    _MODEL_LOAD_COUNT += 1
    return SentenceTransformer(model_name)


def _embed_openai(keywords: list[str]) -> dict[str, np.ndarray] | None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    try:
        import urllib.request

        out: dict[str, np.ndarray] = {}
        batch = int(os.getenv("OPENAI_EMBEDDING_BATCH", "64"))
        for i in range(0, len(keywords), batch):
            chunk = keywords[i : i + batch]
            body = json.dumps({"model": model, "input": chunk}).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            items = sorted(data.get("data", []), key=lambda x: int(x.get("index", 0)))
            for pos, item in enumerate(items):
                if pos >= len(chunk):
                    break
                emb = np.array(item.get("embedding") or [], dtype=np.float32)
                v = _l2_normalize(emb.reshape(1, -1))[0]
                out[chunk[pos]] = v
        return out if len(out) == len(keywords) else None
    except Exception as exc:
        _LOG.debug("OpenAI embeddings failed: %s", exc)
        return None


def _embed_sentence_transformers(keywords: list[str]) -> dict[str, np.ndarray] | None:
    if not uvicorn_may_load_embedding_model() and not is_embedding_worker_process():
        return None
    model_name = (os.getenv("SEMANTIC_EMBEDDING_MODEL") or "all-MiniLM-L6-v2").strip()
    try:
        model = _get_sentence_transformer(model_name)
        vecs = model.encode(
            keywords,
            batch_size=int(os.getenv("ST_EMBEDDING_BATCH", "32")),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        out: dict[str, np.ndarray] = {}
        for i, k in enumerate(keywords):
            out[k] = np.asarray(vecs[i], dtype=np.float32).flatten()
        return out
    except Exception as exc:
        _LOG.debug("sentence-transformers not used: %s", exc)
        return None


def _embed_tfidf_dense(keywords: list[str]) -> dict[str, np.ndarray]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    max_f = min(int(os.getenv("KEYWORD_CLUSTER_MAX_FEATURES", "4096")), 8192)
    vec = TfidfVectorizer(max_features=max_f, ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    X = vec.fit_transform(keywords)
    Xd = X.toarray().astype(np.float32)
    Xn = normalize(Xd, norm="l2", axis=1)
    return {k: Xn[i] for i, k in enumerate(keywords)}


def embed_keywords_tfidf_only(keywords: list[str]) -> dict[str, np.ndarray]:
    """Fallback when Celery embedding worker unavailable."""
    global LAST_BACKEND
    uniq = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    if not uniq:
        return {}
    emb = _embed_tfidf_dense(uniq)
    LAST_BACKEND = "tfidf_dense"
    return emb


def embed_keywords_local(
    keywords: list[str],
    *,
    tenant_scope: str = "global",
    use_cache: bool = True,
) -> dict[str, np.ndarray]:
    """Run embedding in current process (embedding worker only for ST)."""
    return _embed_keywords_impl(keywords, tenant_scope=tenant_scope, use_cache=use_cache)


def embed_keywords(
    keywords: list[str],
    *,
    tenant_scope: str = "global",
    use_cache: bool = True,
) -> dict[str, np.ndarray]:
    """
    Return mapping ``keyword ->`` L2-normalized dense ``np.ndarray`` (float32).

    Resolution order: per-keyword cache → Celery worker (WAVE5) → ST → OpenAI → TF-IDF.
    """
    if embedding_celery_enabled() and not is_embedding_worker_process():
        from app.workers.embedding_tasks import embed_keywords_via_worker

        return embed_keywords_via_worker(keywords, tenant_scope=tenant_scope)
    return _embed_keywords_impl(keywords, tenant_scope=tenant_scope, use_cache=use_cache)


def _embed_keywords_impl(
    keywords: list[str],
    *,
    tenant_scope: str = "global",
    use_cache: bool = True,
) -> dict[str, np.ndarray]:
    uniq = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    if not uniq:
        return {}

    out: dict[str, np.ndarray] = {}
    pending: list[str] = []
    for k in uniq:
        digest = embedding_cache.content_hash(k)
        if use_cache:
            hit = embedding_cache.cache_get(tenant_scope=tenant_scope, digest=digest)
            if hit is not None and hit.size > 0:
                embedding_cache.record_cache_hit()
                out[k] = hit
                continue
            embedding_cache.record_cache_miss()
        pending.append(k)

    if not pending:
        return out

    global LAST_BACKEND

    emb = _embed_sentence_transformers(pending)
    if emb is not None:
        LAST_BACKEND = "sentence_transformers"
    if emb is None:
        if os.getenv("SEMANTIC_EMBEDDING_ALLOW_OPENAI", "0").strip().lower() in ("1", "true", "yes"):
            emb = _embed_openai(pending)
            if emb is not None:
                LAST_BACKEND = "openai"
    if emb is None:
        emb = _embed_tfidf_dense(pending)
        LAST_BACKEND = "tfidf_dense"

    for k, v in emb.items():
        v = np.asarray(v, dtype=np.float32).flatten()
        nv = _l2_normalize(v.reshape(1, -1))[0]
        out[k] = nv
        if use_cache:
            embedding_cache.cache_set(
                tenant_scope=tenant_scope,
                digest=embedding_cache.content_hash(k),
                vec=nv,
            )

    return out
